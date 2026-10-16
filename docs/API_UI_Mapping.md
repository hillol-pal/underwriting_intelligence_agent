# API and UI mapping

Streamlit calls the API at `http://localhost:8000/api/v1` unless `API_BASE_URL` is set. The API process must be on that same port:

```bash
uvicorn app.main:app --reload --port 8000
```

`/health` and `/` are on the API host, not under `/api/v1`. Opening `http://localhost:8000/` returns the service index. Opening a path that does not exist returns 404.

| Tab | User action | Control | Method | Path | What is sent |
| --- | --- | --- | --- | --- | --- |
| New claim | Create claim | Form button: Create claim | POST | /claims | JSON: `policy_number`, `incident_date_claimed` |
| New claim | Load demo pack | Button: Load September collision pack | POST | /demo/september-collision | Creates the claim and ingests the labeled document pack. Timeout 180s |
| Documents | Upload PDFs | Form button: Upload and read | POST | /claims/{claim_id}/documents | Multipart file, plus optional `document_type` |
| Documents | Refresh list | Button: Refresh document list | GET | /claims/{claim_id}/documents | Loads ingested documents into the table |
| Search | Search evidence | Form button: Search evidence | POST | /claims/{claim_id}/search | JSON: `query`, `document_type`, `section_kind`, `policy_version`, `effective_date`, `k` |
| Evidence ledger | Load findings | Button: Load findings | GET | /claims/{claim_id}/findings | Returns evidence ledger rows |
| Evidence ledger | Run investigation | Button: Run investigation | POST | /claims/{claim_id}/investigate | Starts the supervisor. Client timeout 180s |
| Evidence ledger | Load sample data | Button: Load Phase 0 sample rows | POST | /claims/{claim_id}/seed-example | Replaces the ledger with sample rows. No PDF |
| Report | Load report | Button: Load report | GET | /claims/{claim_id}/report | Returns the advisory investigation report |
| Report | Run caption | Called by Load report | GET | /claims/{claim_id}/investigation | Latest supervisor run. A 404 leaves the Phase 1 caption |
| Sidebar | Health check | Page load | GET | /health | API and database status. Not under `/api/v1` |

The same rows as CSV:

```csv
tab,user_action,control,method,path,what_is_sent
New claim,Create claim,Form button: Create claim,POST,/claims,"JSON: policy_number, incident_date_claimed"
New claim,Load demo pack,Button: Load September collision pack,POST,/demo/september-collision,Creates the claim and ingests the labeled document pack. Timeout 180s
Documents,Upload PDFs,Form button: Upload and read,POST,/claims/{claim_id}/documents,"Multipart file, plus optional document_type"
Documents,Refresh list,Button: Refresh document list,GET,/claims/{claim_id}/documents,Loads ingested documents into the table
Search,Search evidence,Form button: Search evidence,POST,/claims/{claim_id}/search,"JSON: query, document_type, section_kind, policy_version, effective_date, k"
Evidence ledger,Load findings,Button: Load findings,GET,/claims/{claim_id}/findings,Returns evidence ledger rows
Evidence ledger,Run investigation,Button: Run investigation,POST,/claims/{claim_id}/investigate,Starts the supervisor. Client timeout 180s
Evidence ledger,Load sample data,Button: Load Phase 0 sample rows,POST,/claims/{claim_id}/seed-example,Replaces the ledger with sample rows. No PDF
Report,Load report,Button: Load report,GET,/claims/{claim_id}/report,Returns the advisory investigation report
Report,Run caption,Called by Load report,GET,/claims/{claim_id}/investigation,Latest supervisor run. A 404 leaves the Phase 1 caption
Sidebar,Health check,Page load,GET,/health,API and database status. Not under /api/v1
```

## Order of calls

| Step | What happens | Calls |
| --- | --- | --- |
| 1 | Create a claim | `POST /claims` or `POST /demo/september-collision` |
| 2 | Read documents | `POST /claims/{id}/documents`, then `GET /claims/{id}/documents` |
| 3 | Search the file | `POST /claims/{id}/search` |
| 4 | Investigate | `POST /claims/{id}/investigate`, then `GET /claims/{id}/findings` and `GET /claims/{id}/report` |
| 5 | Read the run | `GET /claims/{id}/investigation` |

Findings, the report, and the investigation run are separate reads. The UI does not grant cover, decide fraud, or authorise payment.
