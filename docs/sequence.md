# Product Intelligence Assistant — Sequence Flows

This document details the end-to-end execution flows of the Product Intelligence Assistant, including one-command system bootstrap (`run_app.bat`), user registration, authentication, chat interaction with thread-scoped memory, multi-agent orchestration, hybrid search routing, dual-gate security verification, and administrative role management.

---

## 1. System Bootstrap & One-Command Startup Flow (`run_app.bat`)

All three microservices are initialized in parallel with staggered delays via `.\run_app.bat` (or `./run_app.sh` on macOS/Linux):

```mermaid
sequenceDiagram
    autonumber
    actor Operator as Developer / Evaluator
    participant Script as Launcher (run_app.bat / run_app.sh)
    participant FastAPI as FastAPI Gateway (:8000)
    participant MCP as Catalog MCP Server (:8001)
    participant UI as Streamlit UI (:8501)
    participant Browser as Web Browser

    Operator->>Script: Execute .\run_app.bat
    Script->>Script: cd /d "%~dp0" (Anchor to project root directory)
    Script->>Script: Check & activate venv / .venv if present
    Script->>FastAPI: Spawn Terminal 1: uvicorn api.app:app --host 127.0.0.1 --port 8000 --reload
    Script->>Script: Stagger delay (2s) for socket binding
    Script->>MCP: Spawn Terminal 2: python mcp_service/tools.py (:8001)
    Script->>Script: Stagger delay (2s) for tool registration
    Script->>UI: Spawn Terminal 3: streamlit run main.py (:8501)
    UI->>Browser: Automatically launch http://localhost:8501
    Browser-->>Operator: Chatbot Ready for Authentication & Queries
```

---

## 2. User Registration and Sign-In Flow

All users authenticate through the unified FastAPI endpoints (`POST /login` or `/Login`) from the Streamlit UI. User credentials and roles are persisted in `data/users.sqlite3` with Argon2 password hashing. Roles are strictly managed through database records rather than inferred from email domains.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as Streamlit UI (main.py)
    participant API as FastAPI (api/routers/auth.py)
    participant Sec as Security (passwords.py & tokens.py)
    participant DB as User Database (users.sqlite3)

    alt New User Registration
        User->>UI: Enter email and password
        UI->>API: POST /register {email, password}
        API->>DB: Check if email already registered
        alt Email exists
            DB-->>API: Conflict detected
            API-->>UI: 409 Conflict ("Account already exists")
        else New Email
            API->>Sec: Hash password (Argon2)
            API->>DB: INSERT user with default role = 'Shopper'
            DB-->>API: Created user record
            API-->>UI: 201 Created {id, email, role: 'Shopper'}
            UI-->>User: Show registration success
        end
    end

    alt User Sign-In
        User->>UI: Submit email and password
        UI->>API: POST /login or /Login (username, password)
        API->>Sec: Check credentials

        alt Email matches configured ADMIN_EMAIL
            Sec->>Sec: Compare submitted password against ADMIN_PASSWORD from .env
            alt Admin password valid
                Sec-->>API: Admin authenticated (role = 'ADMIN')
            else Admin password invalid
                Sec-->>API: 401 Unauthorized
            end
        else Standard User (Shopper / Merchandiser)
            Sec->>DB: Query user record by email
            alt User found and Argon2 password hash matches
                DB-->>Sec: User record with stored role ('Shopper' or 'Merchandiser')
                Sec-->>API: Authenticated user
            else Invalid email or password
                Sec-->>API: 401 Unauthorized ("Invalid credentials")
            end
        end

        alt Authentication Successful
            API->>Sec: Generate RS256 signed user access token (contains user_id and role)
            API-->>UI: 200 {access_token, token_type: "bearer", user_id, role}
            UI->>UI: Store access_token in Streamlit session state
            UI-->>User: Open chatbot interface with role-adapted view
        else Authentication Failed
            API-->>UI: 401 Unauthorized
            UI-->>User: Display sign-in error
        end
    end
