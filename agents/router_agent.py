import logging
import os
import re
from typing import Literal
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from core.llm_factory import get_llm
from core.prompts import ROUTER_PROMPT
from workflow.memory import format_recent_conversation

logger = logging.getLogger("agent.router")


def extract_sku_candidate(text: str) -> str | None:
    if not text:
        return None
    raw = str(text).strip()
    cleaned = raw.strip(" ?.,!#*`\"'")
    if re.fullmatch(r"[A-Za-z0-9_-]{4,40}", cleaned):
        if any(c.isdigit() for c in cleaned) and any(c.isalpha() for c in cleaned):
            if not re.fullmatch(r"(?:10|14|18|22|24)k(?:t)?|\d+(?:\.\d+)?(?:mm|ct|cm|in|x\d+)", cleaned, re.IGNORECASE):
                return cleaned

    m = re.search(r"\b(?:product|sku|parent\s*sku)\s*[:#]?\s*([A-Za-z0-9_-]{4,40})\b", raw, re.IGNORECASE)
    if m:
        candidate = m.group(1).strip().strip("_-")
        if any(c.isdigit() for c in candidate) and any(c.isalpha() for c in candidate):
            if not re.fullmatch(r"(?:10|14|18|22|24)k(?:t)?|\d+(?:\.\d+)?(?:mm|ct|cm|in|x\d+)", candidate, re.IGNORECASE):
                return candidate

    pattern = r"\b([A-Za-z]{1,10}_[A-Za-z0-9_-]+|[A-Za-z]{2,}[0-9]+[A-Za-z0-9_-]*)\b"
    for m in re.finditer(pattern, raw):
        candidate = m.group(1).strip().strip("_-")
        if any(c.isdigit() for c in candidate) and any(c.isalpha() for c in candidate):
            if not re.fullmatch(r"(?:10|14|18|22|24)k(?:t)?|\d+(?:\.\d+)?(?:mm|ct|cm|in|x\d+)", candidate, re.IGNORECASE):
                return candidate
    return None


def resolve_active_product(query: str, active_results: list[dict]) -> dict | None:
    if not active_results or not query:
        return None
    q = query.lower().strip()

    # Match numeric position (#1, item 2, choice 3, 1st, 2nd, etc.)
    m = re.search(r"\b([1-5])(?:st|nd|rd|th)?\b", q)
    if m:
        try:
            pos = int(m.group(1))
            for item in active_results:
                if item.get("position") == pos:
                    return item
        except ValueError:
            pass

    for item in active_results:
        name = (item.get("name") or "").lower()
        if name and len(name) > 6 and name in q:
            return item

    return None


def clean_product_filters(filters: dict, raw_query: str = "") -> dict:
    cleaned = {}
    for key, val in filters.items():
        if val is None:
            continue
        if isinstance(val, str):
            val = val.strip()
            if not val:
                continue
        cleaned[key] = val

    for sort_key in ("sort_by", "sort_order"):
        if sort_key in cleaned and cleaned[sort_key]:
            cleaned[sort_key] = str(cleaned[sort_key]).strip().lower()

    return cleaned


class ProductFilters(BaseModel):
    query: str | None = Field(
        default=None,
        description="Optional design, motif, or style keyword (e.g., 'wedding', 'solitaire', 'halo', 'cathedral', 'eternity', 'vintage'). For follow-ups like 'are these in ruby', carry forward the active style.",
    )
    product_id: str | None = Field(default=None, description="Exact product ID, variant SKU, or Parent SKU if mentioned.")
    parent_sku: str | None = Field(default=None, description="Parent SKU or base model SKU if mentioned.")
    stone_type: str | None = Field(default=None, description="Gemstone name (e.g. diamond, sapphire, ruby, emerald). Correct minor spelling typos naturally.")
    metal_type: str | None = Field(default=None, description="Metal type (e.g. gold, white gold, yellow gold, rose gold, platinum, silver).")
    jewelry_type: str | None = Field(default=None, description="Jewelry category (e.g. rings, necklaces, earrings, pendants, bracelets, bands).")
    min_price: float | None = Field(default=None, description="Minimum price in USD (number only).")
    max_price: float | None = Field(default=None, description="Maximum price in USD (number only).")
    stock_status: str | None = Field(default=None, description="'in stock' or 'out of stock' if specified.")
    sort_by: str | None = Field(default=None, description="Sort field: 'price' when user asks for highest, lowest, most expensive, cheapest products.")
    sort_order: str | None = Field(default=None, description="'desc' for highest/most expensive/maximum, 'asc' for lowest/cheapest/minimum.")


class RouteDecision(BaseModel):
    route: Literal[
        "product_search",
        "product_details",
        "jewellery_help",
        "catalog_analytics",
        "unsupported",
    ] = Field(description="The chosen route based on user query.")
    metric: str | None = Field(
        default="total_count",
        description="Metric name if catalog_analytics route: total_count, count_by_jewelry_type, missing_price_by_jewelry_type, price_range_by_jewelry_type, filtered_count, all.",
    )
    filters: ProductFilters | None = None


