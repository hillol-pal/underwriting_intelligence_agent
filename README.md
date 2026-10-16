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
docker compose up -d postgres mlflow

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
- MLflow: http://localhost:5001

On **New claim**, press **Load September collision pack**. Then open **Evidence ledger** and **Search**.

## Embeddings

`EMBEDDING_PROVIDER=auto` uses OpenAI `text-embedding-3-small` at 256 dimensions when `OPENAI_API_KEY` is set. With no OpenAI key it uses xAI when `XAI_API_KEY` is set, and otherwise a local hashing embedding. Set `EMBEDDING_PROVIDER=openai` to require OpenAI. Date comparisons and money checks never call a model.

Agent chat is a separate setting. `LLM_PROVIDER` must be `openai`. The supervisor uses `LLM_MODEL` and the four specialists use `LLM_SPECIALIST_MODEL`. Embeddings stay on the 256-dimension pgvector column. Do not point `EMBEDDING_MODEL` at `text-embedding-3-small` or `text-embedding-3-large`. The investigation agent stays off until `INVESTIGATION_AGENT_ENABLED=true`.

## Observability

MLflow runs in Docker on http://localhost:5001 (port 5000 is macOS AirPlay). Loading the September collision pack writes a trace to the `underwriting-intelligence-agent` experiment. OpenAI embedding calls are child spans. The API reads `.env` again when the process starts, so a change to the key or `MLFLOW_TRACKING_URI` applies on the next start. Inside Compose, the API uses `http://mlflow:5000`.

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
- `app/agents/` — Deep Agent supervisor and the policy, evidence, contradiction, and loss specialists
- `app/core/` — evidence-ledger models and config

## Current status

Phase 1 reads PDFs into the evidence ledger. Phase 2 adds the supervisor and four specialists behind `INVESTIGATION_AGENT_ENABLED`. Chat completions use OpenAI. Embeddings stay 256-dimensional. The supervisor does not grant cover, decide fraud, or authorise payment. `human_review_required` stays true. The path is drawn in [docs/phase-2-flow.md](docs/phase-2-flow.md).

## Next steps

1. Add reranking, query expansion, and parent-child retrieval beyond the surrounding clause.
2. Add a prompt-injection regression corpus. The specialist tools already wrap page text as untrusted data.
3. Leave LangGraph checkpointing and an in-app approval gate for a later phase. The reviewer still decides outside this application.
