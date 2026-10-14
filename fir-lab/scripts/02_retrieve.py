"""
02_retrieve.py  —  BM25 baseline retrieval → TREC run file

IMPORTANT: The corpus index uses sequential _id (3, 4, 5...) not PMID.
The qrels use PMID. We must extract PMID from _source for the run file.

Usage:
    python 02_retrieve.py
    python 02_retrieve.py --queries /work/data/FIR-s05-training-queries-simple.txt
                          --run /work/runs/bm25_baseline.run
"""
import os, argparse
from tqdm import tqdm
from elasticsearch import Elasticsearch

ES_URL   = os.getenv("ES_URL",   "http://elasticsearch:9200")
ES_INDEX = os.getenv("ES_INDEX", "medline")

DEFAULT_QUERIES = "/work/data/FIR-s05-training-queries-simple.txt"
DEFAULT_RUN     = "/work/runs/bm25_baseline.run"


def load_queries(path):
    queries = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split("\t", 1)
            if len(parts) == 2:
                queries[parts[0]] = parts[1].strip('"')
    return queries


def search(es, query_text, size=1000):
    """
    Multi-match BM25 retrieval.
    Returns PMID from _source — NOT _id (which is sequential position).
    The qrels use PMID so this is critical for evaluation to work.
    """
    resp = es.search(
        index=ES_INDEX,
        body={
            "query": {
                "multi_match": {
                    "query":  query_text,
                    "fields": ["TI^2", "AB", "MH"],
                    "type":   "best_fields",
                }
            },
            "_source": ["PMID"],   # fetch PMID for qrels matching
            "size": size,
        },
        params={"search_type": "dfs_query_then_fetch"},
        request_timeout=60,
    )
    # extract PMID from source, fall back to _id if missing
    hits = []
    for hit in resp["hits"]["hits"]:
        pmid  = hit.get("_source", {}).get("PMID", hit["_id"])
        score = hit["_score"]
        hits.append((pmid, score))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", default=DEFAULT_QUERIES)
    ap.add_argument("--run",     default=DEFAULT_RUN)
    ap.add_argument("--tag",     default="bm25_baseline")
    ap.add_argument("--size",    type=int, default=1000)
    args = ap.parse_args()

    es      = Elasticsearch(ES_URL)
    queries = load_queries(args.queries)
    print(f"Index:   {ES_INDEX}")
    print(f"Queries: {len(queries)}")
    print(f"Note: using PMID from _source (not ES _id) for run file")
    print()

    os.makedirs(os.path.dirname(args.run) if os.path.dirname(args.run) else '.', exist_ok=True)

    with open(args.run, "w") as f:
        for qid, qtext in tqdm(queries.items(), desc="Retrieving"):
            hits = search(es, qtext, size=args.size)
            for rank, (pmid, score) in enumerate(hits, start=1):
                f.write(f"{qid} Q0 {pmid} {rank} {score:.6f} {args.tag}\n")

    # verify first few lines
    print(f"\nRun written → {args.run}")
    with open(args.run) as f:
        for i, line in enumerate(f):
            if i >= 3: break
            print(f"  {line.strip()}")

    print(f"\nNext: python scripts/03_evaluate.py \\")
    print(f"        --qrels /work/data/FIR-s05-training-qrels.txt \\")
    print(f"        --run   {args.run}")


if __name__ == "__main__":
    main()