```

---

## 3. Chat Request, Context Memory & Multi-Agent Orchestration Flow

Every chat query undergoes dual-gate authorization: first at the API middleware & router level, and second at the MCP tool execution level. Conversational context is retrieved from `InMemorySaver` by `thread_id`. 
* **Zero-Hardcoding Router:** The Router Agent parses structured `ProductFilters` via the LLM, resolving typos (e.g. `diamod` $\rightarrow$ `diamond`) and contextual references (e.g. carrying forward previous jewelry types for pronoun follow-ups) without static word dictionaries.
* **Hybrid Search Strategy:** Vague or conceptual queries trigger pure FAISS Cosine Similarity (`semantic_search`). Structured attribute queries execute relevance-ranked SQL (`search_products`) prioritizing primary center stones. If SQL finds 0 items, it automatically falls back to Cosine Similarity.
* **Deterministic Catalog Presentation:** The Composer Agent formats verified Markdown tables directly in code for analytics queries, and constructs clean, deduplicated product context rendered with role-aware styling (Shopper vs. Staff/Merchandiser).
* **Deterministic Code Verification:** The Verifier Agent verifies all prices and stock availability in code against database records before delivering responses to users.
* **Adaptive Summarization:** If message count reaches 6, older dialogue is condensed into a summary while the latest 4 messages are retained as clean text. When the summary exceeds ~300 words, it is recursively condensed.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as Streamlit UI (main.py)
    participant MW as Middleware (api/middleware.py)
    participant API as FastAPI Router (api/routers/chat.py)
    participant Mem as Memory (InMemorySaver checkpointer)
    participant Audit as Audit DB (data/audit.sqlite3)
    participant Logs as Log File (logs/api.log)
    participant Router as Router Agent (agents/router_agent.py)
    participant Graph as LangGraph Workflow (workflow/graph.py)
    participant MCP as Catalog MCP Server (mcp_service/tools.py)
    participant DB as SQLite DB (catalog.sqlite3)
    participant FAISS as FAISS Index (Cosine Sim)
    participant Verifier as Verifier Agent (agents/verifier_agent.py)

    User->>UI: Ask: "Show me oval sapphire rings under $800"
    UI->>MW: POST /chat + Bearer Token {query, thread_id}

    MW->>MW: Assign X-Request-ID (req_id) & check 20 req/min rate limit
    alt Rate limit exceeded
        MW-->>UI: 429 Too Many Requests (Retry-After: 60)
    else Rate limit OK
        MW->>API: Forward request to chat_endpoint
        API->>API: Validate user token and extract role via get_current_user
        API->>Mem: Load existing messages & summary for thread_id
        Mem-->>API: {messages, conversation_summary}

        API->>Router: route_query(query, role, messages, conversation_summary)
        Note over Router: LLM Structured Output (Pydantic ProductFilters)<br/>Zero Hardcoded Word Lists
        Router-->>API: RouteDecision {plan: "product_search", filters: {...}}

        alt Shopper requested catalog analytics
            API->>Audit: record_audit(req_id, user_id, role, query, route="forbidden")
            API->>Logs: Log forbidden access attempt with req_id
            API-->>UI: 403 Forbidden ("Analytics available to merchandisers only")
        else Allowed Route
            API->>API: Mint short-lived RS256 token scoped to role (catalog:read)
            Note over API,MCP: User's login token is NEVER forwarded to the MCP server.

            API->>Graph: run_workflow(query, role, login_token=mcp_token, thread_id)
            Graph->>Graph: initialize_turn: record HumanMessage, load checkpointer

            alt Product Search Route (Hybrid Search)
                alt Query Has Structured Attributes (Gemstone, Metal, Type)
                    Graph->>MCP: Call search_products(stone_type, metal_type, min_price, max_price)
                    MCP->>DB: Execute SQL with Multi-Tier Relevance Ranking (Center Stone First)
                    DB-->>MCP: Matching product rows
                    alt 0 Matches in SQL
                        MCP->>FAISS: Fallback to semantic_search (Cosine Similarity)
                        FAISS-->>MCP: Closest semantic candidate products
                    end
                else Conceptual / Gift / Vague Query
                    Graph->>MCP: Call semantic_search(query, min_price, max_price)
                    MCP->>FAISS: Execute Cosine Similarity Search (L2-Normalized)
                    FAISS-->>MCP: Semantically matching products
                end
                MCP-->>Graph: Structured product documents with image URLs
                
                Graph->>Graph: Node: composer_agent
                Note over Graph: Code formats Markdown analytics tables / deduplicates product items.<br/>LLM writes role-tailored product cards & overview.
            else Jewellery Help Route
                Graph->>Graph: Search curated knowledge base (jewellery_care / sizing)
            else Unsupported / Prompt Injection Route
                Graph->>Graph: Select safe_response ("I can't help with that request.")
            end

            opt Verification Step (Catalog Responses)
                Graph->>Verifier: verify_answer(documents, draft_answer)
                Verifier->>Verifier: Deterministic code check: compare all prices & stock
                alt Prices or stock status contradict data
                    Verifier-->>Graph: Verification FAIL (feedback: "Price does not match data")
                    loop Retry failed verification (MAX_RETRIES = 2)
                        Graph->>Router: Re-route with error feedback
                        Graph->>Graph: Regenerate draft with corrected constraints
                        Graph->>Verifier: Re-verify revised draft
                    end
                    Note over Graph: If verification fails after 2 retries, fallback to:<br/>"Sorry, I could not confirm this answer."
                else Code check passes
                    Verifier->>Verifier: LLM-as-Judge evaluates semantic groundedness
                    Verifier-->>Graph: Verification PASS
                end
            end

            opt Adaptive History Summarization (Message Count >= 6)
                Graph->>Graph: summarize_history_node: LLM condenses older turns
                Graph->>Graph: Remove older messages with RemoveMessage and keep last 4 clean turns
                Note over Graph: If running summary exceeds ~300 words, recursively re-summarize.
            end

            Graph->>Mem: Persist updated state to InMemorySaver checkpointer
            Graph-->>API: Final verified response and sources
            API->>Audit: record_audit(req_id, user_id, role, query, route, agent)
            API->>Logs: Write access entry (req_id, status=200, duration_ms)
            API-->>UI: 200 OK {answer, sources, trace_id, request_id}
            UI-->>User: Display formatted answer, images, and citations
        end
    end
```

