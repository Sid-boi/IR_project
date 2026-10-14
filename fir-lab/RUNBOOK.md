# Runbook — reproduce the experiment end to end

Copy-paste commands. Windows users: **PowerShell only**, not Git Bash.
Each command is on one line — no backslash continuations.

Total time: about 60 minutes, most of it waiting for the enriched index build.

---

## 0. Setup (once)

```
git clone <repo-url> fir-lab
cd fir-lab
mkdir data runs
cp .env.example .env
```

`data/` and `runs/` are not in git (they are gitignored), so you must create
them yourself. Make them **before** `docker compose up` — Docker will create
missing bind-mount folders as root and the notebooks then cannot write into
`runs/`.

Download `data01.zip` from Canvas. Unzip into `data/` so you get
`data/FIR-s05-medline.json` — **not** `data/data01/FIR-s05-medline.json`.

```
unzip data01.zip -d data/
```

If it extracts a nested `data/data01/` folder, move the files up one level:

```
# PowerShell
Move-Item data\data01\* data\ ; Remove-Item data\data01

# bash
mv data/data01/* data/ && rmdir data/data01
```

Your tree should look like this before you start:

```
fir-lab/
  data/            <- you create, then unzip into it
    FIR-s05-medline.json
    FIR-s05-training-queries-simple.txt
    FIR-s05-training-qrels.txt
    test-queries-simple.txt
  runs/            <- you create, stays empty for now
  notebooks/
  scripts/
  workbench/
  docker-compose.yml
  .env             <- you create from .env.example
```

```
docker compose up -d --build
```

Wait 60 seconds. Check it is alive:

```
curl http://localhost:9200
```

Jupyter: http://localhost:8888 · Kibana: http://localhost:5601

---

## 1. Baseline index — 2 min

```
docker exec fir-workbench python scripts/01_index.py --recreate
```

✅ Expect: `Count: 263,080`, `Errors: 0`

---

## 2. Baseline retrieval — 30 s

```
docker exec fir-workbench python scripts/02_retrieve.py
```

```
docker exec fir-workbench head -3 /work/runs/bm25_baseline.run
```

✅ Expect column 3 to be a PMID like `12368211`, not a small number like `3`.
If it is a small number, the run file is broken and evaluation will give 0.

---

## 3. Baseline evaluation — 10 s

```
docker exec fir-workbench python scripts/03_evaluate.py --qrels /work/data/FIR-s05-training-qrels.txt --run /work/runs/bm25_baseline.run
```

✅ Expect: `map 0.0855`, `recall@100 0.3799`

---

## 4. Notebook 02 — data exploration — 5 min

Open `02_explore.ipynb`, run all cells.

✅ Expect:
- query types: 34 gene_descriptor, 4 gene_with_aliases
- vocabulary gap: 0 of 38 topics
- writes `data/query_classifications.json`

---

## 5. Notebook 03 — analyzer gate + enriched index — 40 min

Open `03_index_design.ipynb`.

Run Sections 1 and 2. **Stop and check Section 2 prints `✓ GO`.**
If it prints `✗ NO-GO`, fix the analyzer in `scripts/07_enrich_index.py`
and rerun Section 2 before going further.

Then run Section 3 (or the shell command below) and wait.

```
docker exec fir-workbench python scripts/07_enrich_index.py --recreate
```

✅ Expect: `Count: 263,080`, `Errors: 0`, roughly 25 min

Then verify species detection worked:

```
curl -s "http://localhost:9200/medline_enriched/_search" -H "Content-Type: application/json" -d "{\"size\":0,\"aggs\":{\"species\":{\"terms\":{\"field\":\"species_norm\",\"size\":10}}}}"
```

✅ Expect roughly:
```
Homo sapiens              184,000   (70%)
unknown                    55,000   (21%)
Rattus norvegicus          12,000
Mus musculus               10,000
Drosophila melanogaster     1,000
```

❌ If `unknown` is above 80%, species detection is broken. Check that
`normalise_species()` in `07_enrich_index.py` reads MeSH headings, not just
free text. Rebuild after fixing.

---

## 6. Enriched retrieval — 2 min total

Main system:

```
docker exec fir-workbench python scripts/08_enrich_retrieve.py --index medline_enriched --queries /work/data/FIR-s05-training-queries-simple.txt --qunderstanding /work/data/query_classifications.json --strategy anti_pollution --run /work/runs/enriched_anti_pollution_v3.run
```

Ablation control 1 — analyzer only:

```
docker exec fir-workbench python scripts/08_enrich_retrieve.py --index medline_enriched --strategy baseline_fields --run /work/runs/enriched_baseline_fields.run
```

Ablation control 2 — enriched fields:

```
docker exec fir-workbench python scripts/08_enrich_retrieve.py --index medline_enriched --strategy enriched_fields --run /work/runs/enriched_fields.run
```

---

## 7. Main result — 10 s

```
docker exec fir-workbench python scripts/03_evaluate.py --qrels /work/data/FIR-s05-training-qrels.txt --run /work/runs/enriched_anti_pollution_v3.run --baseline /work/runs/bm25_baseline.run
```

✅ Expect:
```
map          0.1802
ndcg@10      0.2144
precision@5  0.1000
recall@100   0.5855

significant vs baseline: yes
```

---

## 8. Notebook 04 — full evaluation — 10 min

Open `04_evaluate.ipynb`, run all cells.

Produces, into `runs/`:
- `results_table.csv`
- `per_topic_ap.png` — win/loss bar chart, 29/6
- `pr_curves.png` — 11-point interpolated
- `pareto_scatter.png`
- `per_type_breakdown.png`
- `feature_importance.png` (from the LTR section)

---

## Expected numbers — check against these

| System | MAP | recall@100 | p-value |
|---|---|---|---|
| BM25 baseline | 0.0855 | 0.380 | — |
| Analyzer only | 0.0864 | 0.369 | 0.934 |
| Enriched fields | 0.0877 | 0.382 | 0.845 |
| Anti-pollution v2 | 0.1508 | 0.590 | 0.031 |
| Anti-pollution v3 | 0.1802 | 0.586 | 0.004 |

If your numbers are within ±0.002 you have reproduced it correctly.

---

## If something breaks

| Symptom | Cause | Fix |
|---|---|---|
| `map 0.0000` | run file has sequential ids not PMIDs | check `_source.PMID` is used in the retrieve script |
| `no such index [medline]` | index not built, or wrong `--index` | run step 1, pass `--index medline_enriched` explicitly |
| `unknown field [pub_year]` | querying the baseline index with an enriched query | add `--index medline_enriched` |
| all docker commands fail on Windows | using Git Bash | switch to PowerShell |
| `species_norm` 87% unknown | free-text species detection | make `normalise_species()` read MeSH first, rebuild |
| `IndexError` in `evaluate(...)` | ranx returns an array not a dict | pass metric as a string, not a list |
| `libgomp.so.1 not found` | lightgbm missing a system lib | `docker exec fir-workbench apt-get update && apt-get install -y libgomp1` |

---

## Reset everything

```
docker compose down
docker compose up -d
```

Indexes survive this. To wipe them too:

```
docker compose down -v
```
