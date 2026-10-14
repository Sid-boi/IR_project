# FIR Project — Text Retrieval on TREC Genomics 2005

Foundations of Information Retrieval, University of Twente.

We test whether enriching an Elasticsearch index with biomedical domain
knowledge improves retrieval over a plain BM25 baseline, and find that the
improvement comes from somewhere other than where we expected.

---

## Headline result

| System | MAP | NDCG@10 | P@5 | recall@100 | Significant? |
|---|---|---|---|---|---|
| BM25 baseline | 0.086 | 0.102 | 0.047 | 0.380 | — |
| Analyzer only | 0.086 | 0.103 | 0.047 | 0.369 | no (p=0.93) |
| Enriched fields | 0.088 | 0.101 | 0.047 | 0.382 | no (p=0.85) |
| Species-aware (v2) | 0.151 | 0.176 | 0.079 | 0.590 | yes (p=0.031) |
| Species-aware (v3) | **0.180** | **0.214** | **0.100** | **0.586** | yes (p=0.004) |

29 of 38 topics improved, 6 got worse. Bootstrap 95% CI `[+0.043, +0.161]`.

**The finding:** index enrichment (stemming, MeSH, gene aliases) produced no
significant gain on its own. A species-aware multiplicative scoring boost
produced all of it.

---

## Research questions

**RQ1** — Is the retrieval failure caused by vocabulary coverage (relevant
documents not retrievable) or by ranking (retrievable but ranked too low)?

**RQ2** — Does index-side enrichment — biomedical analyzer, MeSH concept
indexing, gene alias expansion — significantly improve MAP and recall@100
over plain BM25?

**RQ3** — Does species, a structural signal present in every topic, applied as
a multiplicative scoring boost, improve retrieval beyond index enrichment?

**H0** — Each treated system performs the same as the BM25 baseline.

Answers: RQ1 → ranking. RQ2 → rejected, no significant gain. RQ3 → accepted.

---

## Quick start

### 1. Prerequisites

- Docker Desktop (running)
- ~6 GB free disk
- 8 GB RAM minimum

### 2. Clone and configure

```bash
git clone <repo-url> fir-lab
cd fir-lab
mkdir data runs
cp .env.example .env
```

`data/` and `runs/` are gitignored, so they are not in the clone — create them
yourself before starting Docker. If you let Docker create them, on Linux they
come out owned by root and the notebooks cannot write run files.

### 3. Get the data

The corpus is 146 MB and is **not** in this repo. Download `data01.zip` from
Canvas and unzip it so the files land directly in `data/`:

```bash
unzip data01.zip -d data/
```

You should end up with:

```
data/
  FIR-s05-medline.json                   490 MB, 263,080 documents
  FIR-s05-training-queries-simple.txt     38 training topics
  FIR-s05-training-qrels.txt              relevance judgments
  test-queries-simple.txt                 50 test topics (no qrels)
```

If the zip creates a nested `data/data01/` folder, move the files up one level.
The scripts expect `/work/data/FIR-s05-medline.json`, not `/work/data/data01/...`.

### 4. Start the stack

```bash
docker compose up -d --build
```

Three containers start:

| Service | Port | What it is |
|---|---|---|
| `fir-es` | 9200 | Elasticsearch 7.17 |
| `fir-kibana` | 5601 | Kibana — for ad-hoc queries |
| `fir-workbench` | 8888 | Jupyter + Python libs |

Wait about 60 seconds, then check:

```bash
curl http://localhost:9200
```

Open Jupyter at **http://localhost:8888** (no token needed).

---

## Reproducing the experiment

Run these in order. On Windows use **PowerShell**, not Git Bash — Git Bash
rewrites container paths and breaks every command.

### Step 1 — Baseline index (~2 min)

```bash
docker exec fir-workbench python scripts/01_index.py --recreate
```

Expect `Count: 263,080` and `Errors: 0`.

### Step 2 — Baseline retrieval (~30 s)

```bash
docker exec fir-workbench python scripts/02_retrieve.py
```

Check the run file uses PMIDs, not sequential ids:

```bash
docker exec fir-workbench head -3 /work/runs/bm25_baseline.run
```

You want `1 Q0 12368211 1 61.5 bm25_baseline` — a real PMID in column 3.

### Step 3 — Baseline evaluation

```bash
docker exec fir-workbench python scripts/03_evaluate.py --qrels /work/data/FIR-s05-training-qrels.txt --run /work/runs/bm25_baseline.run
```

Expect `map 0.0855`.

### Step 4 — Notebook 02: data exploration (~5 min)

