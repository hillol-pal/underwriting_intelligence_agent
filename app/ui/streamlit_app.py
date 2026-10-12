"""Streamlit UI for the Claims Investigation Workbench."""
import os

import httpx
import streamlit as st

API_BASE = os.environ.get("API_BASE_URL", "http://localhost:8000/api/v1")
HEALTH_URL = API_BASE.removesuffix("/api/v1") + "/health"

DOCUMENT_TYPES = [
    "Auto-detect",
    "policy_schedule",
    "policy_wording",
    "endorsement",
    "claim_form",
    "police_report",
    "photograph",
    "garage_estimate",
    "invoice",
    "claim_history",
    "guideline",
]
SECTION_KINDS = [
    "Any",
    "coverage",
    "exclusion",
    "endorsement",
    "definition",
    "schedule",
    "claim_details",
    "estimate",
    "invoice",
    "statement",
    "prior_claims",
    "guideline",
    "photograph_notes",
    "body",
]

st.set_page_config(
    page_title="Underwriting intelligence agent",
    page_icon="🛡️",
    layout="wide",
)

if "claim_id" not in st.session_state:
    st.session_state["claim_id"] = ""


def _claim_id() -> str:
    return st.session_state.get("claim_id", "").strip()


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        return response.text
    detail = payload.get("detail", response.text)
    if isinstance(detail, list):
        return "; ".join(str(item) for item in detail)
    return str(detail)


st.title("Underwriting intelligence agent")
st.caption("Claims investigation workbench. Advisory only. A person decides coverage, fraud, and payment.")

new_claim, documents, search, ledger, report = st.tabs(
    ["New claim", "Documents", "Search", "Evidence ledger", "Report"]
)

with new_claim:
    st.header("Create claim")
    st.write("Intake records the policy number and the date the policyholder gave. Reading the file starts when documents are uploaded.")
    with st.form("create_claim"):
        policy_number = st.text_input("Policy number", placeholder="POL-88421")
        incident_date = st.text_input("Claimed incident date", placeholder="12 September 2026")
        submitted = st.form_submit_button("Create claim", type="primary", icon=":material/add:")
    if submitted:
        try:
            response = httpx.post(
                f"{API_BASE}/claims",
                json={"policy_number": policy_number or None, "incident_date_claimed": incident_date or None},
                timeout=30,
            )
            if response.status_code >= 400:
                st.error(_error_detail(response))
            else:
                data = response.json()
                st.session_state["claim_id"] = data["claim"]["claim_id"]
                st.success(f"Claim created: {data['claim']['claim_id']}")
        except Exception as exc:
            st.error(f"Failed to create claim: {exc}")

    st.subheader("September collision pack")
    st.write(
        "Loads the labeled motor claim: inception on 15 September, claim form on 16 September, "
        "police report on 12 September, a pre-existing bumper line, an exclusion, and endorsement E-17."
    )
    if st.button("Load September collision pack", icon=":material/folder_open:"):
        try:
            with st.spinner("Reading the September pack"):
                response = httpx.post(f"{API_BASE}/demo/september-collision", timeout=180)
            if response.status_code >= 400:
                st.error(_error_detail(response))
            else:
                data = response.json()
                st.session_state["claim_id"] = data["claim"]["claim_id"]
                st.success(
                    f"Claim {data['claim']['claim_id']} has {data['documents']} documents and {data['findings']} ledger rows."
                )
        except Exception as exc:
            st.error(f"Failed to load the pack: {exc}")

