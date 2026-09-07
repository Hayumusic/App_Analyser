# App Analyser MVP

A local, upload-driven MVP for CMDB-first enterprise application analysis.

The app does not include demo data and does not generate dummy data. It only analyses files uploaded by the user during runtime.

## What is included

- Local Streamlit web app
- CMDB Excel upload and validation
- CMDB mandatory-fields configuration upload
- Output-family configuration upload
- Optional Confluence PDF upload
- Optional team validation Excel upload
- Optional CloudWatch Excel upload
- Source-of-truth labels
- Reliability labels
- Evidence and missing-data warnings
- CSV and JSON exports
- Three independent analysis modules:
  - Application Similarity and Redundancy Analysis
  - Technology and Integration Visualization
  - Application Outputs Analysis

## Folder structure

```text
app_analyser_mvp/
  app.py
  requirements.txt
  README.md
  core/
    data_loader.py
    exports.py
    labels.py
    pdf_loader.py
    text_utils.py
    validation.py
  modules/
    similarity.py
    technology.py
    outputs.py
```

## Install and run

From the `app_analyser_mvp` folder:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

## Required uploads

The app will not start analysis until these are loaded:

1. CMDB Excel file
2. CMDB mandatory-fields configuration Excel file
3. Output-family configuration Excel file

### CMDB mandatory-fields config

Use one column containing mandatory CMDB field names. Supported column names include:

- `Mandatory Field`
- `CMDB Field`
- `Field Name`
- `Attribute`
- `Column Name`

If none of these names are found, the app uses the first column.

### Output-family config

Recommended columns:

- `Output Family`
- `Family Member`

Each row can define one output family member. Multiple members can also be comma-separated in the member column.

Example structure only:

| Output Family | Family Member |
| --- | --- |
| Reports | report |
| Reports | scheduled report |
| Dashboards | dashboard |

## Optional uploads

### Confluence PDFs

Used to detect whether Confluence evidence exists for an application by matching application ID or application name in extracted PDF text.

### Team validation Excel

Minimum expected fields:

- `Application ID` or `Application Name`
- `CMDB Data Up to Date`
- `Confluence Up to Date`
- `Additional Context`

The app validates Yes/No fields, flags unmatched rows, and flags CMDB applications missing validation records.

### CloudWatch Excel reports

Accepted and stored as optional operational input. In this MVP, CloudWatch does not change the Source of Truth label. Additional CloudWatch-specific enrichment rules can be added later once the CloudWatch export schema is known.

## Source-of-truth rules

| Label | Condition |
| --- | --- |
| Source of Truth 1 | CMDB only |
| Source of Truth 2 | CMDB + Confluence |
| Source of Truth 3 | CMDB + Confluence + Team Validation Document |

CMDB is always mandatory. CloudWatch is enrichment-only in this MVP.

## Reliability rules

| Reliability | Condition |
| --- | --- |
| High | Validation document is available and mandatory CMDB field completeness is at least 70% |
| Average | Validation document is missing or mandatory CMDB field completeness is below 70% |

## Module 1: Application Similarity and Redundancy

The module compares applications using configurable field mapping and weights.

Default weights:

- Business use case: 30%
- Business function: 30%
- Capability: 30%
- Supported process: 10%

Outputs:

- App-to-app heatmap
- Similar applications panel
- Top-5 similar applications list
- Similarity cluster network
- Redundancy alerts
- Direct comparison card
- Exportable CSV

Current MVP note: direct comparison is dropdown-based. Drag-and-drop comparison can be added later with a custom Streamlit component.

## Module 2: Technology and Integration Visualization

The module detects integration-related columns and technology-related fields from CMDB.

Outputs:

- Application integration flow map
- Portfolio integration map where a portfolio field exists
- Technology-stack cluster view
- Obsolete technology dashboard
- Risk heatmap
- Modernization priority matrix
- Exportable CSVs

Missing integration details are shown as `Not Available` or `Insufficient data`.

## Module 3: Application Outputs Analysis

The module classifies application outputs using the uploaded output-family configuration.

Outputs:

- Output family clusters
- App vs output family matrix
- Redundancy alerts
- Output details
- Exceptions / Others
- Exportable CSVs

If no configured output family clearly matches, the output is assigned to `Others`.

## Anti-hallucination behavior

The app is designed to:

- Use uploaded data only
- Show missing data instead of guessing
- Mark weak findings as low confidence
- Show evidence type and missing-data warnings
- Keep rules configurable in the UI or upload files where feasible

## Known MVP limitations

- PDF extraction quality depends on the PDF text layer. Scanned PDFs may need OCR, which is not included.
- CloudWatch enrichment is schema-light until the exact report columns are known.
- Drag-and-drop comparison is represented by dropdown-based direct comparison in this MVP.
- Risk and technology bucket rules are intentionally simple and can be expanded in `modules/technology.py`.
- Similarity uses token/Jaccard-style comparison and configurable weights; enterprise taxonomy matching can be added later.
