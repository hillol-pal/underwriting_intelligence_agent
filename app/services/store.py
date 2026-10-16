"""PostgreSQL + pgvector persistence for claims, pages, chunks, and findings."""
import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

import psycopg2
from pgvector.psycopg2 import register_vector
from psycopg2.errors import UniqueViolation
from psycopg2.extras import Json, RealDictCursor

from app.core.config import settings
from app.core.logutil import event
from app.core.models import (
    Claim,
    ClaimStatus,
    DocumentSummary,
    Finding,
    FindingType,
    InvestigationRunView,
    InvestigationStepView,
    VerificationStatus,
)

logger = logging.getLogger("app.agents")

RUNNING_LOCK = "An investigation is running for this claim."

_ready_url: str | None = None


class DatabaseUnavailable(RuntimeError):
    pass


class InvestigationInProgress(RuntimeError):
    """A fresh running row holds the claim. The route maps this to HTTP 409."""

    def __init__(self, detail: str = RUNNING_LOCK):
        super().__init__(detail)


def reset_schema_cache() -> None:
    global _ready_url
    _ready_url = None


def database_name(url: str) -> str:
    name = urlparse(url).path.lstrip("/")
    if not name or not name.replace("_", "").isalnum():
        raise ValueError(f"Unsupported database name in {url}")
    return name


def with_database(url: str, name: str) -> str:
    if not name.replace("_", "").isalnum():
        raise ValueError(name)
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=f"/{name}"))


def ensure_database(url: str) -> None:
    name = database_name(url)
    admin_url = with_database(url, "postgres")
    try:
        connection = psycopg2.connect(admin_url, connect_timeout=3)
    except psycopg2.OperationalError as exc:
        raise DatabaseUnavailable(
            "PostgreSQL is not available. Start it with `docker compose up -d postgres` "
            f"(expected {settings.database_url}). {exc}"
        ) from exc
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
            if cursor.fetchone() is None:
                cursor.execute(f'CREATE DATABASE "{name}"')
    finally:
        connection.close()


def ping_ok() -> bool:
    """True when PostgreSQL accepts connections. Schema setup happens on the first claim call."""
    try:
        connection = psycopg2.connect(settings.database_url, connect_timeout=3)
    except psycopg2.Error:
        return False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except psycopg2.Error:
        return False
    finally:
        connection.close()


