import json
import unittest

from langchain_core.documents import Document

from agents.verifier_agent import verify_numeric_and_stock_facts


class TestNumberAccuracy(unittest.TestCase):

    def setUp(self):
        self.sample_docs = [
            Document(
                page_content=json.dumps([{
                    "product_id": "SR001",
                    "title": "Oval Sapphire Ring",
                    "price_usd": 750.0,
                    "stock_status": "in stock",
                }])
            )
        ]

    def test_accurate_price_and_stock_passes(self):
        valid_answer = "### 1. Oval Sapphire Ring\n- **Price:** $750.00\n- **Availability:** In Stock"
        passed, msg = verify_numeric_and_stock_facts(self.sample_docs, valid_answer)
        self.assertTrue(passed, f"Accurate price/stock must pass: {msg}")

    def test_inaccurate_price_fails(self):
        wrong_price_answer = "### 1. Oval Sapphire Ring\n- **Price:** $299.00\n- **Availability:** In Stock"
        passed, msg = verify_numeric_and_stock_facts(self.sample_docs, wrong_price_answer)
        self.assertFalse(passed, "Invented price must be caught and rejected")
        self.assertIn("cited price $299.00 does not match any product in data", msg)

    def test_inaccurate_stock_status_fails(self):
        wrong_stock_answer = "### 1. Oval Sapphire Ring\n- **Price:** $750.00\n- **Availability:** Out Of Stock"
        passed, msg = verify_numeric_and_stock_facts(self.sample_docs, wrong_stock_answer)
        self.assertFalse(passed, "Incorrect stock status must be caught and rejected")
        self.assertIn("claimed 'out of stock'", msg)


if __name__ == "__main__":
    unittest.main()
