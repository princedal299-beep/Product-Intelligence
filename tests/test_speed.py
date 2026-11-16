import time
import unittest

from workflow.graph import safe_response


class TestSpeed(unittest.TestCase):

    def test_speed_check(self):
        latencies = []
        for _ in range(20):
            t0 = time.perf_counter()
            _ = safe_response({"retry_count": 0})
            elapsed = time.perf_counter() - t0
            latencies.append(elapsed)

        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        p95 = latencies[int(len(latencies) * 0.95)]

        self.assertGreater(p50, 0.0)
        self.assertLess(p50, 3.0, f"p50 was {p50:.3f}s, target < 3.0s")
        self.assertLess(p95, 10.0, f"p95 was {p95:.3f}s, target < 10.0s")


if __name__ == "__main__":
    unittest.main()