def _heuristic_fallback_route(query: str, state: dict) -> RouteDecision:
    sku = extract_sku_candidate(query)
    if sku:
        return RouteDecision(
            route="product_details",
            filters=ProductFilters(product_id=sku, parent_sku=sku),
        )
    return RouteDecision(
        route="product_search",
        filters=ProductFilters(query=query),
    )


def load_router_prompt() -> str:
    return ROUTER_PROMPT


def route_query(state):
    router_model = os.getenv("ROUTER_LLM_MODEL", "openai/gpt-oss-20b")
    llm = get_llm(model_name=router_model, temperature=0, max_retries=2, llm_class=ChatGroq)
    classifier = llm.with_structured_output(RouteDecision)

    messages = state.get("messages", [])
    summary = state.get("conversation_summary", "")
    query = state.get("query", "")
    summary_text = (
        f"\n\nPrevious conversation summary:\n{summary}" if summary else ""
    )
    recent_chat = format_recent_conversation(messages, current_query=query, limit=4)

    logger.debug("Routing query: '%.60s' (role=%s)", query, state.get("role"))
    decision = None
    try:
        decision = classifier.invoke(
            [
                SystemMessage(content=f"{ROUTER_PROMPT}{summary_text}{recent_chat}"),
                HumanMessage(content=query),
            ]
        )
        logger.debug("Router LLM returned decision: route=%s, metric=%s", decision.route, decision.metric)
    except Exception as exc:
        logger.warning(
            "Primary Router LLM classifier failed for query '%.60s': %s. Attempting fallback model...",
            query,
            exc,
        )
        try:
            fallback_model = os.getenv("COMPOSER_LLM_MODEL", "gemini-3.5-flash-lite")
            fallback_llm = get_llm(model_name=fallback_model, temperature=0, max_retries=1)
            fallback_classifier = fallback_llm.with_structured_output(RouteDecision)
            decision = fallback_classifier.invoke(
                [
                    SystemMessage(content=f"{ROUTER_PROMPT}{summary_text}{recent_chat}"),
                    HumanMessage(content=query),
                ]
            )
            logger.info("Fallback Router LLM succeeded: route=%s", decision.route)
        except Exception as fallback_exc:
            logger.error("Fallback Router LLM failed as well: %s", fallback_exc, exc_info=True)
            decision = _heuristic_fallback_route(query, state)

    route = decision.route
    user_role = (state.get("role") or "").upper()
    if route == "catalog_analytics" and user_role not in {"MERCHANDISER", "ADMIN"}:
        route = "forbidden"

    result = {"plan": route, "metric": decision.metric or "total_count"}
    if getattr(decision, "filters", None):
        filter_dict = decision.filters.model_dump(exclude_none=True)
        if filter_dict:
            result["filters"] = clean_product_filters(filter_dict, state.get("query", ""))

    # Pure numeric price regex fallback (supports both "$600" and "600$"):
    raw_lower = (state.get("query") or "").lower()
    if route == "product_search":
        result.setdefault("filters", {})
        if not result["filters"].get("max_price"):
            m_under = re.search(r"(?:under|below|less than|up to|max)\s*\$?(\d+(?:\.\d+)?)\s*\$?", raw_lower)
            if m_under:
                try:
                    result["filters"]["max_price"] = float(m_under.group(1))
                except ValueError:
                    pass
        if not result["filters"].get("min_price"):
            m_over = re.search(r"(?:above|over|more than|at least|from|min)\s*\$?(\d+(?:\.\d+)?)\s*\$?", raw_lower)
            if m_over:
                try:
                    result["filters"]["min_price"] = float(m_over.group(1))
                except ValueError:
                    pass

    # Contextual active product resolution:
    raw_query = state.get("query", "").strip()
    active_results = state.get("active_results", [])
    ref_item = resolve_active_product(raw_query, active_results)
    if ref_item:
        pid = ref_item.get("product_id")
        if pid:
            result["plan"] = "product_details"
            result.setdefault("filters", {})
            result["filters"]["product_id"] = pid
            result["filters"]["parent_sku"] = pid

    sku_candidate = extract_sku_candidate(raw_query)
    if sku_candidate:
        result.setdefault("filters", {})
        if not result["filters"].get("product_id") and not result["filters"].get("parent_sku"):
            result["filters"]["product_id"] = sku_candidate
            result["filters"]["parent_sku"] = sku_candidate
        cleaned_q = raw_query.strip(" ?.,!#*`\"'")
        if cleaned_q.upper() == sku_candidate.upper() or route in {"product_details", "unsupported"}:
            result["plan"] = "product_details"

    if result.get("plan") == "product_details" and (
        "filters" not in result
        or (not result["filters"].get("product_id") and not result["filters"].get("parent_sku"))
    ):
        for m in reversed(messages or []):
            content = str(getattr(m, "content", ""))
            candidate = extract_sku_candidate(content)
            if candidate:
                result.setdefault("filters", {})
                result["filters"]["product_id"] = candidate
                result["filters"]["parent_sku"] = candidate
                break

    logger.info("Router final plan: %s (filters=%s)", result.get("plan"), result.get("filters"))
    return result
