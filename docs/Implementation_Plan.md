Software other than Python libraries

Phase 0 needs nothing else. Use the existing venv (Python 3.13). The system Python is 3.8, so stay inside that virtualenv. Docker is optional for the current stub.

This machine already has Docker 20.10.8, Docker Compose, Homebrew, and PostgreSQL 14.12 listening on port 5432. That Postgres instance asks for a password. .env.example assumes postgres:postgres, which does not match it. pgvector, Tesseract, and Poppler are not installed.

Install these before Phase 1:

┌────────────────────┬─────────────────────────────────────────────────┬───────────────────────────────────────────┐
│ Software           │ Why                                             │ On this Mac                               │
├────────────────────┼─────────────────────────────────────────────────┼───────────────────────────────────────────┤
│ PostgreSQL with    │ Vector storage plus full-text search for hybrid │ Prefer a separate pgvector/pgvector       │
│ pgvector           │ retrieval                                       │ Postgres 16 container on port 5433. Leave │
│                    │                                                 │ the existing Postgres 14 alone.           │
├────────────────────┼─────────────────────────────────────────────────┼───────────────────────────────────────────┤
│ Tesseract OCR (    │ Read scanned policy, police, and garage PDFs    │ Not installed                             │
│ brew install       │                                                 │                                           │
│ tesseract)         │                                                 │                                           │
├────────────────────┼─────────────────────────────────────────────────┼───────────────────────────────────────────┤
│ Poppler (brew      │ Rasterize scanned pages before OCR (pdftoppm)   │ Not installed                             │
│ install poppler)   │                                                 │                                           │
├────────────────────┼─────────────────────────────────────────────────┼───────────────────────────────────────────┤
│ xAI API key        │ Structured extraction. Not a local install. Put │ The sample env still points at OpenAI     │
│                    │ XAI_API_KEY in a git-ignored .env and call      │                                           │
│                    │ https://api.x.ai/v1                             │                                           │
└────────────────────┴─────────────────────────────────────────────────┴───────────────────────────────────────────┘

Do not add OpenSearch, a graph database, or LangSmith for Phase 1. PostgreSQL full-text search is the lexical index. Vision review of photographs can wait until the text pipeline cites pages correctly.

Phase 1 plan — document intelligence and baseline RAG

Phase 1 replaces the seeded ledger with facts read from a synthetic claim pack. The investigator can upload those files and retrieve the coverage clause together with the exclusion, the endorsement, and the insured-period definition, each with a document id and a page. The September date conflict stays unresolved. Coverage stays pending.

Specialist agents, the Deep Agent supervisor, reranking, parent-child retrieval, an evidence graph, checkpointing, and the human-approval workflow stay in later phases.

Done when

• A labeled corpus of 5–10 claims and 20–40 documents exists, including this collision file.
• Upload stores the file and runs ingestion. The current upload route only returns a stub receipt.
• Chunks keep claim id, document type, page, policy version, effective date, and section kind (schedule, exclusion, endorsement, definition, claim field, estimate line).
• Search is pgvector similarity plus PostgreSQL full-text search, filtered by that metadata.
• Each material hit can return the surrounding clause, not only the one similar paragraph.
• New ledger rows use the existing Finding model: quoted text, page, confidence, and status extracted or unresolved.
• A normal date comparison, not the model, flags 12 September against a 15 September inception.
• An evaluation script reports Recall@k, citation correctness, and fact-extraction accuracy on the labeled set.
• Streamlit can upload a pack, show retrieved passages, and load ledger rows that came from those files.

Build order

1. Corpus and answer key. Write the September claim as PDFs plus a few scanned pages. Label inception, both incident dates, the exclusion, the endorsement, the insured-period definition, and the pre-existing bumper line, each with a page.
2. Database. Add a Postgres 16 + pgvector service on port 5433. Tables for documents, pages, and chunks. Enable vector and a full-text column.
3. Ingestion. PyMuPDF for digital text and page numbers. Poppler + Tesseract when a page has no text. Save document type, claim id, and page image path.
4. Chunking. Split on policy headings, exclusions, endorsements, definitions, tables, and claim fields. Carry the page number onto every chunk.
5. Indexing. Embed chunks through the xAI API and store the vector next to the tsvector.
6. Retrieval service. Hybrid search with metadata filters. A query about collision cover must be able to pull the exclusion, endorsement, and period definition in the same result set.
7. Extraction. Map retrieved passages into Finding rows. Keep the quote and the page. Do not mark a row verified unless the deterministic date check agrees.
8. Wire the existing API and UI. Persist uploads, fill the ledger from extraction, and add a retrieval panel. Leave the Phase 0 seeded path available only as an explicit demo.
9. Evaluation. Run the labeled questions and fail the build if a cited page does not contain the quoted text.

The current modules stay where they are. New work belongs in ingestion, retrieval, and extraction services, with app/api/routes.py and app/ui/streamlit_app.py calling them. InvestigationSupervisor stays a stub until Phase 2