with documents:
    st.header("Documents")
    claim_id = _claim_id()
    if not claim_id:
        st.info("Create a claim or load the September pack first.")
    else:
        st.write(f"Claim `{claim_id}`")
        with st.form("upload_documents"):
            uploads = st.file_uploader(
                "PDF documents",
                type=["pdf"],
                accept_multiple_files=True,
                help="Policy, claim form, police report, estimate, invoice, and photographs.",
            )
            chosen_type = st.selectbox("Document type", DOCUMENT_TYPES, help="Auto-detect is used for each file when more than one file is selected.")
            upload_submitted = st.form_submit_button("Upload and read", type="primary", icon=":material/upload:")
        if upload_submitted:
            if not uploads:
                st.warning("Choose at least one PDF.")
            else:
                for upload in uploads:
                    document_type = None if chosen_type == "Auto-detect" or len(uploads) > 1 else chosen_type
                    try:
                        response = httpx.post(
                            f"{API_BASE}/claims/{claim_id}/documents",
                            files={"file": (upload.name, upload.getvalue(), "application/pdf")},
                            data={"document_type": document_type} if document_type else None,
                            timeout=180,
                        )
                        if response.status_code >= 400:
                            st.error(f"{upload.name}: {_error_detail(response)}")
                        else:
                            saved = response.json()
                            st.success(
                                f"{saved['filename']} read as {saved['document_type']} "
                                f"({saved['page_count']} pages, OCR on {saved['ocr_pages']})."
                            )
                    except Exception as exc:
                        st.error(f"{upload.name}: {exc}")
        st.button("Refresh document list", icon=":material/refresh:")
        try:
            response = httpx.get(f"{API_BASE}/claims/{claim_id}/documents", timeout=30)
            if response.status_code == 200:
                rows = response.json()
                if rows:
                    st.dataframe(
                        [
                            {
                                "File": row["filename"],
                                "Type": row["document_type"],
                                "Pages": row["page_count"],
                                "OCR pages": row["ocr_pages"],
                                "Policy version": row.get("policy_version") or "",
                                "Effective date": row.get("effective_date") or "",
                            }
                            for row in rows
                        ],
                        hide_index=True,
                        width="stretch",
                        alt="Documents ingested for this claim",
                    )
                else:
                    st.info("No documents have been read for this claim.")
            else:
                st.warning(_error_detail(response))
        except Exception as exc:
            st.error(f"Could not load documents: {exc}")

with search:
    st.header("Search evidence")
    claim_id = _claim_id()
    if not claim_id:
        st.info("Create a claim or load the September pack first.")
    else:
        with st.form("search_evidence"):
            query = st.text_input("Question or clause", placeholder="Is this collision damage covered under the policy?")
            filter_type = st.selectbox("Document type", ["Any", *DOCUMENT_TYPES[1:]])
            filter_kind = st.selectbox("Section kind", SECTION_KINDS)
            policy_version = st.text_input("Policy version", placeholder="MOT-2026.1")
            effective_date = st.text_input("Effective date", placeholder="2026-09-15")
            search_submitted = st.form_submit_button("Search evidence", type="primary", icon=":material/search:")
        if search_submitted:
            if not query.strip():
                st.warning("Enter a question or a clause to search.")
            else:
                payload = {
                    "query": query.strip(),
                    "document_type": None if filter_type == "Any" else filter_type,
                    "section_kind": None if filter_kind == "Any" else filter_kind,
                    "policy_version": policy_version.strip() or None,
                    "effective_date": effective_date.strip() or None,
                    "k": 8,
                }
                try:
                    response = httpx.post(f"{API_BASE}/claims/{claim_id}/search", json=payload, timeout=60)
                    if response.status_code >= 400:
                        st.error(_error_detail(response))
                    else:
                        payload_result = response.json()
                        payload_result["_claim_id"] = claim_id
                        st.session_state["search_result"] = payload_result
                except Exception as exc:
                    st.error(f"Search failed: {exc}")
        result = st.session_state.get("search_result")
        if result and result.get("_claim_id") == _claim_id():
            if result.get("note"):
                st.info(result["note"])
            hits = result.get("hits") or []
            if not hits:
                st.warning("No passages were retrieved.")
            for hit in hits:
                with st.container(border=True):
                    st.caption(
                        f"{hit['filename']} · page {hit['page_number']} · {hit['section_kind']} · "
                        f"{', '.join(hit['matched_by'])}"
                    )
                    st.write(hit["text"])
                    with st.expander("Surrounding clause"):
                        st.write(hit["surrounding_clause"])

