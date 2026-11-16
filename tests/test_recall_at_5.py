import sqlite3
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG_DB = PROJECT_ROOT / "data" / "catalog" / "catalog.sqlite3"


class TestRecallAt5(unittest.TestCase):

    def test_recall_at_5(self):
        self.assertTrue(CATALOG_DB.is_file(), f"Catalog database not found at {CATALOG_DB}")

        test_queries = [
            ("sapphire", "Rings"),
            ("emerald", "Rings"),
            ("ruby", "Rings"),
            ("diamond", "Rings"),
            ("gold", "Rings"),
        ]

        hits = 0
        conn = sqlite3.connect(f"{CATALOG_DB.resolve().as_uri()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            for stone_or_metal, j_type in test_queries:
                cursor = conn.execute(
                    """
                    SELECT title, attributes_json FROM products
                    WHERE lower(search_text) LIKE ? AND lower(attributes_json) LIKE ?
                    LIMIT 5
                    """,
                    (f"%{stone_or_metal}%", f"%{j_type.lower()}%"),
                )
                top_5 = cursor.fetchall()
                if any(
                    stone_or_metal in r["title"].lower()
                    or stone_or_metal in r["attributes_json"].lower()
                    for r in top_5
                ):
                    hits += 1
        finally:
            conn.close()

        recall_at_5 = hits / len(test_queries)
        self.assertGreaterEqual(recall_at_5, 0.80, f"Recall@5 was {recall_at_5:.2f}, target >= 0.80")


if __name__ == "__main__":
    unittest.main()
