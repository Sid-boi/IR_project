"""
08_enrich_retrieve.py  —  Retrieval on the knowledge-enriched index

Key decisions from data exploration (Notebook 02):
  - 0% vocabulary gap → ranking problem not retrieval
  - 89% gene_descriptor → analyzer quality is primary lever
  - species in 100% queries → multiplicative species boost (Elastic blog pattern)
  - 4/38 queries have real aliases → gene_context field isolated at boost 3x
  - MeSH 100% coverage → concept_context at boost 1.5x
  - PMID ≠ ES _id → always extract PMID from _source for run files

Species boost: multiplicative function_score (not additive should clause)
  Rationale: additive boosts are unstable — +5 dominates BM25=0.08
  but is invisible on BM25=8.0. Multiplicative 1.5x is always proportional.

Four strategies (all write PMIDs to run file):
  baseline_fields  TI + AB only (control on enriched index)
  enriched_fields  + gene_context + mesh + soft species
  biz_context      + concept_context + function_score
  anti_pollution   recommended — field isolation + multiplicative species

Usage:
    python 08_enrich_retrieve.py
    python 08_enrich_retrieve.py --strategy anti_pollution
    python 08_enrich_retrieve.py --queries /work/data/FIR-s05-training-queries-simple.txt
"""
import os, json, argparse
from tqdm import tqdm
from elasticsearch import Elasticsearch

ES_URL   = os.getenv("ES_URL",   "http://elasticsearch:9200")
ES_INDEX = os.getenv("ES_INDEX", "medline_enriched")

DEFAULT_QUERIES = "/work/data/FIR-s05-training-queries-simple.txt"
DEFAULT_RUN     = "/work/runs/enriched_anti_pollution.run"
DEFAULT_QU      = "/work/data/query_classifications.json"

# Test-set ambiguous queries — alias expansion disabled for these
# All 4 are in TEST set only, not in training — but kept for completeness
AMBIGUOUS_GENE_QUERIES = {"76","77","79","80"}


def load_queries(path):
    queries = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split("\t", 1)
            if len(parts) == 2:
                queries[parts[0]] = parts[1].strip('"')
    return queries


