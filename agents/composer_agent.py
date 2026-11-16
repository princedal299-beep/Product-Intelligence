import json
import os
from langchain_core.messages import HumanMessage, SystemMessage
from core.llm_factory import extract_text_content, get_llm
from core.prompts import get_composer_prompt
from workflow.memory import format_recent_conversation


def _format_analytics_table(title: str, rows: list[dict]) -> str:
    if not rows or not isinstance(rows, list) or not isinstance(rows[0], dict):
        return ""

    headers = [k for k in rows[0].keys() if k != "source"]
    if not headers:
        return ""

    header_labels = [h.replace("_usd", "").replace("_", " ").title() for h in headers]
    table_header = f"| {' | '.join(header_labels)} |"
    table_sep = f"| {' | '.join(':---' for _ in headers)} |"

    table_rows = []
    for r in rows:
        row_vals = []
        for h in headers:
            val = r.get(h, "")
            if isinstance(val, float):
                row_vals.append(f"${val:,.2f}")
            elif isinstance(val, int):
                row_vals.append(f"{val:,}")
            else:
                row_vals.append(str(val))
        table_rows.append(f"| {' | '.join(row_vals)} |")

    return f"### {title}\n{table_header}\n{table_sep}\n" + "\n".join(table_rows)


def _format_analytics_data(data: list | dict) -> str:
    if not data:
        return "No catalog statistics available."

    sections = []

    if isinstance(data, dict):
        if "total_count" in data:
            tc = data["total_count"]
            if isinstance(tc, list) and tc and "product_count" in tc[0]:
                sections.append(f"**Total Products in Catalog:** {tc[0]['product_count']:,}")

        title_map = {
            "count_by_jewelry_type": "Inventory Breakdown by Category",
            "price_range_by_jewelry_type": "Price Ranges by Category",
            "missing_price_by_jewelry_type": "Missing Price Records",
        }

        for metric_key, metric_rows in data.items():
            if metric_key == "total_count":
                continue
            title = title_map.get(metric_key, metric_key.replace("_", " ").title())
            if isinstance(metric_rows, list) and metric_rows:
                table_md = _format_analytics_table(title, metric_rows)
                if table_md:
                    sections.append(table_md)

        return "\n\n".join(sections) if sections else str(data)

    if isinstance(data, list) and len(data) == 1 and "product_count" in data[0] and "jewelry_type" not in data[0]:
        cnt = data[0]["product_count"]
        if len(data[0]) <= 2:
            return f"**Total Products in Catalog:** {cnt:,} (Total: {cnt})"
        table_md = _format_analytics_table("Catalog Statistics", data)
        return f"**Matching Products in Catalog:** {cnt:,} (Total: {cnt})\n\n{table_md}"

    if isinstance(data, list) and data and isinstance(data[0], dict):
        return _format_analytics_table("Catalog Statistics", data)

    return str(data)


