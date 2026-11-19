import argparse
import csv
import html
import json
import logging
from pathlib import Path
import re
import sqlite3
import unicodedata
from contextlib import closing
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "catalog"
PRODUCT_ID_COLUMN = "sku"
PARENT_SKU_COLUMN = "SKU"
TITLE_COLUMN = "Product Name"
PRICE_COLUMN = "price (in USD)"
STOCK_COLUMN = "In Stock"
DESCRIPTION_COLUMN = "Description"

_ALLOWED_ATTRIBUTES = {
    "jewelry_type",
    "length",
    "width",
    "clasp_type",
    "ring_size",
    "band_width",
    "band_height",
    "fit",
    "butterfly1_type",
    "strandlength",
    "chaintypeoptions",
    "chainlengthoptions",
    "backingtypeoptions",
    "chain1_length",
    "chain1_type",
    "necklace_length",
    "metal_type",
    "metal_weight",
    "total carat weight",
}
_STONE_ATTRIBUTE = re.compile(r"stone\d+_(?:name|shape|size|cut|grade|setting|count|weight)$")
_TRUE_STOCK_VALUES = {"true", "1", "yes", "in stock", "available"}
_FALSE_STOCK_VALUES = {"false", "0", "no", "out of stock", "unavailable"}


class Product(BaseModel):
    product_id: str = Field(min_length=1)
    parent_sku: str | None = None
    title: str = Field(min_length=1)
    price_usd: float | None = Field(default=None, ge=0)
    stock_status: str
    description: str = ""
    image_path: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)

    @field_validator("product_id", "title")
    @classmethod
    def strip_required_text(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("parent_sku", "image_path")
    @classmethod
    def strip_optional_text(cls, value):
        if value is None:
            return None
        return value.strip() or None


class IngestionSummary:

    def __init__(self, rows_read=0, rows_loaded=0, rows_rejected=0, duplicates_removed=0):
        self.rows_read = rows_read
        self.rows_loaded = rows_loaded
        self.rows_rejected = rows_rejected
        self.duplicates_removed = duplicates_removed

    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)


def clean_text(value):
    if not value:
        return ""
    text = html.unescape(value)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if ch.isprintable())
    return re.sub(r"\s+", " ", text).strip()