def load_query_understanding(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def get_species(qinfo):
    if not qinfo:
        return None
    sp = qinfo.get("species", "unknown")
    return sp if sp and sp != "unknown" else None


# ── Strategy 1: baseline_fields ───────────────────────────────────────────────
def build_baseline_query(qtext, qinfo=None, size=1000, qid=None):
    """TI + AB only — control on enriched index."""
    return {
        "query": {
            "multi_match": {
                "query":  qtext,
                "fields": ["TI^2", "AB"],
                "type":   "best_fields",
            }
        },
        "size":    size,
        "_source": ["PMID"],
    }


# ── Strategy 2: enriched_fields ───────────────────────────────────────────────
def build_enriched_query(qtext, qinfo=None, size=1000, qid=None):
    """Enriched fields + soft multiplicative species boost."""
    species     = get_species(qinfo)
    prose_match = {
        "multi_match": {
            "query":  qtext,
            "fields": ["TI^2", "AB", "mesh_clean^1.5"],
            "type":   "best_fields",
        }
    }
    symbol_match = {"match": {"gene_context": {"query": qtext, "boost": 3.0}}}

    base_query = {
        "bool": {
            "should": [prose_match, symbol_match],
            "minimum_should_match": 1,
        }
    }

    functions = []
    if species:
        functions.append({"filter": {"term": {"species_norm": species}}, "weight": 0.5})

    return {
        "query": {
            "function_score": {
                "query":      base_query,
                "functions":  functions if functions else [{"weight": 1.0}],
                "score_mode": "sum",
                "boost_mode": "multiply",
            }
        },
        "size":    size,
        "_source": ["PMID"],
    }


# ── Strategy 3: biz_context ───────────────────────────────────────────────────
def build_biz_context_query(qtext, qinfo=None, size=1000, qid=None):
    """All enriched fields + concept_context + multiplicative species."""
    species = get_species(qinfo)

    base_query = {
        "bool": {
            "should": [
                {"multi_match": {"query": qtext,
                                 "fields": ["TI^2","AB","mesh_clean^1.5",
                                            "substance_names^1.0"],
                                 "type": "best_fields"}},
                {"match": {"gene_context":    {"query": qtext, "boost": 3.0}}},
                {"match": {"concept_context": {"query": qtext, "boost": 1.5}}},
            ],
            "minimum_should_match": 1,
        }
    }

    functions = []
    if species:
        functions.append({"filter": {"term": {"species_norm": species}}, "weight": 0.5})
    functions.append({
        "gauss": {"pub_year": {"origin": 2002, "scale": 3, "decay": 0.5}},
        "weight": 0.05
    })

    return {
        "query": {
            "function_score": {
                "query":      base_query,
                "functions":  functions,
                "score_mode": "sum",
                "boost_mode": "multiply",
            }
        },
        "size":    size,
        "_source": ["PMID"],
    }


# ── Strategy 4: anti_pollution (recommended) ──────────────────────────────────
def build_anti_pollution_query(qtext, qinfo=None, size=1000, qid=None):
    """
    Recommended strategy.

    Layer 1 — Ambiguous query detection
      gene_symbol_ambiguous queries (fat, numb, brahma, reaper):
      alias expansion DISABLED, species as HARD filter.
      These are all in test set — but handled defensively.

    Layer 2 — Multiplicative species boost (not additive)
      function_score with boost_mode=multiply.
      1.0 base + 0.5 species weight = 1.5x proportional uplift.
      Proportional regardless of BM25 score magnitude.
      Cross-species papers still retrievable but ranked lower.

    Layer 3 — Field isolation
      gene_context queried separately from prose (not mixed into multi_match).
      Alias hits score independently — don't pollute TI/AB IDF weighting.

    Layer 4 — Weak recency signal
      Gaussian decay on pub_year centred on 2002.
      Weight 0.05 — barely registers, just a tiebreaker.
    """
    is_ambiguous = str(qid) in AMBIGUOUS_GENE_QUERIES if qid else False
    species      = get_species(qinfo)

    # Layer 1: ambiguous queries — text only + hard species filter
    if is_ambiguous:
        return {
            "query": {
                "bool": {
                    "must":   [{"multi_match": {"query": qtext,
                                                "fields": ["TI^2","AB"],
                                                "type": "best_fields"}}],
                    "filter": ([{"term": {"species_norm": species}}]
                               if species else []),
                }
            },
            "size":    size,
            "_source": ["PMID"],
        }

    # Layers 2-4: normal queries
    base_query = {
        "bool": {
            "should": [
                # prose fields
                {"multi_match": {"query": qtext,
                                 "fields": ["TI^2","AB","mesh_clean^1.5",
                                            "substance_names^1.0"],
                                 "type": "best_fields"}},
                # gene identifiers — isolated, no prose contamination
                {"match": {"gene_context":    {"query": qtext, "boost": 3.0,
                                               "operator": "or"}}},
                # MeSH concepts — recall bridge
                {"match": {"concept_context": {"query": qtext, "boost": 1.5}}},
            ],
            "minimum_should_match": 1,
        }
    }

    # Layer 2: multiplicative species boost
    functions = []
    if species:
        functions.append({
            "filter": {"term": {"species_norm": species}},
            "weight": 0.5,  # 1.0 base + 0.5 = 1.5x multiplier
        })

    # Layer 4: very weak recency signal
    functions.append({
        "gauss":  {"pub_year": {"origin": 2002, "scale": 3, "decay": 0.5}},
        "weight": 0.05,
    })

    return {
        "query": {
            "function_score": {
                "query":      base_query,
                "functions":  functions,
                "score_mode": "sum",      # sum weights → multiplier
                "boost_mode": "multiply", # multiplier × BM25 score
            }
        },
        "size":    size,
        "_source": ["PMID"],
    }


STRATEGY_MAP = {
    "baseline_fields": build_baseline_query,
    "enriched_fields": build_enriched_query,
    "biz_context":     build_biz_context_query,
    "anti_pollution":  build_anti_pollution_query,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries",        default=DEFAULT_QUERIES)
    ap.add_argument("--qunderstanding", default=DEFAULT_QU)
    ap.add_argument("--strategy",       default="anti_pollution",
                    choices=list(STRATEGY_MAP.keys()))
    ap.add_argument("--index",          default=ES_INDEX)
    ap.add_argument("--run",            default=DEFAULT_RUN)
    ap.add_argument("--size",           type=int, default=1000)
    args = ap.parse_args()

    es          = Elasticsearch(ES_URL)
    queries     = load_queries(args.queries)
    qunderstand = load_query_understanding(args.qunderstanding)

    os.makedirs(os.path.dirname(args.run), exist_ok=True)

    print(f"Strategy:  {args.strategy}")
    print(f"Index:     {args.index}")
    print(f"Queries:   {len(queries)}")
    if qunderstand:
        types = Counter = {}
        for v in qunderstand.values():
            t = v.get('qtype', v.get('query_type', 'unknown'))
            Counter[t] = Counter.get(t, 0) + 1
        print(f"Q-types:   {Counter}")
    print()

    builder = STRATEGY_MAP[args.strategy]

    with open(args.run, "w") as out:
        for qid, qtext in tqdm(queries.items(),
                                desc=f"Retrieving ({args.strategy})"):
            qinfo = qunderstand.get(qid)
            body  = builder(qtext, qinfo=qinfo, size=args.size, qid=qid)

            resp  = es.search(index=args.index, body=body, request_timeout=60)
            hits  = resp["hits"]["hits"]

            for rank, hit in enumerate(hits, start=1):
                pmid = hit.get("_source", {}).get("PMID", hit["_id"])
                out.write(
                    f"{qid} Q0 {pmid} {rank} "
                    f"{hit['_score']:.6f} {args.strategy}\n"
                )

    # verify PMIDs in output
    print(f"\nRun written → {args.run}")
    with open(args.run) as f:
        lines = [f.readline().strip() for _ in range(3)]
    print("First 3 lines:")
    for line in lines:
        print(f"  {line}")

    print(f"\nNext:")
    print(f"  python scripts/03_evaluate.py \\")
    print(f"      --qrels    /work/data/FIR-s05-training-qrels.txt \\")
    print(f"      --run      {args.run} \\")
    print(f"      --baseline /work/runs/bm25_baseline.run")


if __name__ == "__main__":
    main()
