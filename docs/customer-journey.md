# Customer journey — Claims Investigation Workbench

The person using this product is a claims investigator. The policyholder reports the collision and supplies documents. The workbench reads those documents, keeps conflicting statements apart, and recommends a next action. An authorised reviewer still makes any coverage, fraud, or payment decision.

The workbench is one Streamlit page at `http://localhost:8501`. The claim id in the sidebar is shared by every tab. These are the screens:

| Tab | What it is for |
| --- | --- |
| New claim | Open a claim, or load the labeled September collision pack. |
| Documents | Upload PDFs and see how each file was classified. |
| Search | Retrieve clauses with the page, the section, and the surrounding wording. |
| Evidence ledger | Read structured findings, citations, and the next action on each row. |
| Report | Read the advisory coverage note, gaps, money split, and recommended steps. |

There is no button that rejects a claim, records fraud as a determination, or authorises payment.

## Actors

| Actor | Where they appear |
| --- | --- |
| Policyholder | Outside the workbench. They report the collision and provide documents. |
| Claims intake | New claim and Documents. They open the file and load the pack. |
| Claims investigator | Search, Evidence ledger, and Report. They check citations and decide what a person must confirm. |
| Authorised reviewer | Evidence ledger and Report, read only. The decision happens in the insurer's own process. |

## September collision, used in the flows below

The labeled pack behind **Load September collision pack** contains:

- Policy schedule: period commences 15 September 2026, policy POL-88421, registration LK21 ABC.
- Policy wording: accidental collision cover, a pre-existing-damage exclusion, a before-inception exclusion, and the insured-period definition.
- Endorsement E-17: waives the before-inception exclusion for glass only. Collision damage stays subject to the insured period.
- Claim form: incident date 16 September 2026.
- Police report: incident date 12 September 2026.
- Photograph notes: bumper damage that may not match a fresh collision.
- Garage estimate: pre-existing bumper line £420.00 and collision repair £2180.00.
- Invoice: £2600.00, which matches those two lines.
- Prior claim history, the date-conflict guideline, and a scanned police supplement.

## User flows

### Policyholder

The policyholder does not sign in.

1. They report that the car was damaged in a collision on 12 September.
2. They give intake the claim form, statement, and repair documents.
3. They wait. The workbench does not send them an automated denial or payment.
4. Any later question about the date or the photographs comes from the investigator, not from the agent.

### Claims intake

Intake assembles the file and gets it into the workbench.

1. Open **New claim**.
2. Either enter the policy number and the claimed incident date and press **Create claim**, or press **Load September collision pack**.
3. The page confirms the claim id. The same id appears in the sidebar.
4. Open **Documents**.
5. For a file that was not in the pack, choose the PDFs, leave **Document type** on Auto-detect, and press **Upload and read**.
6. The table shows the file name, the detected type, the page count, and how many pages needed OCR.
7. Stop here. Intake does not decide coverage. The investigator continues on Search and Evidence ledger.

What intake should see after the September pack: 11 documents, including `policy_schedule.pdf`, `policy_wording.pdf`, `endorsement_e17.pdf`, `claim_form.pdf`, `police_report.pdf`, `garage_estimate.pdf`, and `police_supplement_scan.pdf`.

### Claims investigator

The investigator treats the ledger as the case file, not as a chat answer.

1. Confirm the claim id in the sidebar. If intake already loaded the pack, use that id. Otherwise press **Load September collision pack** on **New claim**.
2. Open **Documents** and check that the policy, claim form, police report, estimate, and invoice are listed.
3. Open **Search**. Ask `Is this collision damage covered under the policy?` and press **Search evidence**.
4. Read the passages. A coverage question also returns the exclusion, the endorsement, the insured-period definition, and the coverage wording. Each card shows the file name and page. **Surrounding clause** shows the whole section, not only the matching lines.
5. Optional checks on the same tab:
   - Document type `police_report` limits the hits to the police documents.
   - Policy version `MOT-2026.1` limits the hits to that version of the wording.
6. Open **Evidence ledger** and press **Load findings**.
7. Expect these rows for the September pack, each with a quoted line and a page:
   - Policy inception 15 September 2026, from the schedule.
   - Claim form incident date 16 September 2026.
   - Police incident date 12 September 2026.
   - An unresolved incident-date conflict that keeps both sources.
   - An unresolved note that the police date is before inception. That comparison is done in code.
   - Coverage applicability: **Pending date verification**.
   - The pre-existing-damage exclusion, the before-inception exclusion, the insured-period definition, and endorsement E-17.
   - Estimate lines £420.00 and £2180.00, kept separate.
   - Photograph notes that may not match the reported collision.
8. Open **Report** and press **Load report**.
9. The coverage sentence says coverage cannot be determined until the conflict is resolved. The financial estimate keeps the pre-existing amount separate from the collision amount. The next steps tell the investigator to confirm the date and review the photographs.
10. The report states that a person must review the file before any consequential decision. The investigator records that confirmation outside the agent, or uploads a corrected document and returns to **Documents**.

**Load Phase 0 sample rows** replaces the ledger with three illustrative rows that were not read from a PDF. Use it only to compare the old scaffold. Upload or reload the pack to get document-backed rows again.

### Authorised reviewer

The reviewer does not get a separate screen, and they do not get an approve or decline control.

1. Take the claim id from the investigator.
2. Paste it into **Claim id** in the sidebar.
3. Open **Evidence ledger** and press **Load findings**. Check that every material row they rely on has a source quote and a page.
4. Open **Report** and press **Load report**. Read the gaps and the next steps.
5. Leave the workbench. Record the coverage, fraud, or payment decision in the insurer's authorised process.
6. If the police date and the claim-form date still disagree, send the file back to the investigator. The report is not a decision.

## What the September report is for

The useful outcome on screen is a file that shows 12 September and 16 September as different statements, shows 15 September as the inception date, cites the exclusion and endorsement E-17, and asks a person to confirm the incident date before anyone treats coverage as decided.
