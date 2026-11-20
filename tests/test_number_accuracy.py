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

    def test_price_swapping_between_products_fails(self):
        docs_with_two_products = [
            Document(
                page_content=json.dumps([
                    {"product_id": "SR001", "title": "Oval Sapphire Ring", "price_usd": 750.0},
                    {"product_id": "DR002", "title": "Diamond Eternity Band", "price_usd": 1500.0},
                ])
            )
        ]
        swapped_answer = "The Oval Sapphire Ring is priced at $1,500.00."
        passed, msg = verify_numeric_and_stock_facts(docs_with_two_products, swapped_answer)
        self.assertFalse(passed, "Cross-product price swapping must be caught")
        self.assertIn("Price mismatch for 'oval sapphire ring'", msg)

    def test_markdown_multiline_price_swapping_fails(self):
        docs = [
            Document(
                page_content=json.dumps([
                    {"product_id": "SR001", "title": "Oval Sapphire Ring", "price_usd": 750.0, "stock_status": "in stock"},
                    {"product_id": "DR002", "title": "Diamond Eternity Band", "price_usd": 1500.0, "stock_status": "out of stock"},
                ])
            )
        ]
        swapped_md = "### 1. Oval Sapphire Ring\n- **Price:** $1,500.00\n- **Availability:** In Stock\n\n### 2. Diamond Eternity Band\n- **Price:** $750.00\n- **Availability:** Out of Stock"
        passed, msg = verify_numeric_and_stock_facts(docs, swapped_md)
        self.assertFalse(passed, "Multiline markdown price swapping must be caught")
        self.assertIn("Price mismatch for 'oval sapphire ring'", msg)

    def test_markdown_multiline_stock_swapping_fails(self):
        docs = [
            Document(
                page_content=json.dumps([
                    {"product_id": "SR001", "title": "Oval Sapphire Ring", "price_usd": 750.0, "stock_status": "in stock"},
                    {"product_id": "DR002", "title": "Diamond Eternity Band", "price_usd": 1500.0, "stock_status": "out of stock"},
                ])
            )
        ]
        stock_swapped_md = "### 1. Oval Sapphire Ring\n- **Price:** $750.00\n- **Availability:** In Stock\n\n### 2. Diamond Eternity Band\n- **Price:** $1,500.00\n- **Availability:** In Stock"
        passed, msg = verify_numeric_and_stock_facts(docs, stock_swapped_md)
        self.assertFalse(passed, "Claiming out-of-stock product as in-stock must be caught")
        self.assertIn("Stock mismatch for 'diamond eternity band'", msg)

    def test_query_fake_price_fails(self):
        fake_price_answer = "Yes, we have the Oval Sapphire Ring for $10.00."
        passed, msg = verify_numeric_and_stock_facts(self.sample_docs, fake_price_answer, query="Do you have a ring for $10?")
        self.assertFalse(passed, "Fake price mentioned in query must not be approved")

    def test_accurate_catalog_count_passes(self):
        count_docs = [
            Document(page_content=json.dumps([{"product_count": 2500}]))
        ]
        answer = "We found 2,500 products matching your criteria."
        passed, msg = verify_numeric_and_stock_facts(count_docs, answer)
        self.assertTrue(passed, f"Accurate count must pass: {msg}")

    def test_inaccurate_catalog_count_fails(self):
        count_docs = [
            Document(page_content=json.dumps([{"product_count": 2500}]))
        ]
        wrong_count_answer = "We found 12,000 products matching your criteria."
        passed, msg = verify_numeric_and_stock_facts(count_docs, wrong_count_answer)
        self.assertFalse(passed, "Hallucinated count must be rejected")
        self.assertIn("Stated count '12,000' does not match catalog data", msg)


if __name__ == "__main__":
    unittest.main()
