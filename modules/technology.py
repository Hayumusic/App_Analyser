from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

import pandas as pd

from core.data_loader import ColumnResolver
from core.text_utils import clean_text, contains_any, split_multi_value

BUCKET_KEYWORDS = {
    "Mainframe / iSeries / AS400": ["as400", "as/400", "iseries", "i-series", "mainframe", "cobol", "rpg"],
    "Java-based Applications": ["java", "spring", "j2ee", "tomcat", "weblogic", "jboss"],
    ".NET Applications": [".net", "dotnet", "c#", "asp.net", "vb.net", "iis"],
    "SAP Ecosystem": ["sap", "s/4", "ecc", "bw", "hana", "bapi", "idoc"],
    "SaaS Applications": ["saas", "salesforce", "workday", "servicenow", "oracle cloud", "adobe", "netsuite"],
    "Cloud-native Applications": ["aws", "azure", "gcp", "lambda", "kubernetes", "eks", "aks", "cloud native", "serverless"],
    "Data Platforms": ["snowflake", "bigquery", "redshift", "databricks", "data lake", "warehouse", "etl", "analytics"],
    "Middleware / Integration Platforms": ["mulesoft", "boomi", "informatica", "kafka", "mq", "middleware", "api gateway", "esb"],
    "Database-centric Applications": ["oracle", "sql server", "mysql", "postgres", "database", "db2", "mongodb"],
    "End-user Computing Tools": ["excel", "access", "sharepoint list", "power query", "macro", "vba"],
    "Unsupported or Obsolete Technology": ["unsupported", "obsolete", "end of support", "eol", "legacy", "vb6", "lotus", "silverlight"],
}

RISK_KEYWORDS = {
    "Obsolete or unsupported technology": ["unsupported", "obsolete", "end of support", "eol", "legacy", "vb6", "lotus", "silverlight"],
    "Manual or file-based integration risk": ["manual", "file", "ftp", "sftp", "csv", "spreadsheet", "batch"],
    "Lack of API readiness": ["no api", "manual interface", "file transfer", "batch only"],
    "Security or compliance exposure": ["security", "compliance", "vulnerability", "unencrypted", "audit"],
}


def useful_text_columns(cmdb_df: pd.DataFrame) -> List[str]:
    resolver = ColumnResolver(list(cmdb_df.columns))
    return resolver.find_many_by_keywords([
        "technology", "stack", "platform", "hosting", "database", "language", "framework",
        "integration", "interface", "api", "dependency", "description", "notes", "shortcoming",
        "risk", "support", "vendor", "owner", "criticality"
    ])


def combined_app_text(row: pd.Series, columns: List[str], confluence_text: str = "", validation_context: str = "") -> str:
    parts = [clean_text(row.get(col)) for col in columns]
    parts.extend([clean_text(confluence_text), clean_text(validation_context)])
    return " | ".join([p for p in parts if p])


def classify_bucket(text: str) -> Tuple[str, str]:
    matched = []
    for bucket, keywords in BUCKET_KEYWORDS.items():
        if contains_any(text, keywords):
            matched.append(bucket)
    if not matched:
        return "Custom-built Applications", "No specific configured technology bucket matched; classified as custom/unclear based on available data."
    return " | ".join(matched), "Matched keywords in available technology/context fields."


def technology_clusters(cmdb_df: pd.DataFrame, app_labels: pd.DataFrame | None = None) -> pd.DataFrame:
    text_cols = useful_text_columns(cmdb_df)
    rows = []
    for _, row in cmdb_df.iterrows():
        text = combined_app_text(row, text_cols)
        bucket, reason = classify_bucket(text)
        rows.append({
            "Application Key": row.get("_app_key"),
            "Application Name": row.get("_app_label"),
            "Technology Stack Bucket": bucket,
            "Primary Technologies Found": text[:500] if text else "Not Available",
            "Hosting Model": _first_by_keywords(row, ["hosting", "hosted", "deployment"]),
            "Database or Data Store": _first_by_keywords(row, ["database", "data store", "db"]),
            "Support Status": _first_by_keywords(row, ["support status", "support", "lifecycle", "eol"]),
            "Vendor or Ownership": _first_by_keywords(row, ["vendor", "business owner", "technology owner", "support owner", "owner"]),
            "Why Grouped": reason,
            "Evidence Type": "Direct CMDB Evidence" if text else "Missing Evidence",
        })
    df = pd.DataFrame(rows)
    if app_labels is not None and not app_labels.empty:
        df = df.merge(app_labels[["_app_key", "Source of Truth Label", "Reliability Label"]], left_on="Application Key", right_on="_app_key", how="left").drop(columns=["_app_key"], errors="ignore")
    return df


def _first_by_keywords(row: pd.Series, keywords: Iterable[str]) -> str:
    for col in row.index:
        low = col.lower()
        if any(k in low for k in keywords):
            val = clean_text(row.get(col))
            if val:
                return val
    return "Not Available"