Open `02_explore.ipynb` in Jupyter and run top to bottom. This produces the
query-type distribution, the vocabulary-gap measurement and the field
discrimination analysis that justify every design choice downstream.

It writes `data/query_classifications.json`, which later scripts read.

### Step 5 — Notebook 03: analyzer validation + enriched index

Open `03_index_design.ipynb`. **Section 2 must print `✓ GO` before you run
Section 3.** The analyzer cannot be changed after indexing without a full
rebuild, so it is validated first.

Section 3 builds the enriched index. Takes 20–40 min. Or from the shell:

```bash
docker exec fir-workbench python scripts/07_enrich_index.py --recreate
```

Verify the species field populated correctly — this matters, see Gotchas:

```bash
curl -s "http://localhost:9200/medline_enriched/_search" -H "Content-Type: application/json" -d "{\"size\":0,\"aggs\":{\"species\":{\"terms\":{\"field\":\"species_norm\",\"size\":10}}}}"
```

Expect roughly 70% `Homo sapiens`, 21% `unknown`. If `unknown` is above 80%,
the species detection is broken — see Gotchas.

### Step 6 — Enriched retrieval (~30 s per strategy)

The main system:

```bash
docker exec fir-workbench python scripts/08_enrich_retrieve.py --index medline_enriched --queries /work/data/FIR-s05-training-queries-simple.txt --qunderstanding /work/data/query_classifications.json --strategy anti_pollution --run /work/runs/enriched_anti_pollution_v3.run
```

The two ablation controls:

```bash
docker exec fir-workbench python scripts/08_enrich_retrieve.py --index medline_enriched --strategy baseline_fields --run /work/runs/enriched_baseline_fields.run

docker exec fir-workbench python scripts/08_enrich_retrieve.py --index medline_enriched --strategy enriched_fields --run /work/runs/enriched_fields.run
```

### Step 7 — Notebook 04: full evaluation

Open `04_evaluate.ipynb` and run top to bottom. Produces the metric table,
ablation table, significance tests, per-topic AP chart, PR curves, Pareto
scatter, per-query-type breakdown and failure analysis. Images land in `runs/`.

### Optional — Notebook 04c: species weight tuning

Grid search over the species boost weight. No reindex needed.

---

## The four retrieval strategies

`08_enrich_retrieve.py` implements four strategies. They form the ablation.

| Strategy | Fields queried | Species | Purpose |
|---|---|---|---|
| `baseline_fields` | TI, AB | none | control on the enriched index — isolates the analyzer |
| `enriched_fields` | + gene_context, mesh_clean | soft | adds the enriched fields |
| `biz_context` | + concept_context | soft | adds MeSH concepts |
| `anti_pollution` | all, isolated | soft + layers | the main system |

### What `anti_pollution` does

"Pollution" = irrelevant documents crowding the top of the ranking. Four
layers, each blocking a different source of noise.

**Layer 1 — ambiguous query handling.** Four test-set topics (`fat`, `numb`,
`brahma`, `reaper`) are both English words and Drosophila gene names. For
these, alias expansion is disabled and species becomes a hard filter rather
than a boost.

**Layer 2 — field isolation.** `gene_context` is queried as its own `match`
clause rather than being folded into the `multi_match`. This stops an exact
alias hit from distorting the IDF weighting of the prose fields.

**Layer 3 — multiplicative species boost.** The core mechanism.

```python
'function_score': {
    'functions': [{'filter': {'term': {'species_norm': species}},
                   'weight': 0.5}],
    'score_mode': 'sum',        # 1.0 base + 0.5 = 1.5
    'boost_mode': 'multiply'    # x the BM25 score
}
```

A same-species document gets a proportional 1.5x uplift. We did not use an
additive `should` boost because a fixed `+5` would swamp a BM25 score of 0.08
and be invisible on a score of 8.0. Multiplicative stays proportional at every
scale.

Cross-species papers are demoted, not excluded — mouse work on a human gene is
still relevant evidence, just less so.

**Layer 4 — recency decay.** Gaussian on `pub_year` at weight 0.05. A
tiebreaker, nothing more.

Honest caveat: layers 1, 2 and 4 are present in both the v2 and v3 runs, so
the ablation cannot separate their individual contributions. Only layer 3 was
isolated, and it accounts for essentially the whole gain.

---

## Index design

Two indexes.

**`medline`** — plain BM25, standard English analyzer, fields TI/AB/MH.
This is the control.

**`medline_enriched`** — three changes:

