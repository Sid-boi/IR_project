"""
03_evaluate.py  —  Evaluate a TREC run against qrels
                   Outputs MAP, P@10, recall@100 / @1000
                   + paired significance test vs a baseline run
Usage:
    # just evaluate one run
    python 03_evaluate.py \
        --qrels /work/data/FIR-s05-training-qrels.txt \
        --run   /work/runs/bm25_baseline.run

    # compare treatment vs baseline (adds significance test)
    python 03_evaluate.py \
        --qrels    /work/data/FIR-s05-training-qrels.txt \
        --run      /work/runs/passage_maxp.run \
        --baseline /work/runs/bm25_baseline.run
"""
import argparse
from ranx import Qrels, Run, evaluate, compare


def load_qrels(path):
    """TREC format: qid  0  doc_id  relevance"""
    data = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 4:
                continue
            qid, _, doc_id, rel = parts[0], parts[1], parts[2], int(parts[3])
            if rel > 0:                          # only relevant docs
                data.setdefault(qid, {})[doc_id] = rel
    return Qrels(data)


def load_run(path):
    """TREC format: qid  Q0  doc_id  rank  score  tag"""
    data = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 6:
                continue
            qid, doc_id, score = parts[0], parts[2], float(parts[4])
            data.setdefault(qid, {})[doc_id] = score
    return Run(data)


METRICS = ["map", "precision@10", "recall@100", "recall@1000"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qrels",    required=True)
    ap.add_argument("--run",      required=True)
    ap.add_argument("--baseline", default=None,
                    help="Baseline run for significance test")
    ap.add_argument("--stat-test", default="student",
                    choices=["student", "fisher", "permutation"],
                    help="Significance test (ranx supports all three)")
    args = ap.parse_args()

    qrels = load_qrels(args.qrels)
    run   = load_run(args.run)

    print(f"\n{'='*55}")
    print(f"Run: {args.run}")
    print(f"{'='*55}")

    results = evaluate(qrels, run, METRICS)
    for metric, val in results.items():
        print(f"  {metric:<20} {val:.4f}")

    if args.baseline:
        baseline = load_run(args.baseline)
        print(f"\n{'='*55}")
        print(f"Significance test ({args.stat_test}) vs baseline")
        print(f"{'='*55}")

        report = compare(
            qrels,
            runs=[baseline, run],
            metrics=METRICS,
            stat_test=args.stat_test,
            max_p=0.05,
        )
        print(report)
        print()
        print("Key: † = significant at p<0.05 vs baseline")


if __name__ == "__main__":
    main()