with ledger:
    st.header("Evidence ledger")
    claim_id = _claim_id()
    if not claim_id:
        st.info("Create a claim or load the September pack first.")
    else:
        st.write("Rows come from the documents that were read. Sample rows replace them and are not taken from a PDF.")
        with st.container(horizontal=True):
            load_findings = st.button("Load findings", type="primary", icon=":material/list:")
            load_sample = st.button("Load Phase 0 sample rows", icon=":material/science:")
        if load_sample:
            try:
                response = httpx.post(f"{API_BASE}/claims/{claim_id}/seed-example", timeout=30)
                if response.status_code >= 400:
                    st.error(_error_detail(response))
                else:
                    st.warning("Sample rows replaced the ledger. Upload documents again to read the file.")
                    load_findings = True
            except Exception as exc:
                st.error(f"Could not load sample rows: {exc}")
        if load_findings:
            try:
                response = httpx.get(f"{API_BASE}/claims/{claim_id}/findings", timeout=30)
                if response.status_code >= 400:
                    st.error(_error_detail(response))
                else:
                    st.session_state["findings"] = {"_claim_id": claim_id, "rows": response.json()}
            except Exception as exc:
                st.error(f"Could not load findings: {exc}")
        stored_findings = st.session_state.get("findings") or {}
        findings = stored_findings.get("rows", []) if stored_findings.get("_claim_id") == claim_id else []
        if findings:
            st.dataframe(
                [
                    {
                        "Fact": finding["claim_or_policy_fact"],
                        "Value": finding.get("normalized_value") or "",
                        "Status": finding["verification_status"],
                        "Page": finding.get("page_number") or "",
                        "Confidence": finding["confidence"],
                    }
                    for finding in findings
                ],
                hide_index=True,
                width="stretch",
                alt="Evidence ledger findings for this claim",
            )
            for finding in findings:
                with st.expander(f"{finding['finding_id']} — {finding['claim_or_policy_fact']}"):
                    st.write(f"Type: {finding['finding_type']}")
                    st.write(f"Status: {finding['verification_status']}")
                    if finding.get("quoted_source_text"):
                        st.write(f"Source: {finding['quoted_source_text']}")
                    if finding.get("next_action"):
                        st.write(f"Next action: {finding['next_action']}")
                    if finding.get("contradicts"):
                        st.write(f"Contradicts: {', '.join(finding['contradicts'])}")
                    if finding.get("depends_on"):
                        st.write(f"Depends on: {', '.join(finding['depends_on'])}")

with report:
    st.header("Investigation report")
    claim_id = _claim_id()
    if not claim_id:
        st.info("Create a claim or load the September pack first.")
    else:
        st.write("The report recommends a next action. It does not reject the claim or authorise payment.")
        if st.button("Load report", type="primary", icon=":material/description:"):
            try:
                response = httpx.get(f"{API_BASE}/claims/{claim_id}/report", timeout=30)
                if response.status_code >= 400:
                    st.error(_error_detail(response))
                else:
                    loaded_report = response.json()
                    loaded_report["_claim_id"] = claim_id
                    st.session_state["report"] = loaded_report
            except Exception as exc:
                st.error(f"Could not load the report: {exc}")
        loaded = st.session_state.get("report")
        if loaded and loaded.get("_claim_id") != claim_id:
            loaded = None
        if loaded:
            st.subheader("Coverage analysis")
            st.write(loaded["coverage_analysis"])
            st.subheader("Evidence gaps")
            for gap in loaded["evidence_gaps"]:
                st.write(f"- {gap}")
            st.subheader("Financial estimate")
            st.write(loaded.get("financial_estimate") or "Pending loss assessment")
            st.subheader("Recommended next steps")
            for step in loaded["recommended_next_steps"]:
                st.write(f"- {step}")
            st.info("Human review is required before any consequential decision.")

with st.sidebar:
    st.header("Claim")
    st.text_input("Claim id", key="claim_id")
    try:
        health = httpx.get(HEALTH_URL, timeout=2)
        if health.status_code == 200:
            body = health.json()
            database = body.get("database", "unknown")
            st.write(f"API: healthy. Database: {database}.")
        else:
            st.write("API: unexpected response.")
    except Exception:
        st.write(f"API: not reachable at {HEALTH_URL}.")
    st.caption("Phase 1 reads PDFs into the evidence ledger and searches clauses with page citations.")