def compose_catalog_response(
    query: str,
    role: str = "Shopper",
    documents: list | None = None,
    messages: list | None = None,
    filters: dict | None = None,
    metric: str | None = None,
    conversation_summary: str = "",
    active_results: list | None = None,
) -> str:

    docs = documents or []
    if not docs:
        return "I don't have enough relevant context to answer this question."

    context_chunks = []
    is_analytics = False
    is_filtered_count = False
    analytics_payload = None

    table_metrics = {
        "count_by_jewelry_type",
        "missing_price_by_jewelry_type",
        "price_range_by_jewelry_type",
    }

    if metric == "filtered_count":
        is_filtered_count = True

    for doc in docs:
        content = getattr(doc, "page_content", str(doc))
        if not content or content == "[]":
            continue
        context_chunks.append(content)
        try:
            parsed = json.loads(content)
        
            if isinstance(parsed, dict):
                if "filtered_count" in parsed or parsed.get("metric") == "filtered_count":
                    is_filtered_count = True
                    is_analytics = True
                    analytics_payload = parsed
                elif any(k in parsed for k in ("total_count", "count_by_jewelry_type", "price_range_by_jewelry_type", "missing_price_by_jewelry_type")):
                    is_analytics = True
                    analytics_payload = parsed
            elif isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                first_row = parsed[0]
                if first_row.get("metric") == "filtered_count" or "filtered_count" in str(content):
                    is_filtered_count = True
                    is_analytics = True
                    analytics_payload = parsed
                elif any(k in first_row for k in ("product_count", "missing_price_count", "min_price_usd")):
                    is_analytics = True
                    analytics_payload = parsed
                    if metric in table_metrics or (len(parsed) > 1 and "jewelry_type" in first_row):
                        is_filtered_count = False
                    elif filters and any(k in filters for k in ("stone_type", "metal_type", "jewelry_type", "min_price", "max_price", "query")):
                        is_filtered_count = True
        except Exception:
            pass

    if not is_filtered_count and metric not in table_metrics:
        q_lower = query.lower()
        if any(w in q_lower for w in ("how many", "count of", "number of")):
            if any(w in q_lower for w in ("ring", "rings", "necklace", "earring", "pendant", "bracelet", "band", "sapphire", "ruby", "diamond", "emerald", "gold", "silver", "platinum")):
                if analytics_payload and isinstance(analytics_payload, list) and len(analytics_payload) == 1 and "product_count" in analytics_payload[0]:
                    is_filtered_count = True

    if is_filtered_count:
        is_analytics = True

    if is_analytics and analytics_payload is not None:
        return _format_analytics_data(analytics_payload)

    if not context_chunks:
        return "I could not find any matching products in our catalog."

    deduped_chunks = []
    seen_items = set()
    for chunk in context_chunks:
        try:
            parsed = json.loads(chunk)
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict) and ("product_id" in parsed[0] or "parent_sku" in parsed[0]):
                unique_list = []
                for item in parsed:
                    key = (item.get("parent_sku") or item.get("title") or item.get("product_id") or "").strip().lower()
                    if key and key not in seen_items:
                        seen_items.add(key)
                        # Strip heavy fields to keep token payload minimal
                        clean_item = {k: v for k, v in item.items() if k not in {"attributes_json", "search_text", "_rn"}}
                        if "description" in clean_item and isinstance(clean_item["description"], str) and len(clean_item["description"]) > 250:
                            clean_item["description"] = clean_item["description"][:250] + "..."
                        unique_list.append(clean_item)
                    elif not key:
                        unique_list.append(item)
                if unique_list:
                    deduped_chunks.append(json.dumps(unique_list, ensure_ascii=False, default=str))
            elif isinstance(parsed, dict) and ("product_id" in parsed or "parent_sku" in parsed):
                key = (parsed.get("parent_sku") or parsed.get("title") or parsed.get("product_id") or "").strip().lower()
                if key and key not in seen_items:
                    seen_items.add(key)
                    clean_item = {k: v for k, v in parsed.items() if k not in {"attributes_json", "search_text", "_rn"}}
                    if "description" in clean_item and isinstance(clean_item["description"], str) and len(clean_item["description"]) > 250:
                        clean_item["description"] = clean_item["description"][:250] + "..."
                    deduped_chunks.append(json.dumps(clean_item, ensure_ascii=False, default=str))
                elif not key:
                    deduped_chunks.append(chunk)
            else:
                deduped_chunks.append(chunk)
        except Exception:
            deduped_chunks.append(chunk)

    if deduped_chunks:
        context_chunks = deduped_chunks

    context_text = "\n\n---\n\n".join(context_chunks)
    system_prompt = get_composer_prompt(role=role)

    summary_text = (
        f"\n\nOlder conversation summary:\n{conversation_summary}"
        if conversation_summary
        else ""
    )
    recent_chat = format_recent_conversation(messages, current_query=query, limit=4)

    composer_model = os.getenv("COMPOSER_LLM_MODEL", "gemini-3.5-flash-lite")
    llm = get_llm(model_name=composer_model, temperature=0)
    prompt = [
        SystemMessage(
            content=(
                f"{system_prompt}{summary_text}{recent_chat}\n\n"
                f"RETRIEVED CONTEXT DATA:\n{context_text}\n\n"
                "Use the previous conversation history above to understand any follow-up references."
            )
        ),
        HumanMessage(content=query),
    ]
    response = llm.invoke(prompt)
    return extract_text_content(response.content)


def composer_agent(state: dict) -> dict:
    generation = compose_catalog_response(
        query=state.get("query", ""),
        role=state.get("role", "Shopper"),
        documents=state.get("documents", []),
        messages=state.get("messages", []),
        filters=state.get("filters"),
        metric=state.get("metric"),
        conversation_summary=state.get("conversation_summary", ""),
        active_results=state.get("active_results", []),
    )
    return {"generation": generation}