1. **`biomedical_prose` analyzer** for TI, AB, MH, concept_context
   - Greek char filter: `α` to `alpha`
   - custom stopwords that keep `a b c d` (they are gene subunits)
   - synonym graph: `inhibitory` to `inhibitor`, `regulatory` to `regulator`
   - Porter stemmer (`english`), applied *after* the synonyms

2. **`biomedical_exact` analyzer** for `gene_context`
   - whitespace tokenizer, uppercase filter, **no stemming**
   - so `BCL2` stays `BCL2` and does not stem to `bcl`

3. **`species_norm` keyword field**
   - detected from MeSH headings first (`Humans`, `Mice`, `Rats`)
   - free-text pattern matching as fallback

BM25 tuned to `k1=1.5, b=0.30`. The default `b=0.75` penalises long documents
heavily; MEDLINE abstracts are short and uniform, so less length normalisation
fits better.

Field boosts: TI 2.0x, AB 1.0x, MeSH 1.5x, gene_context 3.0x.

---

## Gotchas

**PMID is not the document id.** The corpus ships as bulk NDJSON where `_id`
is a sequential counter (3, 4, 5...). The qrels use PMIDs. Every run file must
write `_source.PMID`, never `hit['_id']`. If your MAP comes out as 0.0000,
this is why.

**Species detection must read MeSH, not free text.** MEDLINE abstracts almost
never contain the word "human" — the species lives in the MeSH heading
`Humans`. An earlier version used free-text matching and tagged 87% of
documents `unknown`, which left the species boost running at roughly 13%
capacity. Fixing it moved MAP from 0.151 to 0.180.

**Use PowerShell on Windows.** Git Bash rewrites `/work/data/...` into
`C:/Program Files/Git/work/data/...` and every `docker exec` fails.

**No backslash line continuations on Windows.** PowerShell treats them as
separate commands. Put each command on one line.

**`ranx` return shape.** `evaluate(qrels, run, ['map'], return_mean=False)`
returns a bare numpy array, not a dict. Pass the metric as a string and handle
both shapes.

**`docker compose down` is safe.** The ES data lives in a named volume and
survives. Only `docker compose down -v` destroys the indexes.

---

## Repo layout

```
fir-lab/
  docker-compose.yml        three-service stack
  .env.example              copy to .env
  workbench/Dockerfile      Python + ES client + ranx + lightgbm

  data/                     NOT in git — download from Canvas
  runs/                     NOT in git — generated run files and plots

  notebooks/
    FIR-01-SOLVED.ipynb     course assignment 1
    02_explore.ipynb        data exploration to design decisions
    03_index_design.ipynb   analyzer validation gate + index build
    04c_tuning.ipynb        species weight grid search
    04_evaluate.ipynb       full evaluation

  scripts/
    01_index.py             build baseline index
    02_retrieve.py          baseline BM25 retrieval
    03_evaluate.py          MAP / NDCG / recall + significance
    06_query_understand.py  query classification
    07_enrich_index.py      build enriched index
    08_enrich_retrieve.py   four retrieval strategies
    09_evaluate_full.py     multi-run comparison
```

---

## Evaluation methods

Metrics: MAP, NDCG@10, P@5, P@10, recall@100, recall@1000, R-Precision.

For every comparison against the baseline:

- paired t-test (two-tailed) on per-topic AP
- Wilcoxon signed-rank (no normality assumption)
- Cohen's d for effect size
- bootstrap 95% CI, 10,000 resamples
- win / loss / tie count across topics

Both tests are reported because AP is skewed and bounded at zero. For the main
result the Wilcoxon p (0.0001) is far below the t-test p (0.0039), which says
the improvement is consistent across topics rather than large on a few.

---

## Known limitations

| Component | Overfit? | Why |
|---|---|---|
| Species boost | no | every test-set topic also names a species |
| Analyzer design | no | morphological variants are a general property |
| Fallback alias table | **yes** | hand-written for the 4 evaluated alias topics |
| Weight = 0.7 | mild | tuned and reported on the same 38 topics |

Other limitations:

- 38 training topics is thin — confidence intervals are wide
- Porter fails on `transducer`/`transduction` and `protease`/`proteolytic`,
  affecting topics 40 and 18
- LTR (Coordinate Ascent) overfits badly at this scale; reported as a learning
  exercise only, not as a result
- No dense-retrieval comparison. A PubMedBERT cross-encoder reranker would
  address semantic gaps sparse retrieval cannot bridge

---

## Reference point

MAP 0.180 (untuned) and 0.201 (tuned) against a TREC 2005 participant median
of 0.191, using sparse retrieval only.
