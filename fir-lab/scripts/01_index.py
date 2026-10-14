"""
01_index.py  —  Build baseline BM25 index on TREC Genomics corpus

Usage:
    python 01_index.py
    python 01_index.py --data /work/data/FIR-s05-medline.json
    python 01_index.py --recreate   # wipe and rebuild
"""
import os, json, argparse, time
from elasticsearch import Elasticsearch
from elasticsearch.helpers import streaming_bulk

ES_URL   = os.getenv("ES_URL",   "http://elasticsearch:9200")
ES_INDEX = os.getenv("ES_INDEX", "medline")

# ── Mapping ───────────────────────────────────────────────────────────────────
# Plain BM25 baseline — this is your control.
# english analyzer: lowercases, removes stopwords, Porter stems.
# single shard: IDF computed globally → reproducible scores.
# MH (MeSH headings) indexed for later comparison with enriched index.
MAPPING = {
    "settings": {
        "number_of_shards":   1,
        "number_of_replicas": 0,
        "similarity": {
            "default": {
                "type": "BM25",
                "k1":   1.2,
                "b":    0.75
            }
        }
    },
    "mappings": {
        "properties": {
            "TI":   {"type": "text",    "analyzer": "english"},
            "AB":   {"type": "text",    "analyzer": "english"},
            "MH":   {"type": "text",    "analyzer": "english"},
            "RN":   {"type": "text",    "analyzer": "english"},
            "PMID": {"type": "keyword"},
            "TA":   {"type": "keyword"},
            "DP":   {"type": "keyword"},
        }
    }
}


def parse_bulk_ndjson(path):
    """Alternating meta/doc lines → (doc_id, doc) pairs."""
    with open(path, "r", encoding="utf-8") as f:
        while True:
            meta_line = f.readline()
            doc_line  = f.readline()
            if not meta_line or not doc_line:
                break
            meta   = json.loads(meta_line)
            doc    = json.loads(doc_line)
            doc_id = meta["index"]["_id"]
            yield doc_id, doc


def action_iter(path, index):
    for doc_id, doc in parse_bulk_ndjson(path):
        yield {"_index": index, "_id": doc_id, "_source": doc}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--data",
        default="/work/data/FIR-s05-medline.json",  # fixed path
        help="Path to FIR-s05-medline.json"
    )
    ap.add_argument(
        "--recreate",
        action="store_true",
        help="Delete and recreate index if it already exists"
    )
    args = ap.parse_args()

    es = Elasticsearch(ES_URL)

    # wait for ES to be healthy
    print("Waiting for Elasticsearch...")
    for _ in range(30):
        try:
            es.cluster.health(wait_for_status="yellow", timeout="5s")
            print("ES is ready")
            break
        except Exception:
            time.sleep(3)

    # handle recreate
    if args.recreate and es.indices.exists(index=ES_INDEX):
        es.indices.delete(index=ES_INDEX)
        print(f"Deleted existing index '{ES_INDEX}'")

    # create index
    if not es.indices.exists(index=ES_INDEX):
        es.indices.create(index=ES_INDEX, body=MAPPING)
        print(f"Created index '{ES_INDEX}'  (BM25 k1=1.2 b=0.75, english analyzer)")
    else:
        print(f"Index '{ES_INDEX}' already exists")
        print("  Use --recreate to wipe and rebuild")
        count = es.count(index=ES_INDEX)["count"]
        print(f"  Current count: {count:,}")
        return

    # bulk index
    print(f"\nIndexing {args.data} ...")
    print("(~5 min for 263k docs)\n")

    ok = errors = 0
    start = time.time()

    for success, info in streaming_bulk(
        es,
        action_iter(args.data, ES_INDEX),
        chunk_size=500,
        raise_on_error=False,
    ):
        if success:
            ok += 1
            if ok % 50000 == 0:
                elapsed = time.time() - start
                print(f"  {ok:>8,} docs  |  {ok/elapsed:.0f} docs/s")
        else:
            errors += 1
            if errors <= 5:
                print(f"  Error: {info}")

    elapsed = time.time() - start
    count   = es.count(index=ES_INDEX)["count"]

    print(f"\nDone in {elapsed/60:.1f} min")
    print(f"  Indexed:     {ok:,}")
    print(f"  Errors:      {errors:,}")
    print(f"  Index count: {count:,}")
    print(f"\nNext step:")
    print(f"  python scripts/02_retrieve.py")


if __name__ == "__main__":
    main()
