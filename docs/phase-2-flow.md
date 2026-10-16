# Phase 2 flow — supervisor, specialists, and the ledger

The investigator asks for a run. Extraction has already written the ledger. The supervisor delegates four read-only specialists. Code checks every quote, date, and amount before a specialist row is stored. The workbench never grants cover, decides fraud, or authorises payment.

`INVESTIGATION_AGENT_ENABLED` defaults to false. With the flag off, `POST /claims/{id}/investigate` only marks the claim `pending_review` and adds `supervisor: disabled`.

## Run path

```mermaid
flowchart TD
    subgraph client [Workbench]
        UI[Streamlit ledger and report]
    end
    subgraph api [FastAPI]
        Route["POST /claims/{id}/investigate"]
        RunGet["GET /claims/{id}/investigation"]
    end
    subgraph service [InvestigationService]
        Run[run_investigation]
        Recompute["_recompute / extract_findings"]
    end
    subgraph agent [app/agents]
        Plan[build_investigation_plan]
        Sup[InvestigationSupervisor]
        Graph["create_deep_agent supervisor"]
        Policy[policy-analyst]
        Evidence[evidence-analyst]
        Contra[contradiction-analyst]
        Loss[loss-assessor]
        Map[mapper]
    end
    subgraph data [PostgreSQL]
        Pages[pages and chunks]
        Findings[findings]
        Runs[investigation_runs]
    end

    UI --> Route
    UI --> RunGet
    Route --> Run
    Run --> Recompute
    Recompute --> Findings
    Run --> Plan
    Plan --> Runs
    Run --> Sup
    Sup --> Graph
    Graph --> Policy
    Graph --> Evidence
    Graph --> Contra
    Graph --> Loss
    Policy --> Pages
    Evidence --> Pages
    Contra --> Findings
    Loss --> Pages
    Graph --> Map
    Map --> Findings
    Map --> Runs
```

## One investigate call

```mermaid
sequenceDiagram
    participant UI as Streamlit
    participant API as Investigate route
    participant Svc as InvestigationService
    participant DB as store
    participant Sup as InvestigationSupervisor
    participant Graph as create_deep_agent
    participant Sp as Specialist
    participant Map as mapper

    UI->>API: POST /claims/{id}/investigate
    API->>Svc: to_thread run_investigation
    Svc->>DB: claim, pages, findings
    alt flag off or no pages
        Svc->>DB: status pending_review
        Svc-->>UI: supervisor disabled or skipped
    else flag on
        Svc->>DB: snapshot status, unique insert run running
        Svc->>Sup: plan_and_investigate
        Sup->>Graph: invoke plan JSON
        loop one task call per ready specialist
            Graph->>Sp: description and subagent_type
            Sp->>DB: read-only search, pages, ledger, dates, money
            Sp-->>Graph: ToolMessage schema JSON
        end
        Graph-->>Sup: messages
        Sup->>Map: parse ToolMessages, check quotes, dates, money
        Map->>DB: re-read extraction ids
        alt extraction ids changed
            Svc->>DB: failed ledger_changed, restore status
        else ids unchanged
            Map->>DB: insert origin specialist
            Svc->>DB: pending_review
        end
        Svc-->>UI: run_id and step statuses
    end
    UI->>API: GET findings and GET investigation
```

## What the code decides

```mermaid
flowchart LR
    subgraph model [Model may propose]
        Quote[A quote and a page]
        Amount[An amount string copied from the page]
        Date[A date string copied from the page]
    end
    subgraph code [Code decides]
        Q[quote_supported on the full page]
        D[parse_display_date and compare_dates]
        M[Decimal via parse_gbp and format_gbp]
        L[Decision-language filter]
    end
    subgraph ledger [Ledger]
        Fact[origin specialist Finding]
        Gap[gap row when the check fails]
    end
    Quote --> Q
    Date --> D
    Amount --> M
    Quote --> L
    Q --> Fact
    D --> Fact
    M --> Fact
    Q --> Gap
    L --> Gap
```

Search still embeds the query with the Phase 1 embedding path. That path is not the chat model, and the `chunks.embedding` column stays `vector(256)`.

A second investigate while a running row is younger than 15 minutes returns HTTP 409. Upload, recompute, and the sample-row action do the same, and they do not delete the ledger. A running row older than 15 minutes is marked `failed` with `error=superseded` in the same transaction as the new insert.

`DeadlineMiddleware` stops the next model call 180 seconds after the run starts. It does not cancel an OpenAI call that has already started. That call is bounded by a 60-second timeout. The route's `asyncio.wait_for` returns HTTP 504 to the browser and does not kill the worker thread. The thread still writes a terminal run status.
