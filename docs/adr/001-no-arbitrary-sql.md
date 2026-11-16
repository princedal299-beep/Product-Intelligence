# ADR 001: Why There Is No "Run Any SQL" Tool

## Decision
We do **not** provide an open-ended "execute SQL" tool to the LLM. Instead, the MCP server only exposes fixed, predefined tools (like `search_products` and `get_product`).

---

## Logical Reasons

1. **Security (Prevents SQL Injection):**  
   If the LLM had a generic SQL tool, a malicious user prompt could trick it into running destructive commands (like `DROP TABLE`) or reading sensitive internal tables.

2. **Strict Role Access:**  
   Shoppers must not access store-wide analytics or inventory counts reserved for Merchandisers. Fixed tools check user permissions before running; raw SQL would allow users to bypass role restrictions.

3. **Data Protection:**  
   The catalog is read-only. Having fixed tools prevents any accidental or unauthorized data modifications.
