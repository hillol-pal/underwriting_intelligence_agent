# Underwriting Intelligence Agent

Claims Investigation Workbench. Phase 1 reads claim documents, keeps an evidence ledger with page citations, and searches policy wording with hybrid retrieval. Coverage, fraud, and payment stay with an authorised reviewer.

## User flows

The screens and the path for the policyholder, claims intake, the investigator, and the authorised reviewer are in [docs/customer-journey.md](docs/customer-journey.md).

## Quick start

Phase 1 needs PostgreSQL 16 with pgvector. The Compose file publishes it on port 5433 so it does not collide with a Postgres already using 5432. Tesseract is optional and is used when a PDF page has no text layer.

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
docker compose up -d postgres

# API
uvicorn app.main:app --reload --port 8000

# UI, in a second terminal
source venv/bin/activate
streamlit run app/ui/streamlit_app.py
```

Or the full stack:

```bash
cp .env.example .env
docker compose up --build
```

- UI: http://localhost:8501
- API: http://localhost:8000
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

On **New claim**, press **Load September collision pack**. Then open **Evidence ledger** and **Search**.

## Embeddings

`EMBEDDING_PROVIDER=auto` calls xAI `POST /v1/embeddings` with model `v1` when `XAI_API_KEY` is set. With no key, ingestion uses a local hashing embedding so lexical search and the evidence ledger still run. Set `EMBEDDING_PROVIDER=xai` to require the API. Date comparisons and money checks never call a model.

## Evaluate

```bash
python scripts/evaluate.py
```

That loads the 8 synthetic claims (32 PDFs) into the database from `.env` and prints fact-extraction accuracy, citation correctness, and retrieval checks for the September file. The same checks are in `tests/test_phase1.py`.

## Structure

- `app/api/` — FastAPI routes
- `app/ui/` — Streamlit workbench
- `app/corpus/` — labeled synthetic motor claims and PDF builder
- `app/services/` — ingestion, chunking, hybrid retrieval, extraction, ledger
- `app/agents/` — supervisor and specialist stubs for Phase 2
- `app/core/` — evidence-ledger models and config

## Current status

Phase 1 is in place: PDF ingestion, optional Tesseract OCR, section-aware chunks, pgvector plus PostgreSQL full-text search, metadata filters, a coverage bundle that also returns the exclusion, endorsement, and insured-period definition, and ledger rows with quotes and pages.

## Next steps

1. Wire the Deep Agent supervisor and the specialist roles.
2. Add reranking, query expansion, and parent-child retrieval beyond the surrounding clause.
3. Add LangGraph checkpointing and a human approval gate.
4. Add regression evaluations for prompt injection hidden in PDFs.