def detect_integrations(cmdb_df: pd.DataFrame) -> pd.DataFrame:
    resolver = ColumnResolver(list(cmdb_df.columns))
    upstream_cols = resolver.find_many_by_keywords(["upstream", "source application", "source system", "provider"])
    downstream_cols = resolver.find_many_by_keywords(["downstream", "target application", "target system", "consumer"])
    integration_cols = resolver.find_many_by_keywords(["integration", "interface", "api", "dependency", "data flow", "file transfer", "batch", "middleware", "event"])
    frequency_cols = resolver.find_many_by_keywords(["frequency", "schedule", "batch window"])
    criticality_cols = resolver.find_many_by_keywords(["criticality", "risk", "tier"])

    rows = []
    for _, row in cmdb_df.iterrows():
        app = row.get("_app_label")
        for col in upstream_cols:
            for item in split_multi_value(row.get(col)):
                rows.append({
                    "Selected Application": app,
                    "Direction": "Upstream",
                    "Connected Application or System": item,
                    "Integration Type": _first_non_empty(row, integration_cols) or "Not Available",
                    "Interface or API Name": _first_non_empty(row, integration_cols) or "Not Available",
                    "Data Object or Process": _first_by_keywords(row, ["data object", "business process", "process", "object"]),
                    "Frequency": _first_non_empty(row, frequency_cols) or "Not Available",
                    "Criticality or Risk": _first_non_empty(row, criticality_cols) or "Not Available",
                    "Evidence Type": "Direct CMDB Evidence",
                })
        for col in downstream_cols:
            for item in split_multi_value(row.get(col)):
                rows.append({
                    "Selected Application": app,
                    "Direction": "Downstream",
                    "Connected Application or System": item,
                    "Integration Type": _first_non_empty(row, integration_cols) or "Not Available",
                    "Interface or API Name": _first_non_empty(row, integration_cols) or "Not Available",
                    "Data Object or Process": _first_by_keywords(row, ["data object", "business process", "process", "object"]),
                    "Frequency": _first_non_empty(row, frequency_cols) or "Not Available",
                    "Criticality or Risk": _first_non_empty(row, criticality_cols) or "Not Available",
                    "Evidence Type": "Direct CMDB Evidence",
                })
        if not upstream_cols and not downstream_cols and integration_cols:
            details = _first_non_empty(row, integration_cols)
            if details:
                rows.append({
                    "Selected Application": app,
                    "Direction": "Unspecified",
                    "Connected Application or System": "Not Available",
                    "Integration Type": details,
                    "Interface or API Name": details,
                    "Data Object or Process": _first_by_keywords(row, ["data object", "business process", "process", "object"]),
                    "Frequency": _first_non_empty(row, frequency_cols) or "Not Available",
                    "Criticality or Risk": _first_non_empty(row, criticality_cols) or "Not Available",
                    "Evidence Type": "Direct CMDB Evidence",
                })
    if not rows:
        return pd.DataFrame(columns=[
            "Selected Application", "Direction", "Connected Application or System", "Integration Type",
            "Interface or API Name", "Data Object or Process", "Frequency", "Criticality or Risk", "Evidence Type"
        ])
    return pd.DataFrame(rows)


def _first_non_empty(row: pd.Series, columns: List[str]) -> str:
    for col in columns:
        val = clean_text(row.get(col))
        if val:
            return val
    return ""


def risk_analysis(cmdb_df: pd.DataFrame, integrations_df: pd.DataFrame | None = None, app_labels: pd.DataFrame | None = None) -> pd.DataFrame:
    text_cols = useful_text_columns(cmdb_df)
    integration_counts = {}
    if integrations_df is not None and not integrations_df.empty:
        integration_counts = integrations_df.groupby("Selected Application").size().to_dict()
    rows = []
    for _, row in cmdb_df.iterrows():
        app = row.get("_app_label")
        text = combined_app_text(row, text_cols)
        flags = []
        score = 0
        for flag, keywords in RISK_KEYWORDS.items():
            if contains_any(text, keywords):
                flags.append(flag)
                score += 2
        count = integration_counts.get(app, 0)
        if count >= 5:
            flags.append("High integration complexity")
            score += 2
        elif count >= 3:
            flags.append("Moderate integration complexity")
            score += 1
        criticality = _first_by_keywords(row, ["criticality", "business criticality", "tier"])
        if clean_text(criticality).lower() in {"critical", "high", "tier 1", "tier1", "mission critical"} and contains_any(text, ["legacy", "unsupported", "obsolete", "as400", "iseries", "mainframe"]):
            flags.append("Business-critical application using legacy technology")
            score += 3
        owner = _first_by_keywords(row, ["technology owner", "support owner", "business owner", "owner"])
        if owner == "Not Available":
            flags.append("Unclear ownership or support model")
            score += 1
        if score >= 6:
            risk = "Critical Risk"
        elif score >= 4:
            risk = "High Risk"
        elif score >= 2:
            risk = "Medium Risk"
        else:
            risk = "Low Risk"
        modernization = "Modernization Candidate" if risk in {"High Risk", "Critical Risk"} else "Future-Proof" if risk == "Low Risk" else "Monitor"
        rows.append({
            "Application Key": row.get("_app_key"),
            "Application Name": app,
            "Risk Label": risk,
            "Modernization Label": modernization,
            "Integration Count": count,
            "Risk Flags": ", ".join(flags) if flags else "None identified from available data",
            "Risk Logic": "Rule-based risk from technology keywords, support/owner fields, criticality, and integration count.",
            "Business or Operational Impact": criticality if criticality != "Not Available" else "Not Available",
            "Evidence Type": "Direct CMDB Evidence + Inferred Analysis" if text or count else "Missing Evidence",
            "Missing Data Warnings": "Not Available" if text else "Insufficient data",
        })
    df = pd.DataFrame(rows)
    if app_labels is not None and not app_labels.empty:
        df = df.merge(app_labels[["_app_key", "Source of Truth Label", "Reliability Label"]], left_on="Application Key", right_on="_app_key", how="left").drop(columns=["_app_key"], errors="ignore")
    return df
