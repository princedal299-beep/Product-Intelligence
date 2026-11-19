import json
import logging
import re
from langchain_core.documents import Document

from mcp_service.client import call_mcp_tool
from agents.router_agent import extract_sku_candidate

logger = logging.getLogger("agent.catalog")


def extract_active_results(products):
    if not products:
        return []
    items = [products] if isinstance(products, dict) else (products if isinstance(products, list) else [])
    results = []
    for p in items:
        if not isinstance(p, dict) or not p.get("title"):
            continue
        attrs = p.get("attributes") or {}
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs)
            except Exception:
                attrs = {}

        stone = p.get("stone_type") or attrs.get("stone1_name") or ""
        metal = p.get("metal_type") or attrs.get("metal_type") or ""
        results.append({
            "position": len(results) + 1,
            "product_id": p.get("parent_sku") or p.get("product_id") or "",
            "name": p.get("title") or "",
            "stone_type": stone,
            "price": p.get("price_usd") or p.get("price"),
            "metal": metal,
        })
    return results


def roll_active_results(existing_items, new_items, current_summary="", max_active=5, threshold=10):
    if not new_items:
        return existing_items or [], current_summary

    combined = (existing_items or []) + new_items
    if len(combined) > threshold:
        older = combined[:-max_active]
        active = combined[-max_active:]
        for idx, item in enumerate(active, 1):
            item["position"] = idx

        summary_parts = []
        for p in older:
            name = p.get("name") or p.get("product_id")
            price = f"${p['price']:,.2f}" if isinstance(p.get("price"), (int, float)) else str(p.get("price") or "")
            summary_parts.append(f"{name} ({price})".strip())

        addition = f"Previously viewed: {', '.join(summary_parts)}."
        new_summary = f"{current_summary}\n{addition}".strip() if current_summary else addition
        return active, new_summary

    for idx, item in enumerate(new_items, 1):
        item["position"] = idx
    return combined[-max_active:], current_summary


async def catalog_agent(state):
    plan = state.get("plan", "product_search")
    query = state.get("query", "")
    token = state.get("login_token", "")
    filters = state.get("filters", {})
    result = None

    try:
        if plan == "catalog_analytics":
            metric = state.get("metric", "all")
            if metric == "filtered_count" or filters:
                tool_args = {"metric": metric or "filtered_count"}
                for k in ("stone_type", "metal_type", "jewelry_type", "min_price", "max_price", "stock_status", "query"):
                    if filters.get(k) is not None:
                        tool_args[k] = filters[k]
                result = await call_mcp_tool(token, "catalog_stats", tool_args)
            else:
                result = await call_mcp_tool(token, "catalog_stats", {"metric": metric})

        elif plan == "product_details":
            product_id = filters.get("product_id") or filters.get("parent_sku")
            if not product_id:
                product_id = extract_sku_candidate(query)

            if not product_id:
                for m in reversed(state.get("messages", [])):
                    content = str(getattr(m, "content", ""))
                    candidate = extract_sku_candidate(content)
                    if candidate:
                        product_id = candidate
                        break

            if product_id:
                clean_id = str(product_id).strip().strip(" ?.,!#")
                result = await call_mcp_tool(token, "get_product", {"product_id": clean_id})
                if not result:
                    result = await call_mcp_tool(token, "search_products", {"product_id": clean_id, "limit": 1})
                if not result:
                    result = await call_mcp_tool(token, "search_products", {"parent_sku": clean_id, "limit": 1})
                if isinstance(result, list):
                    result = result[0] if result else None
            else:
                result = await call_mcp_tool(token, "search_products", {"query": query, "limit": 1})

        else:
            sku = filters.get("product_id") or filters.get("parent_sku")
            if not sku:
                sku = extract_sku_candidate(query)
                if sku and not filters:
                    filters["product_id"] = sku
                    filters["parent_sku"] = sku

            if sku and not any(filters.get(k) for k in ("stone_type", "metal_type", "jewelry_type", "min_price", "max_price")):
                clean_sku = str(sku).strip().strip(" ?.,!#")
                result = await call_mcp_tool(token, "get_product", {"product_id": clean_sku})
                if not result:
                    result = await call_mcp_tool(token, "search_products", {"product_id": clean_sku, "limit": 1})
                if not result:
                    result = await call_mcp_tool(token, "search_products", {"parent_sku": clean_sku, "limit": 1})
                if isinstance(result, dict):
                    result = [result]
            elif filters:
                has_structured_attributes = any(
                    filters.get(k) for k in ("stone_type", "metal_type", "jewelry_type", "sort_by", "product_id", "parent_sku")
                )
                if not has_structured_attributes and (state.get("query") or query):
                    search_q = state.get("query") or query
                    min_p = filters.get("min_price")
                    max_p = filters.get("max_price")
                    try:
                        result = await call_mcp_tool(
                            token,
                            "semantic_search",
                            {"query": search_q, "limit": 5, "min_price": min_p, "max_price": max_p},
                        )
                    except Exception:
                        result = []
                else:
                    tool_args = {
                        k: v for k, v in filters.items()
                        if v is not None and k in {
                            "stone_type", "metal_type", "jewelry_type",
                            "min_price", "max_price", "stock_status",
                            "query", "product_id", "parent_sku",
                            "sort_by", "sort_order",
                        }
                    }
                    tool_args.setdefault("limit", 5)
                    result = await call_mcp_tool(token, "search_products", tool_args)
                    if not isinstance(result, list):
                        result = [result] if result else []

                    if not filters.get("sort_by") and not result and "query" in tool_args:
                        broader_args = {k: v for k, v in tool_args.items() if k != "query"}
                        broader_args.setdefault("limit", 5)
                        if len(broader_args) > 1:
                            extra = await call_mcp_tool(token, "search_products", broader_args)
                            if extra and isinstance(extra, list):
                                seen = {p.get("title") for p in result}
                                for p in extra:
                                    if p.get("title") not in seen:
                                        result.append(p)
                                        seen.add(p.get("title"))
                                        if len(result) >= 5:
                                            break
            else:
                try:
                    result = await call_mcp_tool(token, "semantic_search", {"query": query, "limit": 5})
                except Exception:
                    result = await call_mcp_tool(token, "search_products", {"query": query, "limit": 5})

            if not result:
                search_query = state.get("query") or query
                if search_query:
                    min_p = filters.get("min_price") if filters else None
                    max_p = filters.get("max_price") if filters else None
                    try:
                        extra = await call_mcp_tool(
                            token,
                            "semantic_search",
                            {"query": search_query, "limit": 5, "min_price": min_p, "max_price": max_p},
                        )
                        if extra and isinstance(extra, list):
                            result = extra
                    except Exception:
                        pass

                    if not result:
                        try:
                            extra = await call_mcp_tool(
                                token,
                                "semantic_search",
                                {"query": search_query, "limit": 5},
                            )
                            if extra and isinstance(extra, list):
                                result = extra
                        except Exception:
                            pass
    except Exception as exc:
        logger.error(f"Catalog agent tool call failed: {exc}")
        result = []

    documents = [
        Document(
            page_content=json.dumps(result or [], ensure_ascii=False, default=str),
        )
    ]

    new_active = extract_active_results(result)
    existing_active = state.get("active_results", [])
    current_summary = state.get("conversation_summary", "")

    if new_active:
        active_results, updated_summary = roll_active_results(existing_active, new_active, current_summary)
    else:
        active_results = existing_active
        updated_summary = current_summary

    updates = {
        "documents": documents,
        "active_results": active_results,
    }
    if updated_summary != current_summary:
        updates["conversation_summary"] = updated_summary

    return updates