def normalize_price_usd(value):
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    cleaned = re.sub(r"(?i)\s*USD\s*$", "", cleaned)
    cleaned = re.sub(r"(?i)^USD\s*", "", cleaned).removeprefix("$").strip()
    if not re.fullmatch(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", cleaned):
        raise ValueError(f"invalid USD price: {value!r}")
    try:
        amount = Decimal(cleaned.replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError(f"invalid USD price: {value!r}") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"invalid USD price: {value!r}")
    if amount * 100 != (amount * 100).to_integral_value():
        raise ValueError(f"price has more than two decimal places: {value!r}")
    return float(amount)


def normalize_stock(value):
    cleaned = (value or "").strip().casefold()
    if cleaned in _TRUE_STOCK_VALUES:
        return "in stock"
    if cleaned in _FALSE_STOCK_VALUES:
        return "out of stock"
    return "unknown"


def product_from_row(row):
    product_id = clean_text(row.get(PRODUCT_ID_COLUMN)) or clean_text(
        row.get(PARENT_SKU_COLUMN)
    )
    if not product_id:
        raise ValueError(
            f"missing product ID in {PRODUCT_ID_COLUMN!r} and {PARENT_SKU_COLUMN!r}"
        )

    attributes = {}
    for key, value in row.items():
        lower_key = key.casefold()
        if lower_key not in _ALLOWED_ATTRIBUTES and not _STONE_ATTRIBUTE.fullmatch(lower_key):
            continue
        cleaned = clean_text(value)
        if cleaned:
            attributes[key] = cleaned

    image_path = clean_text(row.get("Image path")) or None

    return Product(
        product_id=product_id,
        parent_sku=clean_text(row.get(PARENT_SKU_COLUMN)) or None,
        title=clean_text(row.get(TITLE_COLUMN)),
        price_usd=normalize_price_usd(row.get(PRICE_COLUMN)),
        stock_status=normalize_stock(row.get(STOCK_COLUMN)),
        description=clean_text(row.get(DESCRIPTION_COLUMN)),
        image_path=image_path,
        attributes=attributes,
    )


def product_search_text(product):
    parts = [f"Title: {product.title}"]
    if product.description:
        parts.append(f"Description: {product.description}")
    if product.attributes:
        parts.extend(
            f"{name.replace('_', ' ')}: {val}"
            for name, val in product.attributes.items()
        )
    return "\n".join(parts)[:12_000]


class ProductRepository:

    def __init__(self, database_path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS products (
                        product_id TEXT PRIMARY KEY,
                        faiss_id INTEGER NOT NULL UNIQUE,
                        parent_sku TEXT,
                        title TEXT NOT NULL,
                        price_usd REAL,
                        stock_status TEXT NOT NULL,
                        description TEXT NOT NULL,
                        image_path TEXT,
                        attributes_json TEXT NOT NULL,
                        search_text TEXT NOT NULL
                    )
                    """
                )

    def _connect(self):
        return sqlite3.connect(self.database_path)

    def iter_search_records(self, batch_size):
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "SELECT faiss_id, search_text FROM products ORDER BY faiss_id"
            )
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break
                for faiss_id, text in rows:
                    yield int(faiss_id), text

    def get_products_by_faiss_ids(self, faiss_ids):
        if not faiss_ids:
            return {}
        placeholders = ",".join("?" for _ in faiss_ids)
        with closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT faiss_id, product_id, parent_sku, title, price_usd,
                       stock_status, description, image_path, attributes_json
                FROM products WHERE faiss_id IN ({placeholders})
                """,
                faiss_ids,
            ).fetchall()
        return {
            int(row["faiss_id"]): {
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
            for row in rows
        }

    def replace_products(self, products):
        product_list = list(products)
        if not product_list:
            raise ValueError("No valid products were found; catalog was not replaced.")

        with closing(self._connect()) as conn:
            with conn:
                conn.execute("DELETE FROM products")
                insert_sql = """
                    INSERT INTO products (
                        product_id, faiss_id, parent_sku, title, price_usd,
                        stock_status, description, image_path, attributes_json, search_text
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                records = [
                    (
                        p.product_id,
                        faiss_id,
                        p.parent_sku,
                        p.title,
                        p.price_usd,
                        p.stock_status,
                        p.description,
                        p.image_path,
                        json.dumps(p.attributes, ensure_ascii=False),
                        product_search_text(p),
                    )
                    for faiss_id, p in enumerate(product_list)
                ]
                conn.executemany(insert_sql, records)
        return len(product_list)


def valid_products_from_csv(csv_path, rejects_path, summary):
    rejects_path = Path(rejects_path)
    rejects_path.parent.mkdir(parents=True, exist_ok=True)
    seen_ids = set()
    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header row: {csv_path}")
        with rejects_path.open("w", encoding="utf-8", newline="") as reject_file:
            reject_writer = csv.DictWriter(
                reject_file,
                fieldnames=[*reader.fieldnames, "rejection_reason"],
                extrasaction="ignore",
            )
            reject_writer.writeheader()
            for row in reader:
                summary.rows_read += 1
                try:
                    product = product_from_row(row)
                    if product.product_id in seen_ids:
                        summary.duplicates_removed += 1
                        raise ValueError(f"duplicate product ID: {product.product_id}")
                except (ValidationError, ValueError) as exc:
                    summary.rows_rejected += 1
                    reject_writer.writerow({**row, "rejection_reason": str(exc)})
                    continue
                seen_ids.add(product.product_id)
                summary.rows_loaded += 1
                yield product


def find_feed(csv_path=None):
    if csv_path is not None and Path(csv_path).is_file():
        return Path(csv_path)

    feeds = sorted([
        *PROJECT_ROOT.glob("Export_Merchandise_Feeds*.csv"),
        *(PROJECT_ROOT / "docs").glob("Export_Merchandise_Feeds*.csv"),
    ])
    if len(feeds) != 1:
        raise FileNotFoundError(
            "Expected exactly one Export_Merchandise_Feeds*.csv in the project "
            "or docs folder; pass --csv to select the feed."
        )
    return feeds[0]


def run_phase1_ingest(csv_path=None, output_dir=None):
    if output_dir is None:
        output_dir = DEFAULT_OUTPUT_DIR
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if csv_path is None:
        csv_path = find_feed()
    else:
        csv_path = Path(csv_path)

    database_path = output_dir / "catalog.sqlite3"
    rejects_path = output_dir / "rejects.csv"

    summary = IngestionSummary()
    repository = ProductRepository(database_path)
    #valid_product_from csv -> replace products -> loaded
    loaded = repository.replace_products(
        valid_products_from_csv(csv_path, rejects_path, summary)
    )
    if loaded == 0:
        raise ValueError("No valid products were found; catalog was not replaced.")

    return summary