---

## 4. Administrative Role Promotion Flow

Roles are strictly elevated by authenticated administrators through the Admin Dashboard:

```mermaid
sequenceDiagram
    autonumber
    actor Admin
    participant UI as Streamlit UI (Admin Controls)
    participant API as FastAPI (api/routers/admin.py)
    participant Auth as Auth Validation (api/dependencies.py)
    participant DB as User Database (users.sqlite3)
    actor Shopper as Promoted User

    Admin->>UI: Search user by email ("person@example.com")
    UI->>API: GET /admin/users?email=person@example.com (Admin Token)
    API->>Auth: Validate Admin role via get_admin
    API->>DB: Find user account in user_repository
    DB-->>API: User record {id: 42, role: "Shopper"}
    API-->>UI: 200 {id: 42, email: "person@example.com", role: "Shopper"}

    Admin->>UI: Select new role: "Merchandiser" & click Update
    UI->>API: PATCH /admin/users/42/role {role: "Merchandiser"}
    API->>Auth: Verify Admin role
    API->>DB: set_user_role(42, 'Merchandiser')
    DB-->>API: Success
    API-->>UI: 200 {id: 42, role: "Merchandiser"}
    UI-->>Admin: Show promotion confirmed

    Note over Shopper,API: On next sign-in, the user's new token reflects the Merchandiser role.
    Shopper->>UI: Sign in with credentials
    UI->>API: POST /login
    API->>DB: Query stored role
    DB-->>API: Returns role = 'Merchandiser'
    API-->>UI: 200 {access_token with Merchandiser permissions}
    Note over Shopper: User can now query catalog statistics and analytics.
```

