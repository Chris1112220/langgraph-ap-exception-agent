# LangGraph AP Exception Agent

An AI agent that resolves **accounts payable (AP) invoice exceptions**: the invoices an RPA bot or ERP couldn't auto-post because of price variances, missing POs, duplicates, vendor holds, and similar issues. The agent uses **LangGraph + Google Gemini** to investigate each exception with deterministic tools, checks company AP policy through **RAG over pgvector**, and proposes a fix, with **human-in-the-loop approval** for anything risky.

> **Status:** Week 1 in progress. Days 1-2 complete (database + agent tools).

## Why
In real finance automation, RPA handles the happy path. The exceptions (often 10-30% of invoices) land in a human queue. This project automates the triage: *let the LLM decide, let code calculate.*

## Tech stack
| Layer | Tools |
|---|---|
| Agent | LangGraph, LangChain, Google Gemini |
| Data | PostgreSQL 16 + pgvector (Docker Compose) |
| Code | Python 3, Pydantic, psycopg 3 |
| API (planned) | FastAPI webhook for n8n / UiPath |
| Quality | pytest, GitHub Actions CI (LangSmith tracing planned) |

## What's built so far
- **Day 1, Data layer:** Postgres + pgvector in Docker, normalized AP schema (vendors, purchase orders, PO lines, receipts, invoices, invoice lines, posted invoices), and an idempotent seed script with 20 realistic exception invoices (price variance, over-billing, missing/typo PO, duplicate, vendor on hold, fuzzy vendor name, prompt injection, approval limit, UOM mismatch, and more).
- **Day 2, Agent tools:** Pydantic models plus deterministic tools for fuzzy vendor lookup, three-way match (PO vs. receipt vs. invoice, with price tolerance), and duplicate detection.

## Roadmap
- [x] Day 1: Database, schema, seed data
- [x] Day 2: Vendor lookup, three-way match, duplicate check
- [ ] Day 3: AP policy RAG (Gemini embeddings + pgvector)
- [ ] Day 4: LangGraph agent with tool calling, guardrails, and human-in-the-loop approval
- [ ] Day 5: FastAPI webhook (callable from n8n / UiPath)
- [x] Day 6: pytest tests and GitHub Actions CI (LangSmith tracing still planned)
- [ ] Day 7: Deployment + final write-up

## Run it locally (Windows / PowerShell)
Prerequisites: Python 3.11+, Docker Desktop, a free [Gemini API key](https://aistudio.google.com/apikey).

```powershell
git clone https://github.com/Chris1112220/langgraph-ap-exception-agent.git
cd langgraph-ap-exception-agent

# 1. Settings: copy the template and fill in your own keys
Copy-Item .env.example .env

# 2. Start Postgres + pgvector (schema is created automatically)
docker compose up -d

# 3. Python environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 4. Load the 20 test exception invoices, then try the tools
python scripts/seed_data.py
python scripts/try_tools.py

# 5. Run the tests (no database or API keys needed; the suite is fully mocked)
pytest -q
```

## Project layout
```
app/
  db.py          # database connection helper
  models.py      # Pydantic models for tool results
  tools.py       # vendor lookup, three-way match, duplicate check
db/init/
  01_schema.sql  # tables, created on first container start
scripts/
  seed_data.py   # loads vendors, POs, receipts, 20 exceptions
  try_tools.py   # manual check of the tools
tests/
  test_tools.py  # mocked unit tests for the agent tools
.github/workflows/ci.yml
docker-compose.yml
requirements.txt
.env.example
```

## Tests and CI

![tests](https://github.com/Chris1112220/langgraph-ap-exception-agent/actions/workflows/ci.yml/badge.svg)

5 pytest tests cover vendor-name and invoice-number normalization, vendor lookup (ID, exact, fuzzy, and miss), three-way match (price variance vs. the 2% tolerance, OCR PO typo, over-billing, missing receipt), and duplicate detection that ignores invoice-number formatting. The database is mocked, so the suite runs with no Postgres and no API keys.

```bash
pytest -q
```

GitHub Actions runs the same tests on every push and pull request.

## Author
Christopher Roberts, RPA & AI automation developer.