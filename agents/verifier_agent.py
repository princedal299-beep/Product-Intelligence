import json
import logging
import os
import re
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from core.llm_factory import get_llm
from core.prompts import VERIFIER_JUDGE_PROMPT

logger = logging.getLogger("agent.verifier")


class VerificationResult(BaseModel):
    is_valid: bool = Field(description="Whether the answer is supported by context and answers the question.")
    feedback: str = Field(description="Short explanation of the verdict.")


def _extract_prices(text: str) -> list[float]:
    matches = re.findall(r"\$\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*\$", text)
    prices = []
    for m1, m2 in matches:
        num_str = (m1 or m2).replace(",", "")
        try:
            prices.append(float(num_str))
        except ValueError:
            pass
    return prices


def verify_numeric_and_stock_facts(
    documents,
    generation: str,
    query: str = "",
    filters: dict | None = None,
) -> tuple[bool, str]:

    if not generation:
        return False, "No Response ."
    known_prices = set()
    known_stock = set()
    product_price_map = {}
    product_stock_map = {}
    for doc in documents:
        content = doc.page_content if hasattr(doc, "page_content") else str(doc)
        try:
            items = json.loads(content)
            if isinstance(items, dict):
                items = [items]
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        for sub_val in item.values():
                            if isinstance(sub_val, list):
                                items.extend(sub_val)
                        if item.get("product_count") is not None:
                            try:
                                known_prices.add(float(item["product_count"]))
                            except (ValueError, TypeError):
                                pass
                        if item.get("missing_price_count") is not None:
                            try:
                                known_prices.add(float(item["missing_price_count"]))
                            except (ValueError, TypeError):
                                pass
                        price_val = None
                        for k, v in item.items():
                            if "price" in k and isinstance(v, (int, float)):
                                known_prices.add(float(v))
                                if k in ("price_usd", "price") or price_val is None:
                                    price_val = float(v)
                        title = (item.get("title") or item.get("name") or "").strip().lower()
                        sku = (item.get("parent_sku") or item.get("product_id") or "").strip().lower()
                        stock = str(item.get("stock_status") or "").strip().lower()
                        if price_val is not None:
                            if title and len(title) >= 5:
                                product_price_map[title] = price_val
                            if sku and len(sku) >= 4:
                                product_price_map[sku] = price_val
                        if stock:
                            known_stock.add(stock)
                            if title and len(title) >= 5:
                                product_stock_map[title] = stock
                            if sku and len(sku) >= 4:
                                product_stock_map[sku] = stock
        except Exception:
            pass

    for price in _extract_prices(generation):
        if not any(abs(price - kp) < 0.05 for kp in known_prices):
            if filters:
                min_p = filters.get("min_price")
                max_p = filters.get("max_price")
                if min_p is not None and abs(price - float(min_p)) < 0.05:
                    continue
                if max_p is not None and abs(price - float(max_p)) < 0.05:
                    continue
            return False, f"cited price ${price:.2f} does not match any product in data"

    # Cross-product price and stock mismatch check (prevent swapping)
    gen_lower = generation.lower()
    prod_positions = []
    for prod in set(product_price_map.keys()) | set(product_stock_map.keys()):
        pos = gen_lower.find(prod)
        if pos != -1:
            prod_positions.append((pos, prod))
    prod_positions.sort()

    for i, (pos, prod) in enumerate(prod_positions):
        next_pos = prod_positions[i + 1][0] if i + 1 < len(prod_positions) else len(gen_lower)
        segment = gen_lower[pos:next_pos]

        # Check price in product's section
        if prod in product_price_map:
            correct_price = product_price_map[prod]
            segment_prices = _extract_prices(segment)
            if segment_prices and not any(abs(p - correct_price) < 0.05 for p in segment_prices):
                return False, f"Price mismatch for '{prod}': expected ${correct_price:.2f}"

        # Check stock in product's section
        if prod in product_stock_map:
            correct_stock = product_stock_map[prod]
            claimed_in_stock = ("in stock" in segment) or ("available" in segment and "not available" not in segment)
            claimed_out_of_stock = "out of stock" in segment
            if correct_stock == "out of stock" and claimed_in_stock and not claimed_out_of_stock:
                return False, f"Stock mismatch for '{prod}': claimed 'in stock' but data says out of stock"
            if correct_stock == "in stock" and claimed_out_of_stock:
                return False, f"Stock mismatch for '{prod}': claimed 'out of stock' but data says in stock"

    return True, "Code check passed."


def load_judge_prompt() -> str:
    return VERIFIER_JUDGE_PROMPT


def verify_answer(state):
    query = state["query"]
    documents = state.get("documents", [])
    generation = state.get("generation", "")
    retry_count = state.get("retry_count", 0)
    filters = state.get("filters", {})

    code_passed, code_reason = verify_numeric_and_stock_facts(
        documents, generation, query=query, filters=filters
    )
    if not code_passed:
        return {
            "verification_status": "FAIL",
            "verification_feedback": code_reason,
            "retry_count": retry_count + 1,
        }

    if state.get("plan") == "catalog_analytics" or not documents:
        return {
            "verification_status": "PASS",
            "verification_feedback": code_reason,
            "retry_count": retry_count,
        }

    context = "\n\n".join(getattr(doc, "page_content", str(doc))[:2000] for doc in documents)
    try:
        verifier_model = os.getenv("VERIFIER_LLM_MODEL", "openai/gpt-oss-120b")
        llm = get_llm(model_name=verifier_model, temperature=0, max_retries=1)
        verifier = llm.with_structured_output(VerificationResult)
        result = verifier.invoke([
            SystemMessage(content=VERIFIER_JUDGE_PROMPT),
            HumanMessage(content=f"Question: {query}\n\nContext:\n{context}\n\nDraft Answer:\n{generation}"),
        ])
        verdict = {
            "verification_status": "PASS" if result.is_valid else "FAIL",
            "verification_feedback": result.feedback,
            "retry_count": retry_count if result.is_valid else retry_count + 1,
        }
        logger.info("Verifier LLM judged: status=%s, feedback=%s", verdict["verification_status"], verdict["verification_feedback"])
        return verdict
    except Exception as exc:
        logger.warning(
            "Verifier LLM check encountered an error, falling back to code check: %s",
            exc,
            exc_info=True,
        )
        return {
            "verification_status": "PASS",
            "verification_feedback": f"Code check passed ({code_reason}).",
            "retry_count": retry_count,
        }