@contextmanager
def connect():
    try:
        connection = psycopg2.connect(settings.database_url, connect_timeout=3)
    except psycopg2.OperationalError as exc:
        raise DatabaseUnavailable(
            "PostgreSQL is not available. Start it with `docker compose up -d postgres` "
            f"(expected {settings.database_url}). {exc}"
        ) from exc
    try:
        register_vector(connection)
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    global _ready_url
    if _ready_url == settings.database_url:
        return
    ensure_database(settings.database_url)
    raw = psycopg2.connect(settings.database_url, connect_timeout=3)
    raw.autocommit = True
    try:
        with raw.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
    except psycopg2.Error as exc:
        raise DatabaseUnavailable(
            "The pgvector extension is not installed on this PostgreSQL. Use the pgvector/pgvector image."
        ) from exc
    finally:
        raw.close()

    dim = int(settings.embedding_dimensions)
    if not 8 <= dim <= 4096:
        raise ValueError("embedding_dimensions must be between 8 and 4096")
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS claims (
                    claim_id TEXT PRIMARY KEY,
                    policy_number TEXT,
                    incident_date_claimed TEXT,
                    status TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
                    filename TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    policy_version TEXT,
                    effective_date TEXT,
                    jurisdiction TEXT,
                    storage_path TEXT NOT NULL,
                    page_count INT NOT NULL,
                    ocr_pages INT NOT NULL DEFAULT 0,
                    ingested_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS pages (
                    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
                    claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
                    page_number INT NOT NULL,
                    body TEXT NOT NULL,
                    ocr_used BOOLEAN NOT NULL,
                    unreadable BOOLEAN NOT NULL,
                    PRIMARY KEY (document_id, page_number)
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    section_id TEXT NOT NULL,
                    claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
                    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
                    filename TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    page_number INT NOT NULL,
                    section_kind TEXT NOT NULL,
                    section_title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    section_body TEXT NOT NULL,
                    policy_version TEXT,
                    effective_date TEXT,
                    jurisdiction TEXT,
                    embedding vector({dim}),
                    embedding_provider TEXT NOT NULL,
                    tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', body)) STORED
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS findings (
                    finding_id TEXT PRIMARY KEY,
                    claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
                    finding_type TEXT NOT NULL,
                    claim_or_policy_fact TEXT NOT NULL,
                    normalized_value TEXT,
                    source_document_id TEXT,
                    page_number INT,
                    quoted_source_text TEXT,
                    confidence DOUBLE PRECISION NOT NULL,
                    verification_status TEXT NOT NULL,
                    contradicts TEXT[] NOT NULL DEFAULT '{}',
                    depends_on TEXT[] NOT NULL DEFAULT '{}',
                    next_action TEXT,
                    responsible_reviewer TEXT,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS chunks_claim_idx ON chunks (claim_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING GIN (tsv)")
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS chunks_embedding_idx
                ON chunks USING hnsw (embedding vector_cosine_ops)
                """
            )
            # Phase 1 databases already have findings. CREATE TABLE will not add columns.
            cursor.execute("ALTER TABLE findings ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'extraction'")
            cursor.execute("ALTER TABLE findings ADD COLUMN IF NOT EXISTS specialist TEXT")
            cursor.execute("ALTER TABLE findings ADD COLUMN IF NOT EXISTS run_id TEXT")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS investigation_runs (
                    run_id TEXT PRIMARY KEY,
                    claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    plan_json JSONB NOT NULL,
                    specialist_outputs_json JSONB NOT NULL DEFAULT '[]',
                    supervisor_model TEXT NOT NULL,
                    specialist_model TEXT NOT NULL,
                    findings_added INT NOT NULL DEFAULT 0,
                    error TEXT,
                    stale_reason TEXT,
                    started_at TIMESTAMPTZ NOT NULL,
                    finished_at TIMESTAMPTZ
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS investigation_runs_claim_idx
                ON investigation_runs (claim_id, started_at DESC)
                """
            )
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS investigation_runs_one_running_idx
                ON investigation_runs (claim_id) WHERE status = 'running'
                """
            )
    _ready_url = settings.database_url


def _claim_from_row(row: dict) -> Claim:
    return Claim(
        claim_id=row["claim_id"],
        policy_number=row["policy_number"],
        incident_date_claimed=row["incident_date_claimed"],
        status=ClaimStatus(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def upsert_claim(claim: Claim) -> Claim:
    init_db()
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO claims (claim_id, policy_number, incident_date_claimed, status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (claim_id) DO UPDATE SET
                    policy_number = EXCLUDED.policy_number,
                    incident_date_claimed = EXCLUDED.incident_date_claimed,
                    status = EXCLUDED.status,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    claim.claim_id,
                    claim.policy_number,
                    claim.incident_date_claimed,
                    claim.status.value,
                    claim.created_at,
                    claim.updated_at,
                ),
            )
    return claim


def get_claim(claim_id: str) -> Claim | None:
    init_db()
    with connect() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM claims WHERE claim_id = %s", (claim_id,))
            row = cursor.fetchone()
    return _claim_from_row(row) if row else None


def set_claim_status(claim_id: str, status: ClaimStatus) -> None:
    init_db()
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE claims SET status = %s, updated_at = %s WHERE claim_id = %s",
                (status.value, datetime.utcnow(), claim_id),
            )


def save_ingested_document(document: dict, pages: list[dict], chunks: list[dict]) -> None:
    """Replace one filename and write its pages and chunks in a single transaction."""
    event(
        logger,
        "save document",
        claim_id=document.get("claim_id"),
        filename=document.get("filename"),
        document_type=document.get("document_type"),
        pages=[{"page": page.get("page_number"), "text": page.get("body")} for page in pages],
        chunks=[
            {
                "page": chunk.get("page_number"),
                "kind": chunk.get("section_kind"),
                "text": chunk.get("body"),
                "provider": chunk.get("embedding_provider"),
                "dimensions": len(chunk.get("embedding") or []),
            }
            for chunk in chunks
        ],
    )
    init_db()
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM documents WHERE claim_id = %s AND filename = %s",
                (document["claim_id"], document["filename"]),
            )
            cursor.execute(
                """
                INSERT INTO documents (
                    document_id, claim_id, filename, document_type, policy_version, effective_date,
                    jurisdiction, storage_path, page_count, ocr_pages, ingested_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    document["document_id"],
                    document["claim_id"],
                    document["filename"],
                    document["document_type"],
                    document["policy_version"],
                    document["effective_date"],
                    document["jurisdiction"],
                    document["storage_path"],
                    document["page_count"],
                    document["ocr_pages"],
                    datetime.utcnow(),
                ),
            )
            for page in pages:
                cursor.execute(
                    """
                    INSERT INTO pages (document_id, claim_id, page_number, body, ocr_used, unreadable)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        page["document_id"],
                        page["claim_id"],
                        page["page_number"],
                        page["body"],
                        page["ocr_used"],
                        page["unreadable"],
                    ),
                )
            for chunk in chunks:
                cursor.execute(
                    """
                    INSERT INTO chunks (
                        chunk_id, section_id, claim_id, document_id, filename, document_type, page_number,
                        section_kind, section_title, body, section_body, policy_version, effective_date,
                        jurisdiction, embedding, embedding_provider
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s
                    )
                    """,
                    (
                        chunk["chunk_id"],
                        chunk["section_id"],
                        chunk["claim_id"],
                        chunk["document_id"],
                        chunk["filename"],
                        chunk["document_type"],
                        chunk["page_number"],
                        chunk["section_kind"],
                        chunk["section_title"],
                        chunk["body"],
                        chunk["section_body"],
                        chunk["policy_version"],
                        chunk["effective_date"],
                        chunk["jurisdiction"],
                        chunk["embedding"],
                        chunk["embedding_provider"],
                    ),
                )


def list_documents(claim_id: str) -> list[DocumentSummary]:
    init_db()
    with connect() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT * FROM documents WHERE claim_id = %s ORDER BY ingested_at, filename",
                (claim_id,),
            )
            rows = cursor.fetchall()
    return [DocumentSummary.model_validate(dict(row)) for row in rows]


def pages_for_claim(claim_id: str) -> list[dict]:
    init_db()
    with connect() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT pages.*, documents.filename, documents.document_type
                FROM pages
                JOIN documents ON documents.document_id = pages.document_id
                WHERE pages.claim_id = %s
                ORDER BY documents.filename, pages.page_number
                """,
                (claim_id,),
            )
            return [dict(row) for row in cursor.fetchall()]


def _insert_finding(cursor, finding: Finding) -> None:
    cursor.execute(
        """
        INSERT INTO findings (
            finding_id, claim_id, finding_type, claim_or_policy_fact, normalized_value,
            source_document_id, page_number, quoted_source_text, confidence, verification_status,
            contradicts, depends_on, next_action, responsible_reviewer, created_at,
            origin, specialist, run_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            finding.finding_id,
            finding.claim_id,
            finding.finding_type.value,
            finding.claim_or_policy_fact,
            finding.normalized_value,
            finding.source_document_id,
            finding.page_number,
            finding.quoted_source_text,
            finding.confidence,
            finding.verification_status.value,
            finding.contradicts,
            finding.depends_on,
            finding.next_action,
            finding.responsible_reviewer,
            finding.created_at,
            finding.origin,
            finding.specialist,
            finding.run_id,
        ),
    )


def _fresh_running_id(cursor, claim_id: str) -> str | None:
    cursor.execute(
        """
        SELECT run_id FROM investigation_runs
        WHERE claim_id = %s AND status = 'running'
          AND started_at >= NOW() - INTERVAL '15 minutes'
        """,
        (claim_id,),
    )
    row = cursor.fetchone()
    return row[0] if row else None


def _supersede_stale_running(cursor, claim_id: str) -> int:
    cursor.execute(
        """
        UPDATE investigation_runs
        SET status = 'failed', error = 'superseded', finished_at = NOW()
        WHERE claim_id = %s AND status = 'running'
          AND started_at < NOW() - INTERVAL '15 minutes'
        """,
        (claim_id,),
    )
    if cursor.rowcount:
        logger.error("superseded claim_id=%s rows=%s", claim_id, cursor.rowcount)
    return cursor.rowcount


def assert_no_fresh_run(claim_id: str) -> None:
    """Refuse before a delete while a running row is younger than 15 minutes."""
    init_db()
    with connect() as connection:
        with connection.cursor() as cursor:
            if _fresh_running_id(cursor, claim_id):
                raise InvestigationInProgress()


def replace_findings(claim_id: str, findings: list[Finding]) -> None:
    init_db()
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM findings WHERE claim_id = %s", (claim_id,))
            for finding in findings:
                _insert_finding(cursor, finding)


def replace_extracted_findings(claim_id: str, findings: list[Finding], owner_run_id: str | None = None) -> bool:
    """Replace extraction, specialist, and seed rows.

    A fresh running row blocks this unless ``owner_run_id`` is that row.
    Returns true when a previous completed run was marked stale.
    """
    init_db()
    marked = False
    superseded = 0
    with connect() as connection:
        with connection.cursor() as cursor:
            fresh = _fresh_running_id(cursor, claim_id)
            if fresh and fresh != owner_run_id:
                raise InvestigationInProgress()
            if owner_run_id is None:
                superseded = _supersede_stale_running(cursor, claim_id)
            cursor.execute(
                """
                DELETE FROM findings
                WHERE claim_id = %s AND origin IN ('extraction', 'specialist', 'seed')
                """,
                (claim_id,),
            )
            for finding in findings:
                _insert_finding(cursor, finding)
            cursor.execute(
                """
                UPDATE investigation_runs
                SET status = 'stale', stale_reason = 'documents_changed',
                    finished_at = COALESCE(finished_at, NOW())
                WHERE run_id = (
                    SELECT run_id FROM investigation_runs
                    WHERE claim_id = %s
                      AND status IN ('completed', 'completed_with_gaps', 'stale')
                      AND (%s = '' OR run_id <> %s)
                    ORDER BY started_at DESC
                    LIMIT 1
                )
                """,
                (claim_id, owner_run_id or "", owner_run_id or ""),
            )
            marked = cursor.rowcount > 0
    if marked or superseded:
        from app.agents.metrics import record_run

        if superseded:
            record_run("failed")
        if marked:
            record_run("stale")
    return marked


def replace_specialist_findings(claim_id: str, run_id: str, findings: list[Finding]) -> None:
    """Delete specialist rows for the claim, then insert this run's drafts."""
    init_db()
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM findings WHERE claim_id = %s AND origin = 'specialist'",
                (claim_id,),
            )
            for finding in findings:
                finding.run_id = run_id
                finding.origin = "specialist"
                _insert_finding(cursor, finding)


def delete_specialist_findings_for_run(claim_id: str, run_id: str) -> None:
    init_db()
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM findings WHERE claim_id = %s AND origin = 'specialist' AND run_id = %s",
                (claim_id, run_id),
            )


def seed_ledger(claim_id: str, findings: list[Finding]) -> None:
    """Replace the ledger with seed rows and mark the latest run stale.

    A fresh running row raises before any delete. An older running row is
    marked stale so the partial unique index can accept a later investigate.
    """
    init_db()
    marked = False
    with connect() as connection:
        with connection.cursor() as cursor:
            if _fresh_running_id(cursor, claim_id):
                raise InvestigationInProgress()
            cursor.execute("DELETE FROM findings WHERE claim_id = %s", (claim_id,))
            for finding in findings:
                finding.origin = "seed"
                _insert_finding(cursor, finding)
            cursor.execute(
                """
                UPDATE investigation_runs
                SET status = 'stale', stale_reason = 'seed_example',
                    finished_at = COALESCE(finished_at, NOW())
                WHERE run_id = (
                    SELECT run_id FROM investigation_runs
                    WHERE claim_id = %s
                    ORDER BY started_at DESC
                    LIMIT 1
                )
                """,
                (claim_id,),
            )
            marked = cursor.rowcount > 0
    if marked:
        from app.agents.metrics import record_run

        record_run("stale")


def list_findings(claim_id: str) -> list[Finding]:
    init_db()
    with connect() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT * FROM findings WHERE claim_id = %s ORDER BY created_at, finding_id",
                (claim_id,),
            )
            rows = cursor.fetchall()
    findings: list[Finding] = []
    for row in rows:
        payload = dict(row)
        payload["finding_type"] = FindingType(payload["finding_type"])
        payload["verification_status"] = VerificationStatus(payload["verification_status"])
        payload["contradicts"] = list(payload["contradicts"] or [])
        payload["depends_on"] = list(payload["depends_on"] or [])
        payload["origin"] = payload.get("origin") or "extraction"
        payload["specialist"] = payload.get("specialist")
        payload["run_id"] = payload.get("run_id")
        findings.append(Finding.model_validate(payload))
    return findings


