from pathlib import Path
import sys
import logging
import re
logging.getLogger("faiss.loader").setLevel(logging.ERROR)
logging.getLogger("faiss").setLevel(logging.ERROR)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import json
import math
import sqlite3
from contextlib import closing
from functools import lru_cache

import jwt
from api.keys.key_loader import PUBLIC_KEY
from mcp.server.mcpserver import Context, MCPServer

mcp = MCPServer("product-intelligence")
CATALOG_DIR = PROJECT_ROOT / "data" / "catalog"
CATALOG_DATABASE = CATALOG_DIR / "catalog.sqlite3"


def _authorize(ctx, scope):
    headers = getattr(ctx, "headers", None)
    if headers is None:
        request = ctx.request_context.request
        headers = request.headers if request is not None else {}
    authorization = ""
    for k, v in headers.items():
        if k.casefold() == "authorization":
            authorization = v
            break
    scheme, _, token = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not token:
        raise PermissionError("A bearer token is required.")

    try:
        claims = jwt.decode(
            token,
            PUBLIC_KEY,
            algorithms=["RS256"],
            options={"require": ["exp", "sub", "scope"], "verify_aud": False},
        )
    except jwt.InvalidTokenError as exc:
        raise PermissionError("The bearer token is invalid or expired.") from exc

    scopes = claims["scope"]
    if isinstance(scopes, str):
        scopes = scopes.split()
    if not isinstance(scopes, list) or scope not in scopes:
        raise PermissionError(f"The token does not grant {scope}.")


def _connect(path):
    if not path.is_file():
        raise FileNotFoundError(f"Database does not exist: {path}")
    db_uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True)
    conn.execute("PRAGMA temp_store = MEMORY;")
    return conn


def _like(value):
    return value.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _product(row):
    return {
        "product_id": row["product_id"],
        "parent_sku": row["parent_sku"],
        "title": row["title"],
        "price_usd": row["price_usd"],
        "currency": "USD",
        "stock_status": row["stock_status"],
        "description": row["description"],
        "image_path": row["image_path"],
        "attributes": json.loads(row["attributes_json"]),
    }


@lru_cache(maxsize=1)
def _catalog_index():
    from ingestion.build_faiss_index import CatalogIndex
    return CatalogIndex(CATALOG_DIR)


def _build_filter_conditions(
    query=None,
    product_id=None,
    parent_sku=None,
    stone_type=None,
    metal_type=None,
    jewelry_type=None,
    min_price=None,
    max_price=None,
    stock_status=None,
):
    if any(v is not None and (not math.isfinite(v) or v < 0) for v in (min_price, max_price)):
        raise ValueError("prices must be finite and non-negative")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ValueError("min_price must not exceed max_price")

    conditions = []
    params = []

    if query and query.strip():
        conditions.append(
            """(
                lower(product_id) LIKE ? ESCAPE '\\'
                OR lower(COALESCE(parent_sku, '')) LIKE ? ESCAPE '\\'
                OR lower(title) LIKE ? ESCAPE '\\'
                OR lower(description) LIKE ? ESCAPE '\\'
                OR lower(search_text) LIKE ? ESCAPE '\\'
            )"""
        )
        params.extend([f"%{_like(query.strip())}%"] * 5)

    if product_id and product_id.strip():
        pid = product_id.strip().strip(" ?.,!#")
        if parent_sku and parent_sku.strip() and parent_sku.strip().lower() == pid.lower():
            parent_sku = None
        conditions.append("(lower(product_id) = lower(?) OR lower(COALESCE(parent_sku, '')) = lower(?))")
        params.extend([pid, pid])

    if parent_sku and parent_sku.strip():
        psku = parent_sku.strip().strip(" ?.,!#")
        conditions.append("lower(COALESCE(parent_sku, '')) = lower(?)")
        params.append(psku)

    if metal_type and metal_type.strip():
        val = _like(metal_type.strip().casefold())
        conditions.append(
            """(
                EXISTS (
                    SELECT 1 FROM json_each(products.attributes_json)
                    WHERE lower(key) = 'metal_type'
                      AND lower(CAST(value AS TEXT)) LIKE ? ESCAPE '\\'
                )
                OR lower(products.title) LIKE ? ESCAPE '\\'
                OR lower(products.search_text) LIKE ? ESCAPE '\\'
            )"""
        )
        params.extend([f"%{val}%", f"%{val}%", f"%{val}%"])

    if jewelry_type and jewelry_type.strip():
        val = jewelry_type.strip().casefold()
        val_alt = val[:-1] if val.endswith("s") else val + "s"
        conditions.append(
            """EXISTS (
                SELECT 1 FROM json_each(products.attributes_json)
                WHERE lower(key) = 'jewelry_type'
                  AND (lower(CAST(value AS TEXT)) = ? OR lower(CAST(value AS TEXT)) = ? OR lower(CAST(value AS TEXT)) LIKE ? ESCAPE '\\')
            )"""
        )
        params.extend((val, val_alt, f"%{_like(val)}%"))

    if stone_type and stone_type.strip():
        st = _like(stone_type.strip())
        conditions.append(
            """(
                EXISTS (
                    SELECT 1 FROM json_each(products.attributes_json)
                    WHERE lower(key) GLOB 'stone[0-9]*_name'
                      AND lower(CAST(value AS TEXT)) LIKE ? ESCAPE '\\'
                )
                OR lower(products.title) LIKE ? ESCAPE '\\'
                OR lower(products.search_text) LIKE ? ESCAPE '\\'
            )"""
        )
        params.extend([f"%{st}%", f"%{st}%", f"%{st}%"])

    if min_price is not None:
        conditions.append("price_usd >= ?")
        params.append(min_price)

    if max_price is not None:
        conditions.append("price_usd <= ?")
        params.append(max_price)

    if stock_status:
        conditions.append("stock_status = ?")
        params.append(stock_status)

    return conditions, params


