# ADR 002: Why Numbers and Stock Are Checked by Code

## Decision
All prices, stock availability, and counts in the assistant's answer are verified by **deterministic Python code** before being shown to the user, rather than relying solely on an LLM.

---

## Logical Reasons

1. **LLMs Are Prone to Number Hallucinations:**  
   Language models often round prices (e.g. changing `$1,299` to `$1,200`), swap digits, or misstate stock status. Python code verifies the exact values against the database with 100% precision.

2. **Instant and Free:**  
   A regex/string code check runs in under 1 millisecond and costs zero API credits. Asking an LLM to double-check numbers adds latency and token costs.

3. **Clear Debugging:**  
   When code fails a check, it logs the exact missing number or mismatch (e.g., *`$850.00 not found in product data`*), making it simple for the agent to retry and correct itself.
