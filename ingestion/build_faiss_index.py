import json
import logging
from itertools import batched
from pathlib import Path

import faiss
from ingestion.ingest import (
    DEFAULT_OUTPUT_DIR,
    IngestionSummary,
    Product,
    ProductRepository,
    clean_text,
    find_feed,
    valid_products_from_csv,
    PRODUCT_ID_COLUMN,
    PARENT_SKU_COLUMN,
    TITLE_COLUMN,
    PRICE_COLUMN,
    STOCK_COLUMN,
    DESCRIPTION_COLUMN,
)

logging.getLogger("faiss.loader").setLevel(logging.ERROR)
logging.getLogger("faiss").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def build_faiss_index(repository, index_path, model_name, batch_size):
    import numpy as np
    from sentence_transformers import SentenceTransformer

    embedder = SentenceTransformer(model_name)
    index = None

    for batch in batched(repository.iter_search_records(batch_size), batch_size):
        batch = list(batch)
        vectors = embedder.encode(
            [text for _, text in batch],
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        vectors = np.ascontiguousarray(vectors, dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[0] != len(batch):
            raise ValueError("Embedding model returned an invalid vector shape.")

        if index is None:
            index = faiss.IndexIDMap2(faiss.IndexFlatIP(vectors.shape[1]))

        index.add_with_ids(
            vectors,
            np.asarray([fid for fid, _ in batch], dtype=np.int64),
        )

    if index is None:
        raise ValueError("No valid products were found; FAISS index was not built.")

    faiss.write_index(index, str(index_path))
    return int(index.ntotal), int(index.d)


def build_catalog(
    csv_path=None,
    output_dir=DEFAULT_OUTPUT_DIR,
    model_name=DEFAULT_MODEL,
    batch_size=64,
):
    if csv_path is None:
        csv_path = find_feed()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    database_path = output_dir / "catalog.sqlite3"
    index_path = output_dir / "products.faiss"
    rejects_path = output_dir / "rejects.csv"
    manifest_path = output_dir / "manifest.json"

    repository = ProductRepository(database_path)
    summary = IngestionSummary()
    loaded = repository.replace_products(
        valid_products_from_csv(csv_path, rejects_path, summary)
    )
    if loaded == 0:
        raise ValueError(
            "No valid products were found; catalog artifacts were not replaced."
        )

    indexed_count, dimension = build_faiss_index(
        repository, index_path, model_name, batch_size
    )
    if indexed_count != loaded:
        raise ValueError(f"FAISS indexed {indexed_count} products; SQLite loaded {loaded}.")

    manifest = {
        "product_count": loaded,
        "vector_dimension": dimension,
        "embedding_model": model_name,
        "similarity": "cosine",
        "product_id_column": PRODUCT_ID_COLUMN,
        "parent_id_column": PARENT_SKU_COLUMN,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return summary


class CatalogIndex:
    def __init__(self, output_dir):
        from sentence_transformers import SentenceTransformer

        self.output_dir = Path(output_dir)
        manifest_file = self.output_dir / "manifest.json"
        if manifest_file.is_file():
            self.manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        else:
            self.manifest = {
                "embedding_model": DEFAULT_MODEL,
                "vector_dimension": 384,
            }
        self.repository = ProductRepository(self.output_dir / "catalog.sqlite3")

        index_file = self.output_dir / "products.faiss"
        if not index_file.is_file():
            raise FileNotFoundError(f"FAISS index file not found: {index_file}")
        self.index = faiss.read_index(str(index_file))

        try:
            self.embedder = SentenceTransformer(self.manifest["embedding_model"], local_files_only=True)
        except Exception:
            self.embedder = SentenceTransformer(self.manifest["embedding_model"])

    def search(self, query, limit=10, min_price=None, max_price=None):
        import numpy as np

        if not query.strip():
            raise ValueError("Search query must not be empty.")
        if not 1 <= limit <= 10:
            raise ValueError("limit must be between 1 and 10.")

        vector = self.embedder.encode(
            [query],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        vector = np.ascontiguousarray(vector, dtype=np.float32)
        fetch_k = min(
            getattr(self.index, "ntotal", 2000),
            1500 if (min_price is not None or max_price is not None) else max(limit * 50, 300),
        )
        scores, ids = self.index.search(vector, fetch_k)
        faiss_ids = [int(v) for v in ids[0] if v >= 0]
        products = self.repository.get_products_by_faiss_ids(faiss_ids)

        results = []
        seen = set()
        for score, fid in zip(scores[0], ids[0]):
            if fid < 0 or int(fid) not in products:
                continue
            prod = products[int(fid)]
            price = prod.get("price_usd")
            if min_price is not None and (price is None or price < min_price):
                continue
            if max_price is not None and (price is None or price > max_price):
                continue
            title = prod.get("title") or prod.get("product_id")
            if title in seen:
                continue
            seen.add(title)
            results.append({"score": float(score), **prod})
            if len(results) >= limit:
                break
        return results