@mcp.tool()
def search_products(
    ctx: Context,
    query=None,
    product_id=None,
    parent_sku=None,
    stone_type=None,
    metal_type=None,
    jewelry_type=None,
    min_price=None,
    max_price=None,
    stock_status=None,
    sort_by: str = None,
    sort_order: str = "asc",
    limit=20,
):
    _authorize(ctx, "catalog:read")

    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")

    sort_by_norm = (sort_by or "product_id").strip().lower()
    if sort_by_norm not in ("price", "product_id"):
        raise ValueError("sort_by must be 'price' or 'product_id'")

    sort_order_norm = (sort_order or "asc").strip().lower()
    if sort_order_norm not in ("asc", "desc"):
        raise ValueError("sort_order must be 'asc' or 'desc'")

    conditions, params = _build_filter_conditions(
        query=query,
        product_id=product_id,
        parent_sku=parent_sku,
        stone_type=stone_type,
        metal_type=metal_type,
        jewelry_type=jewelry_type,
        min_price=min_price,
        max_price=max_price,
        stock_status=stock_status,
    )

    if sort_by_norm == "price":
        conditions.append("price_usd IS NOT NULL")
        order_by = f"price_usd {'DESC' if sort_order_norm == 'desc' else 'ASC'}, product_id ASC"
        cte_order_by = order_by
    else:
        relevance_clauses = []
        if query and query.strip():
            q_esc = _like(query.strip())
            relevance_clauses.append(f"CASE WHEN lower(title) LIKE '%{q_esc}%' THEN 0 ELSE 1 END")
        if stone_type and stone_type.strip():
            st_esc = _like(stone_type.strip())
            relevance_clauses.append(f"CASE WHEN lower(title) LIKE '%{st_esc}%' THEN 0 ELSE 1 END")
            relevance_clauses.append(
                f"CASE WHEN lower(COALESCE(json_extract(attributes_json, '$.stone1_name'), '')) LIKE '%{st_esc}%' THEN 0 ELSE 1 END"
            )
        relevance_clauses.append("CASE WHEN stock_status = 'in stock' THEN 0 ELSE 1 END")
        relevance_clauses.append("CASE WHEN image_path IS NOT NULL AND image_path LIKE 'http%' THEN 0 ELSE 1 END")
        relevance_clauses.append("price_usd ASC, product_id ASC")

        order_by = ", ".join(relevance_clauses)
        cte_order_by = order_by

    if not conditions:
        conditions.append("1=1")

    sql = f"""
        WITH ranked_products AS (
            SELECT product_id, parent_sku, title, price_usd, stock_status,
                   description, image_path, attributes_json,
                   ROW_NUMBER() OVER (
                       PARTITION BY COALESCE(NULLIF(title, ''), NULLIF(parent_sku, ''), product_id)
                       ORDER BY
                           CASE WHEN image_path IS NOT NULL AND image_path != '' AND image_path LIKE 'http%' THEN 0 ELSE 1 END,
                           CASE WHEN stock_status = 'in stock' THEN 0 ELSE 1 END,
                           {cte_order_by}
                   ) AS _rn
            FROM products
            WHERE {" AND ".join(conditions)}
        )
        SELECT product_id, parent_sku, title, price_usd, stock_status,
               description, image_path, attributes_json
        FROM ranked_products
        WHERE _rn = 1
        ORDER BY {order_by}
        LIMIT ?
    """
    with closing(_connect(CATALOG_DATABASE)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, [*params, limit]).fetchall()

    return [_product(row) for row in rows]


