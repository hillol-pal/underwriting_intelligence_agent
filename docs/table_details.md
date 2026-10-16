The application database has six tables, all created in init_db in app/services/store.py. Every foreign key uses ON DELETE CASCADE. Deleting a claim removes its documents, pages, chunks, findings, and investigation runs.

┌───────────────┬─────────────┬─────────────────────┬──────────────────────────────────────────────────────────┐
│ Table         │ Primary key │ Foreign keys        │ Metadata fields                                          │
├───────────────┼─────────────┼─────────────────────┼──────────────────────────────────────────────────────────┤
│ claims        │ claim_id    │ none                │ policy_number, incident_date_claimed, status, created    │
│               │             │                     │ _at, updated_at                                          │
├───────────────┼─────────────┼─────────────────────┼──────────────────────────────────────────────────────────┤
│ documents     │ document_id │ claim_id → claims.  │ filename, document_type, policy_version, effective_date, │
│               │             │ claim_id            │ jurisdiction, storage_path, page_count, ocr_pages,       │
│               │             │                     │ ingested_at                                              │
├───────────────┼─────────────┼─────────────────────┼──────────────────────────────────────────────────────────┤
│ pages         │ (document   │ document_id →       │ ocr_used, unreadable. body is the page text              │
│               │ _id, page_  │ documents.document  │                                                          │
│               │ number)     │ _id; claim_id →     │                                                          │
│               │             │ claims.claim_id     │                                                          │
├───────────────┼─────────────┼─────────────────────┼──────────────────────────────────────────────────────────┤
│ chunks        │ chunk_id    │ claim_id → claims.  │ section_id, filename, document_type, page_number,        │
│               │             │ claim_id; document  │ section_kind, section_title, policy_version, effective   │
│               │             │ _id → documents.    │ _date, jurisdiction, embedding_provider. body is the     │
│               │             │ document_id         │ embedded window, section_body is the whole section,      │
│               │             │                     │ embedding is vector(256), tsv is a generated full-text   │
│               │             │                     │ column on body                                           │
├───────────────┼─────────────┼─────────────────────┼──────────────────────────────────────────────────────────┤
│ findings      │ finding_id  │ claim_id → claims.  │ finding_type, claim_or_policy_fact, normalized_value,    │
│               │             │ claim_id            │ source_document_id, page_number, quoted_source_text,     │
│               │             │                     │ confidence, verification_status, contradicts, depends    │
│               │             │                     │ _on, next_action, responsible_reviewer, created_at,      │
│               │             │                     │ origin, specialist, run_id                               │
├───────────────┼─────────────┼─────────────────────┼──────────────────────────────────────────────────────────┤
│ investigation │ run_id      │ claim_id → claims.  │ status, plan_json, specialist_outputs_json, supervisor   │
│ _runs         │             │ claim_id            │ _model, specialist_model, findings_added, error, stale_  │
│               │             │                     │ reason, started_at, finished_at                          │
└───────────────┴─────────────┴─────────────────────┴──────────────────────────────────────────────────────────┘