---

## 5. API Endpoints and Status Code Matrix

| Endpoint | Method | Allowed Roles | Description | Expected Status Codes |
|---|---|---|---|---|
| `/register` | `POST` | Public | Register new user account (defaults to `Shopper`) | `201 Created`, `409 Conflict`, `422 Invalid Input` |
| `/login` / `/Login` | `POST` | Public | Authenticate credentials and receive user access token | `200 OK`, `401 Unauthorized` |
| `/chat` | `POST` | `Shopper`, `Merchandiser`, `ADMIN` | Send user inquiry, execute multi-agent workflow | `200 OK`, `401 Unauthorized`, `403 Forbidden`, `429 Rate Limit`, `503 Unavailable` |
| `/chat/stream` | `POST` | `Shopper`, `Merchandiser`, `ADMIN` | Send inquiry and receive word-by-word streaming response | `200 OK`, `401 Unauthorized`, `403 Forbidden`, `429 Rate Limit` |
| `/me` | `GET` | Authenticated Users | Retrieve profile details of currently authenticated user | `200 OK`, `401 Unauthorized`, `404 Not Found` |
| `/mcp-token` | `POST` | Authenticated Users | Mint short-lived (60s) role-scoped token for MCP tools | `200 OK`, `401 Unauthorized` |
| `/admin/users` | `GET` | `ADMIN` only | Search user profile by email | `200 OK`, `401 Unauthorized`, `403 Forbidden`, `404 Not Found` |
| `/admin/users/{id}/role` | `PATCH` | `ADMIN` only | Promote user role (`Shopper` $\leftrightarrow$ `Merchandiser`) | `200 OK`, `401 Unauthorized`, `403 Forbidden`, `422 Invalid Role` |
| `/admin/audit` | `GET` | `ADMIN` only | Retrieve historical query and route audit records | `200 OK`, `401 Unauthorized`, `403 Forbidden` |
| `/admin/reindex` | `POST` | `ADMIN` only | Trigger raw feed re-ingestion and rebuild FAISS index | `200 OK`, `401 Unauthorized`, `403 Forbidden`, `500 Server Error` |

---

## 6. Security and Quality Assurance Guarantees

1. **Dual Token Isolation:** The user's login access token is never shared with downstream tools. The API mints a short-lived, single-purpose RS256 token scoped strictly to tool-level permissions (`catalog:read` or `catalog:analytics`).
2. **Hybrid Search Routing:** Automatically dispatches between Relevance-Ranked SQL (for concrete attribute matching with primary center stone prioritization) and Cosine Similarity FAISS vector search (for open-ended thematic queries and zero-result fallbacks).
3. **Conversational Context & Dynamic Summarization:** Conversation turns are retained in thread-scoped checkpointers. When a thread reaches 6 messages, older turns are compressed into a running summary while the latest 4 turns are retained as clean text dialogue. If the summary exceeds ~300 words, it is recursively condensed.
4. **Deterministic Number Accuracy & Code Table Extraction:** The agent cannot output an unverified numeric price, stock state, or aggregate count. Product catalog Markdown tables are deterministically rendered by Python code directly from retrieved context, and all prices and stock statuses are verified against database records.
5. **Zero Hardcoded Word Lists:** The Router Agent uses LLM-driven structured output parsing without brittle hardcoded word lists, stop words, or typo dictionaries.
6. **Bounded Retries:** If verification fails, the query is retried at most twice (`MAX_RETRIES = 2`). If verification cannot pass, the system gracefully outputs `"Sorry, I could not confirm this answer."`
7. **Persistent File Logging:** Every inbound request is logged with `req_id` to [`logs/api.log`] and console. No tokens, passwords, or full raw prompts are ever written to logs.
8. **Comprehensive Automated Test Suite:** Verified via tests in [`tests/`] covering conversational context, trajectory, API security, recall@5, number accuracy, groundedness, safe replies, and speed.