@mcp.tool()
def get_product(ctx: Context, product_id: str):
    """Get one product by its exact SKU or Parent SKU."""
    _authorize(ctx, "catalog:read")
    clean_id = (product_id or "").strip().strip(" ?.,!#")
    if not clean_id:
        raise ValueError("product_id must not be empty")

    with closing(_connect(CATALOG_DATABASE)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT product_id, parent_sku, title, price_usd, stock_status,
                   description, image_path, attributes_json
            FROM products
            WHERE lower(product_id) = lower(?)
               OR lower(COALESCE(parent_sku, '')) = lower(?)
            ORDER BY
                CASE WHEN lower(product_id) = lower(?) THEN 0 ELSE 1 END,
                CASE WHEN image_path IS NOT NULL AND image_path != '' AND image_path LIKE 'http%' THEN 0 ELSE 1 END,
                CASE WHEN stock_status = 'in stock' THEN 0 ELSE 1 END,
                price_usd ASC, product_id ASC
            LIMIT 1
            """,
            (clean_id, clean_id, clean_id),
        ).fetchone()

    return _product(row) if row else None


@mcp.tool()
def semantic_search(
    ctx: Context,
    query: str,
    limit: int = 10,
    min_price: float = None,
    max_price: float = None,
):
    """Find similar products using the FAISS semantic vector index."""
    _authorize(ctx, "catalog:read")
    if not query.strip():
        raise ValueError("query must not be empty")
    if not 1 <= limit <= 10:
        raise ValueError("limit must be between 1 and 10")

    results = _catalog_index().search(
        query,
        limit=limit,
        min_price=min_price,
        max_price=max_price,
    )
    return [
        {**product, "source": "catalog.sqlite3"}
        for product in results
    ]


@mcp.tool()
def catalog_stats(
    ctx: Context,
    metric: str,
    stone_type=None,
    metal_type=None,
    jewelry_type=None,
    min_price=None,
    max_price=None,
    stock_status=None,
    query=None,
):
    """Return a supported catalog statistic (merchandiser/admin only)."""
    _authorize(ctx, "catalog:analytics")
    queries_by_metric = {
        "total_count": "SELECT COUNT(*) AS product_count FROM products",
        "count_by_jewelry_type": """
            SELECT COALESCE(a.value, 'Unknown') AS jewelry_type,
                   COUNT(*) AS product_count
            FROM products p
            LEFT JOIN json_each(p.attributes_json) a
                ON lower(a.key) = 'jewelry_type'
            GROUP BY jewelry_type ORDER BY jewelry_type
        """,
        "missing_price_by_jewelry_type": """
            SELECT COALESCE(a.value, 'Unknown') AS jewelry_type,
                   SUM(p.price_usd IS NULL) AS missing_price_count
            FROM products p
            LEFT JOIN json_each(p.attributes_json) a
                ON lower(a.key) = 'jewelry_type'
            GROUP BY jewelry_type ORDER BY jewelry_type
        """,
        "price_range_by_jewelry_type": """
            SELECT COALESCE(a.value, 'Unknown') AS jewelry_type,
                   MIN(p.price_usd) AS min_price_usd,
                   MAX(p.price_usd) AS max_price_usd
            FROM products p
            LEFT JOIN json_each(p.attributes_json) a
                ON lower(a.key) = 'jewelry_type'
            WHERE p.price_usd IS NOT NULL
            GROUP BY jewelry_type ORDER BY jewelry_type
        """,
    }

    if metric == "all":
        results = {}
        with closing(_connect(CATALOG_DATABASE)) as conn:
            conn.row_factory = sqlite3.Row
            for m, q in queries_by_metric.items():
                rows = conn.execute(q).fetchall()
                results[m] = [{**dict(row), "source": "catalog.sqlite3"} for row in rows]
        return results

    if metric in ("filtered_count", "total_count"):
        conditions, params = _build_filter_conditions(
            query=query,
            stone_type=stone_type,
            metal_type=metal_type,
            jewelry_type=jewelry_type,
            min_price=min_price,
            max_price=max_price,
            stock_status=stock_status,
        )
        if conditions:
            sql = f"""
                SELECT COUNT(*) AS product_count,
                       MIN(price_usd) AS min_price_usd,
                       MAX(price_usd) AS max_price_usd
                FROM products
                WHERE {" AND ".join(conditions)}
            """
        else:
            sql = "SELECT COUNT(*) AS product_count FROM products"
            params = []

        with closing(_connect(CATALOG_DATABASE)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()

        return [{**dict(row), "source": "catalog.sqlite3"} for row in rows]

    if metric not in queries_by_metric:
        raise ValueError(f"Unknown metric: {metric}")

    with closing(_connect(CATALOG_DATABASE)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(queries_by_metric[metric]).fetchall()

    return [{**dict(row), "source": "catalog.sqlite3"} for row in rows]


@mcp.resource(
    "catalog://schema",
    name="catalog-schema",
    description="Fields and analytics supported by catalog tools.",
    mime_type="application/json",
)
def catalog_schema():
    return json.dumps({
        "product_fields": [
            "product_id", "parent_sku", "title", "price_usd", "stock_status",
            "description", "image_path", "attributes",
        ],
        "analytics_metrics": [
            "total_count", "filtered_count", "count_by_jewelry_type",
            "missing_price_by_jewelry_type", "price_range_by_jewelry_type",
        ],
    })


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8001)
