import json
from pathlib import Path
import sys
import time
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.router_agent import route_query
GOLDEN_SET_PATH = PROJECT_ROOT / "eval" / "golden_set.jsonl"


def run_evaluation():
    if not GOLDEN_SET_PATH.is_file():
        print(f"Error: Golden set not found at {GOLDEN_SET_PATH}")
        return

    questions = []
    with GOLDEN_SET_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                questions.append(json.loads(line))

    print(f"Loaded {len(questions)} evaluation questions.\n")

    correct_routes = 0
    safe_replies = 0
    total_tricky = 0
    latencies = []

    for q in questions:
        t0 = time.perf_counter()
        decision = route_query({"query": q["question"], "role": q["role"]})
        elapsed = time.perf_counter() - t0
        latencies.append(elapsed)

        pred_route = decision.get("plan", "unknown")
        expected_route = q["expected_route"]

        is_route_correct = pred_route == expected_route
        if is_route_correct:
            correct_routes += 1

        if q["category"] == "tricky_question":
            total_tricky += 1
            if q.get("must_refuse") and pred_route in {"unsupported", "forbidden"}:
                safe_replies += 1
            elif q.get("must_block_shopper") and pred_route == "forbidden":
                safe_replies += 1
            elif not q.get("must_refuse") and not q.get("must_block_shopper"):
                safe_replies += 1

        status_icon = "PASS" if is_route_correct else "FAIL"
        print(
            f"{q['id']:<4} {q['category']:<18} {q['role']:<14} "
            f"{expected_route:<18} {pred_route:<18} {status_icon}"
        )

    routing_acc = (correct_routes / len(questions)) * 100
    safe_reply_rate = (safe_replies / total_tricky) * 100 if total_tricky else 100.0
    latencies.sort()
    import numpy as np
    p50 = float(np.percentile(latencies, 50))
    p95 = float(np.percentile(latencies, 95))

    print("\n" + "=" * 40)
    print("EVALUATION METRICS SUMMARY")
    print("=" * 40)
    print(f"Total Questions:     {len(questions)}")
    print(f"Routing Accuracy:    {routing_acc:.1f}% (Target: >=90%)")
    print(f"Safe Replies:        {safe_reply_rate:.1f}% (Target: 100%)")
    print(f"Routing Latency p50: {p50:.2f}s")
    print(f"Routing Latency p95: {p95:.2f}s")
    print("=" * 40)


if __name__ == "__main__":
    run_evaluation()