def _loads(value):
    if value is None or isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def insert_running_run(claim_id: str, run_id: str, supervisor_model: str, specialist_model: str) -> None:
    """Insert the lock row. A running row older than 15 minutes is superseded first."""
    init_db()
    superseded = 0
    with connect() as connection:
        with connection.cursor() as cursor:
            superseded = _supersede_stale_running(cursor, claim_id)
            try:
                cursor.execute(
                    """
                    INSERT INTO investigation_runs (
                        run_id, claim_id, status, plan_json, specialist_outputs_json,
                        supervisor_model, specialist_model, findings_added, started_at
                    ) VALUES (%s, %s, 'running', %s, %s, %s, %s, 0, %s)
                    """,
                    (
                        run_id,
                        claim_id,
                        Json({}),
                        Json([]),
                        supervisor_model,
                        specialist_model,
                        datetime.now(timezone.utc),
                    ),
                )
            except UniqueViolation as exc:
                if "investigation_runs_one_running_idx" not in str(exc):
                    raise
                raise InvestigationInProgress() from exc
    if superseded:
        from app.agents.metrics import record_run

        record_run("failed")


def save_run_plan(run_id: str, plan: dict) -> None:
    init_db()
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE investigation_runs SET plan_json = %s WHERE run_id = %s",
                (Json(plan), run_id),
            )


