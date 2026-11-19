# Product Intelligence Assistant

An enterprise-grade, conversational product discovery and intelligence platform built for luxury fine jewelry. The system combines a **FastAPI** gateway, a **Model Context Protocol (MCP)** tool server, a **LangGraph** multi-agent orchestration pipeline, **FAISS** vector search, and a **Streamlit** front-end. It features dual-gate security, role-based access control (RBAC), thread-scoped conversational memory with adaptive summarization, and deterministic code-based verification guaranteeing **zero price or inventory hallucinations**.

> ⚡ **One-Command Quick Start (Windows):** Launch the entire platform in a single command using `.\run_app.bat`!
>
> ```powershell
> .\run_app.bat
> ```
> *(Or in Command Prompt: `run_app.bat`)
>
> This checks the project Python environment and application imports before starting the **FastAPI Gateway (Port 8000)**, **MCP Tool Server (Port 8001)**, and **Streamlit Web UI (Port 8501)** in separate terminal windows. See [Section 2: Running the Application](#2-running-the-application) for prerequisites and details.

---

## Table of Contents
- [Architecture Overview](#architecture-overview)
- [Key Technical Guarantees](#key-technical-guarantees)
- [Role-Based Access Control (RBAC) Matrix](#role-based-access-control-rbac-matrix)
- [1. Installation & Environment Setup](#1-installation--environment-setup)
- [2. Running the Application](#2-running-the-application)
  - [Option A: One-Command Startup (`run_app.bat`)](#option-a-one-command-startup-recommended-for-windows-run_appbat)
  - [Option B: Manual Startup (3 Terminals)](#option-b-manual-startup-macos--linux--multi-terminal-debugging)
- [3. Usage & Persona Walkthrough](#3-usage--persona-walkthrough)
- [4. API Reference](#4-api-reference)
- [5. Automated Tests & Evaluation](#5-automated-tests--evaluation)
- [6. Repository Layout](#6-repository-layout)
- [7. Architectural Decisions & Key Documents](#7-architectural-decisions-adrs)

---

## Architecture Overview

```
                      +-----------------------------+
                      |   Streamlit UI (Port 8501)  |
                      |          main.py            |
                      +--------------+--------------+
                                     | HTTP / Bearer JWT
                                     v
+------------------------------------+---------------------------------------+
|                         FastAPI Backend (Port 8000)                        |
|                                                                            |
|  [Middleware] Rate Limiter (20 req/min) | Request-ID Tracing | Persistent Logging |
|  [Auth API]   Argon2 Password Hashing   | RS256 JWT Minting  | SQLite User Store  |
|  [Admin API]  Role Management (RBAC)    | Audit Trail Logger | Catalog Reindex    |
+------------------------------------+---------------------------------------+
                                     | Short-Lived Scoped Token (RS256)
                                     v
+------------------------------------+---------------------------------------+
|                    LangGraph Agent Workflow (workflow/)                    |
|                                                                            |
|  1. initialize_turn   --> Record query & sync thread memory                |
|  2. router_agent      --> LLM structured filters (Zero Hardcoded Keywords) |
|  3. catalog_agent     --> Hybrid Search (Relevance SQL + Cosine FAISS)     |
|  4. composer_agent    --> Code-formatted analytics & role-aware cards      |
|  5. verifier_agent    --> Deterministic code check (prices/stock) + Judge  |
|  6. finish_turn       --> Append response & clear transient credentials    |
|  7. summarize_history --> Adaptive compression when messages >= 6          |
+------------------------------------+---------------------------------------+
                                     | Streamable HTTP Client
                                     v
+------------------------------------+---------------------------------------+
|                      MCP Tool Server (Port 8001)                           |
|                                                                            |
|  * Scope Check: catalog:read | catalog:analytics                           |
|  * search_products: Multi-tier relevance SQL (center stone prioritization) |
|  * semantic_search: FAISS IndexFlatIP (Cosine similarity + price filter)   |
|  * get_product: Exact SKU / Parent SKU resolution                          |
|  * catalog_stats: Aggregations, inventory breakdowns, price ranges        |
+------------------------------------+---------------------------------------+
                                     |
               +---------------------+---------------------+
               |                                           |
               v                                           v
    SQLite Catalog Database                      FAISS Vector Index
    (data/catalog/catalog.sqlite3)               (data/catalog/products.faiss)
```

---

## Key Technical Guarantees

| Capability | Implementation | Benefit |
|---|---|---|
| **Zero Numeric Hallucination** | Deterministic Python regex & SQLite price/stock check in [`agents/verifier_agent.py`](agents/verifier_agent.py). | Prevents incorrect prices or availability claims from ever reaching the customer. |
| **Dual-Gate Security** | Gate 1: FastAPI JWT auth & 20 req/min rate limit. Gate 2: Short-lived (60s) RS256 token verified by MCP server. | Downstream tools are isolated; compromised API sessions cannot bypass tool permissions. |
| **Zero Hardcoded Keywords** | LLM-driven structured output extraction ([`ProductFilters`](agents/router_agent.py)) via Groq / Gemini. | Handles spelling typos (`diamod` $\rightarrow$ `diamond`) and multi-turn pronoun follow-ups naturally. |
| **Hybrid Search Strategy** | Relevance-ranked SQL (center stone $\rightarrow$ title $\rightarrow$ stock) with automatic fallback to FAISS Cosine Similarity. | Balances precise attribute filtering with open-ended conceptual exploration. |
| **Adaptive Summarization** | Thread-scoped `InMemorySaver` checkpointer with sliding window (retains last 4 turns, compresses older turns at $\ge 6$ messages). | Prevents context window explosion while preserving user style and budget preferences. |
| **100% Provenance & Audit** | Persistent log file ([`logs/api.log`](logs/api.log)) and query audit database ([`data/audit.sqlite3`](data/audit.sqlite3)). | Full traceability of every user request, assigned role, route taken, and latency. |

---

## Role-Based Access Control (RBAC) Matrix

| Feature / Action | Shopper (Customer) | Merchandiser (Staff) | Administrator |
|---|:---:|:---:|:---:|
| Search Products & Filter by Attributes | Yes | Yes | Yes |
| View Luxury Product Cards & Images | Yes | Yes | Yes |
| Jewelry Care & Sizing Knowledge Base | Yes | Yes | Yes |
| Internal Parent SKUs & Manufacturing Data | Hidden | Yes | Yes |
| Catalog Analytics (Totals, Counts by Type) | 403 Forbidden | Yes | Yes |
| Price Ranges & Missing Price Audits | 403 Forbidden | Yes | Yes |
| Search Users & Promote Roles | No | No | Yes |
| Audit Trail Inspection (`/admin/audit`) | No | No | Yes |
| Catalog Feed Reload (`/admin/reindex`) | No | No | Yes |

---

## 1. Installation & Environment Setup

### 1.1 Prerequisites
* Python 3.10, 3.11, 3.12, or 3.14
* Git

### 1.2 Install Dependencies
```bash
pip install -r requirements.txt
```

### 1.3 Configure Environment Variables
Create a `.env` file in the project root (or copy `.env.example`):
```ini
# LLM Provider API Keys
GROQ_API_KEY=gsk_your_groq_api_key_here
GEMINI_API_KEY=AIzaSy_your_gemini_api_key_here

# Administrator Credentials (Pre-seeded admin account)
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=your_admin_secure_password

# Service Endpoints
API_BASE_URL=http://localhost:8000
MCP_URL=http://localhost:8001/mcp

# Agent Model Overrides (Optional - defaults shown)
ROUTER_LLM_MODEL=openai/gpt-oss-20b
COMPOSER_LLM_MODEL=gemini-3.5-flash-lite
KNOWLEDGE_LLM_MODEL=gemini-3.5-flash-lite
SUMMARIZER_LLM_MODEL=gemini-3.5-flash-lite
VERIFIER_LLM_MODEL=openai/gpt-oss-20b

# Observability (Optional)
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=product-intelligence
```

### 1.4 Ingest Catalog & Build FAISS Vector Index
Clean the raw product feed, build the SQLite database, and generate the L2-normalized FAISS vector index:
```bash
python ingestion/build_faiss_index.py
```
*Outputs: `data/catalog/catalog.sqlite3` and `data/catalog/products.faiss`.*

### 1.5 Verify RS256 Cryptographic Keys
The system authenticates internal MCP tool calls using RS256 key pairs stored in `api/keys/`. If missing or regenerating:
```bash
python api/keys/generate_keys.py
```

---

## 2. Running the Application

### Option A: One-Command Startup (Recommended for Windows: `.\run_app.bat`)

The easiest way to launch the entire system is using `.\run_app.bat`. It selects the project `venv` or `.venv` Python (or falls back to `python`), checks required application imports, then starts the services in separate terminal windows.

If the preflight reports that Windows Application Control blocked a DLL/module, the issue is an operating-system security policy and cannot be fixed by a batch-file command. Ask your IT administrator to review and authorize the trusted dependency; do not disable or bypass the policy.

#### 1. Execute the Batch Script:
* **In Windows PowerShell:**
  ```powershell
  .\run_app.bat
  ```
* **In Command Prompt (cmd.exe):**
  ```cmd
  run_app.bat
  ```
* *(Or double-click `run_app.bat` directly in Windows File Explorer)*

> **Note for PowerShell Users:** In Windows PowerShell, scripts residing in the current directory require the `.\` prefix (i.e. `.\run_app.bat`).

#### 2. Cross-Platform Alternative (macOS / Linux):
If running on macOS or Linux, execute the companion shell script:
```bash
chmod +x run_app.sh
./run_app.sh
```

#### 3. What Happens Under the Hood:
When you run `.\run_app.bat`, the script executes the following sequence:
1. **Directory Anchoring:** Pins the working directory directly to the project root (`cd /d "%~dp0"`).
2. **Python Selection and Preflight:** Uses the interpreter in `venv` or `.venv` if present and checks the application imports before opening service windows.
3. **[1/3] FastAPI Gateway (Port 8000):** Spawns Terminal 1 running the selected Python interpreter with `-m uvicorn api.app:app --host 127.0.0.1 --port 8000 --reload` (handles authentication, rate limiting, and LangGraph workflow).
4. **Stagger Interval (2s):** Waits 2 seconds before launching the MCP server.
5. **[2/3] MCP Tool Server (Port 8001):** Spawns Terminal 2 running the selected Python interpreter with `-m mcp_service.tools` (serves catalog discovery and analytics tools with RS256 token validation).
6. **Stagger Interval (2s):** Waits 2 seconds for MCP tools to register.
7. **[3/3] Streamlit Web UI (Port 8501):** Spawns Terminal 3 running the selected Python interpreter with `-m streamlit run main.py` and opens the chatbot interface in your default browser.

#### 4. Active Service Endpoints:
| Service | Local URL | Swagger / Health URL | Notes |
|---|---|---|---|
| **Streamlit Web UI** | `http://localhost:8501` | `http://localhost:8501` | Interactive Chatbot interface with RBAC (Shopper / Merchandiser / Admin) |
| **FastAPI Backend** | `http://localhost:8000` | `http://localhost:8000/docs` | REST API, auth, JWT minting, audit logs, streaming endpoints |
| **MCP Tool Server** | `http://localhost:8001` | `http://localhost:8001/mcp` | Streamable HTTP Model Context Protocol catalog tools |

#### 5. How to Stop the System:
* Simply close the 3 opened terminal windows (`FastAPI Backend`, `MCP Server`, `Streamlit UI`), or press `Ctrl + C` inside each terminal window to gracefully stop each service.

---

### Option B: Manual Startup (macOS / Linux / Multi-Terminal Debugging)

#### Terminal 1: FastAPI Gateway (Port 8000)
```bash
uvicorn api.app:app --host 127.0.0.1 --port 8000 --reload
```
*API docs available at `http://127.0.0.1:8000/docs`.*

#### Terminal 2: MCP Catalog Tool Server (Port 8001)
```bash
python mcp_service/tools.py
```
*MCP Streamable HTTP endpoint running at `http://127.0.0.1:8001/mcp`.*

#### Terminal 3: Streamlit Web UI (Port 8501)
```bash
streamlit run main.py
```
*Web application opens at `http://localhost:8501`.*

---

## 3. Usage & Persona Walkthrough

### 3.1 Customer (Shopper)
* Sign up on the **Create account** tab (automatically assigned `Shopper`).
* **Product Discovery:** *"Show me oval sapphire rings under $1200 that are in stock."*
* **Typo Tolerance:** *"Suggest me some diamod pendents."* (Correctly resolves to diamond pendants).
* **Multi-Turn Follow-Up:** *"Are these available in ruby?"* (Carries forward the category and design context).
* **Jewelry Care:** *"How should I clean a diamond ring at home?"*
* **Access Control Test:** Ask *"How many products have no sale price?"* $\rightarrow$ Blocked with `403 Forbidden` (*"Catalog analytics and numerical metrics are available to merchandisers and admins only"*).

### 3.2 Staff (Merchandiser)
* Log in with a promoted merchandiser account.
* **Inventory Counts:** *"How many products are in the catalog?"*
* **Category Breakdown:** *"Show me the count of products by jewelry type."*
* **Pricing Audits:** *"What is the price range for rings vs necklaces?"*
* **Missing Price Audit:** *"How many items are missing a sale price, grouped by category?"*
* **Product Inspection:** Products are displayed with internal **Parent SKUs** for merchandising workflow.

### 3.3 Administrator (Admin Controls)
* Log in using the credentials defined in `.env` (`ADMIN_EMAIL` and `ADMIN_PASSWORD`).
* **Manage User Roles:** Look up any registered user by email and promote them to `Merchandiser` or revert to `Shopper`.
* **Inspect Audit Trail:** View historical user queries, assigned roles, timestamps, and routed agents with pagination.
* **Catalog Re-indexing:** Trigger on-demand feed re-cleaning and database reloading (`POST /admin/reindex`).

---

## 4. API Reference

| Endpoint | Method | Role | Description | Response Codes |
|---|---|---|---|---|
| `/register` | `POST` | Public | Register new Shopper account | `201`, `409`, `422` |
| `/login` / `/Login` | `POST` | Public | OAuth2 password authentication; returns user JWT | `200`, `401` |
| `/chat` | `POST` | Authenticated | Send user query; executes LangGraph agent workflow | `200`, `401`, `403`, `429` |
| `/chat/stream` | `POST` | Authenticated | Word-by-word streaming response | `200`, `401`, `403`, `429` |
| `/me` | `GET` | Authenticated | Fetch current user profile and role | `200`, `401`, `404` |
| `/mcp-token` | `POST` | Authenticated | Mint short-lived (60s) role-scoped MCP token | `200`, `401` |
| `/admin/users` | `GET` | Admin | Search user by email | `200`, `401`, `403`, `404` |
| `/admin/users/{id}/role` | `PATCH` | Admin | Promote or demote user role | `200`, `401`, `403`, `422` |
| `/admin/audit` | `GET` | Admin | Query paginated request and route audit logs | `200`, `401`, `403` |
| `/admin/reindex` | `POST` | Admin | Reload and clean feed data into catalog SQLite DB | `200`, `401`, `403`, `500` |

---

## 5. Automated Tests & Evaluation

### 5.1 Unit and Integration Test Suite
Execute the automated pytest suites covering all 11 core quality & safety evaluation vectors (groundedness, deterministic code accuracy, recall@5, zero-hardcoded routing precision, safe adversarial replies, latency speed, and LangGraph trajectory):
```bash
pytest
```

| Test Suite | Purpose | Target Metric |
|---|---|---|
| [`tests/test_router_agent.py`](tests/test_router_agent.py) | Verifies intent classification, typo resolution, and shopper analytics blocking | Accuracy $\ge 90\%$ |
| [`tests/test_recall_at_5.py`](tests/test_recall_at_5.py) | Validates search relevance for stones, metals, and jewelry types | Recall@5 $\ge 0.80$ |
| [`tests/test_number_accuracy.py`](tests/test_number_accuracy.py) | Confirms code verifier rejects hallucinated prices and stock status | Accuracy $= 100\%$ |
| [`tests/test_groundedness.py`](tests/test_groundedness.py) | Evaluates LLM-as-judge grounding against retrieved catalog documents | Groundedness $\ge 4/5$ |
| [`tests/test_safe_replies.py`](tests/test_safe_replies.py) | Tests defense against prompt injections, credential theft, and role bypass | Safety $= 100\%$ |
| [`tests/test_trajectory.py`](tests/test_trajectory.py) | Ensures correct agent node transitions and bounded retry enforcement ($\le 2$) | Accuracy $\ge 85\%$ |
| [`tests/test_speed.py`](tests/test_speed.py) | Benchmarks latency for routing, catalog search, and end-to-end turns | $\text{p50} < 3.0\text{s}$, $\text{p95} < 10.0\text{s}$ |

### 5.2 Benchmark Evaluation (Golden Dataset)
Run the automated benchmark across the 20 golden test questions:
```bash
python eval/run_eval.py
```

---

## 6. Repository Layout

```
.
├── agents/                     # Specialized agent modules
│   ├── catalog_agent.py        # Hybrid Search dispatcher (SQL + FAISS)
│   ├── composer_agent.py       # Code analytics tables & role-tailored product cards
│   ├── knowledge_agent.py      # Jewelry care & sizing knowledge assistant
│   ├── router_agent.py         # Zero-hardcoding structured filter & intent extraction
│   └── verifier_agent.py       # Deterministic code verifier (prices/stock) & LLM judge
├── api/                        # FastAPI gateway service
│   ├── keys/                   # RS256 cryptographic keys & key generator
│   ├── routers/                # Dedicated auth, admin, and chat endpoints
│   ├── security/               # Argon2 password hashing & RS256 token minting
│   ├── store/                  # SQLite repositories for users and audit logs
│   ├── app.py                  # FastAPI application entrypoint
│   ├── dependencies.py         # Role verification & auth dependencies
│   └── middleware.py           # Rate limiting (20 req/min) & request-ID tracking
├── core/                       # Shared prompt templates & LLM factory
├── data/                       # Local SQLite databases, FAISS index & feed rejects
├── docs/                       # High-Level Design (hld.md), Sequence Flows (sequence.md), ADRs
├── eval/                       # Benchmark runner & 20 golden evaluation questions
├── ingestion/                  # Feed ingestion, currency cleaning, and FAISS builder
├── logs/                       # Persistent service execution log (api.log)
├── mcp_service/                # Model Context Protocol (MCP) server & async client
│   ├── tools.py                # Typed tools: search_products, get_product, semantic_search, catalog_stats
│   └── client.py               # Streamable HTTP MCP client helper
├── tests/                      # Automated pytest suites (7 suites covering 11 evaluation vectors)
├── workflow/                   # LangGraph orchestration
│   ├── graph.py                # Graph compilation, node edges, and retry bounds
│   ├── memory.py               # InMemorySaver checkpointer & adaptive summarizer
│   └── state.py                # WorkflowState definition with Annotated message history
├── main.py                     # Streamlit frontend application
├── run_app.bat                 # Staggered multi-service Windows launcher (One-command startup)
├── run_app.sh                  # Staggered multi-service Bash launcher for macOS / Linux
├── requirements.txt            # Project dependencies
└── pytest.ini                  # Pytest configuration
```

---

## 7. Architectural Decisions (ADRs)

* [`docs/adr/001-no-arbitrary-sql.md`](docs/adr/001-no-arbitrary-sql.md) — Why arbitrary SQL execution is prohibited in favor of typed, role-scoped MCP tools.
* [`docs/adr/002-code-based-numeric-verification.md`](docs/adr/002-code-based-numeric-verification.md) — Why all prices and stock statuses are validated with deterministic Python code rather than relying on LLMs.
* [`docs/hld.md`](docs/hld.md) — Complete High-Level Design document.
* [`docs/sequence.md`](docs/sequence.md) — End-to-end Sequence diagrams.