def finish_run(
    run_id: str,
    status: str,
    plan: dict | None,
    outputs,
    findings_added: int,
    error: str | None = None,
    stale_reason: str | None = None,
) -> None:
    init_db()
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE investigation_runs
                SET status = %s,
                    plan_json = COALESCE(%s, plan_json),
                    specialist_outputs_json = %s,
                    findings_added = %s,
                    error = %s,
                    stale_reason = COALESCE(%s, stale_reason),
                    finished_at = %s
                WHERE run_id = %s
                """,
                (
                    status,
                    Json(plan) if plan is not None else None,
                    Json(outputs if outputs is not None else []),
                    findings_added,
                    error,
                    stale_reason,
                    datetime.now(timezone.utc),
                    run_id,
                ),
            )


def latest_investigation_run(claim_id: str) -> InvestigationRunView | None:
    init_db()
    with connect() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT * FROM investigation_runs
                WHERE claim_id = %s
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (claim_id,),
            )
            row = cursor.fetchone()
    if row is None:
        return None
    plan = _loads(row["plan_json"]) or {}
    steps = []
    for step in plan.get("steps") or []:
        steps.append(
            InvestigationStepView(
                step_id=step.get("step_id") or "",
                specialist=str(step.get("specialist") or ""),
                status=str(step.get("status") or ""),
                skip_reason=step.get("skip_reason"),
            )
        )
    return InvestigationRunView(
        run_id=row["run_id"],
        claim_id=row["claim_id"],
        status=row["status"],
        plan_id=plan.get("plan_id") or "",
        supervisor_model=row["supervisor_model"],
        specialist_model=row["specialist_model"],
        steps=steps,
        findings_added=row["findings_added"] or 0,
        error=row["error"],
        stale_reason=row["stale_reason"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def _filters(sql_parts: list[str], params: list, document_type, section_kind, policy_version, effective_date) -> None:
    for column, value in (
        ("document_type", document_type),
        ("section_kind", section_kind),
        ("policy_version", policy_version),
        ("effective_date", effective_date),
    ):
        sql_parts.append(f"AND (%s::text IS NULL OR {column} = %s)")
        params.extend([value, value])


def vector_search(claim_id: str, provider: str, vector: list[float], limit: int, **filters) -> list[dict]:
    init_db()
    sql = [
        """
        SELECT chunk_id, document_id, filename, document_type, page_number, section_kind,
               section_title, body, section_body, policy_version, effective_date,
               1 - (embedding <=> %s::vector) AS vector_score
        FROM chunks
        WHERE claim_id = %s AND embedding_provider = %s
        """
    ]
    params: list = [vector, claim_id, provider]
    _filters(
        sql,
        params,
        filters.get("document_type"),
        filters.get("section_kind"),
        filters.get("policy_version"),
        filters.get("effective_date"),
    )
    sql.append("ORDER BY embedding <=> %s::vector LIMIT %s")
    params.extend([vector, limit])
    with connect() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("\n".join(sql), params)
            return [dict(row) for row in cursor.fetchall()]


def lexical_search(claim_id: str, query: str, limit: int, **filters) -> list[dict]:
    init_db()
    sql = [
        """
        SELECT chunk_id, document_id, filename, document_type, page_number, section_kind,
               section_title, body, section_body, policy_version, effective_date,
               ts_rank_cd(tsv, plainto_tsquery('english', %s)) AS lexical_score
        FROM chunks
        WHERE claim_id = %s AND tsv @@ plainto_tsquery('english', %s)
        """
    ]
    params: list = [query, claim_id, query]
    _filters(
        sql,
        params,
        filters.get("document_type"),
        filters.get("section_kind"),
        filters.get("policy_version"),
        filters.get("effective_date"),
    )
    sql.append("ORDER BY lexical_score DESC LIMIT %s")
    params.append(limit)
    with connect() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("\n".join(sql), params)
            return [dict(row) for row in cursor.fetchall()]


def sections_by_kind(claim_id: str, kinds: list[str], **filters) -> list[dict]:
    init_db()
    sql = [
        """
        SELECT DISTINCT ON (section_kind)
               chunk_id, document_id, filename, document_type, page_number, section_kind,
               section_title, body, section_body, policy_version, effective_date
        FROM chunks
        WHERE claim_id = %s AND section_kind = ANY(%s)
        """
    ]
    params: list = [claim_id, kinds]
    _filters(
        sql,
        params,
        filters.get("document_type"),
        filters.get("section_kind"),
        filters.get("policy_version"),
        filters.get("effective_date"),
    )
    sql.append("ORDER BY section_kind, page_number, length(body)")
    with connect() as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("\n".join(sql), params)
            return [dict(row) for row in cursor.fetchall()]
