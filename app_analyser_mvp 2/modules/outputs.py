from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

import pandas as pd

from core.data_loader import ColumnResolver
from core.text_utils import clean_text, contains_any, split_multi_value, tokenize

OUTPUT_INDICATORS = [
    "report", "dashboard", "visualization", "visualisation", "api", "export", "file", "feed",
    "extract", "dataset", "data processing", "analytics", "interface", "download", "publication"
]


def output_text_columns(cmdb_df: pd.DataFrame) -> List[str]:
    resolver = ColumnResolver(list(cmdb_df.columns))
    cols = resolver.find_many_by_keywords([
        "output", "report", "dashboard", "api", "export", "file", "feed", "extract", "dataset",
        "visualization", "visualisation", "analytics", "consumer", "downstream", "description", "business function"
    ])
    return list(dict.fromkeys(cols))


def classify_output_text(text: str, output_families: Dict[str, List[str]]) -> Tuple[List[str], str, List[str]]:
    text_clean = clean_text(text).lower()
    if not text_clean:
        return ["Others"], "Low", ["Insufficient data"]
    found = []
    evidence = []
    for family, members in output_families.items():
        terms = [family] + list(members or [])
        matched_terms = [term for term in terms if term and term.lower() in text_clean]
        if matched_terms:
            found.append(family)
            evidence.extend(matched_terms[:5])
    if not found:
        if contains_any(text_clean, OUTPUT_INDICATORS):
            return ["Others"], "Low", ["Output indicator found but no configured output family matched"]
        return ["Others"], "Low", ["No configured output family or output indicator matched"]
    confidence = "High" if evidence else "Medium"
    return sorted(set(found)), confidence, sorted(set(evidence))


def application_output_details(cmdb_df: pd.DataFrame, output_families: Dict[str, List[str]], app_labels: pd.DataFrame | None = None) -> pd.DataFrame:
    cols = output_text_columns(cmdb_df)
    rows = []
    for _, row in cmdb_df.iterrows():
        pieces = [clean_text(row.get(col)) for col in cols]
        text = " | ".join([p for p in pieces if p])
        families, confidence, evidence = classify_output_text(text, output_families)
        rows.append({
            "Application Key": row.get("_app_key"),
            "Application Name": row.get("_app_label"),
            "Output Summary": text[:1000] if text else "Insufficient data",
            "Output Family Classification": ", ".join(families),
            "Key Evidence or Keywords Found": ", ".join(evidence) if evidence else "Insufficient data",
            "Consumers or Downstream Users": _first_by_keywords(row, ["consumer", "downstream", "user", "audience"]),
            "Confidence Level": confidence,
            "Why Classified": "Matched configured output family/member keywords" if families != ["Others"] else "Assigned to Others because no configured family clearly matched",
            "Direct or Inferred": "Directly found + rules-based classification" if text else "Missing Evidence",
            "Evidence Type": "Direct CMDB Evidence + Inferred Analysis" if text else "Missing Evidence",
            "Missing Data Warnings": "None" if text else "Insufficient data",
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


def output_family_clusters(details_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    family_names = sorted(set(
        fam.strip()
        for families in details_df.get("Output Family Classification", pd.Series(dtype=object)).tolist()
        for fam in clean_text(families).split(",")
        if fam.strip()
    ))
    for family in family_names:
        subset = details_df[details_df["Output Family Classification"].str.contains(family, case=False, na=False, regex=False)]
        rows.append({
            "Output Family Name": family,
            "Applications Producing This Output Family": ", ".join(subset["Application Name"].tolist()),
            "Application Count": len(subset),
            "Specific Outputs Identified": " | ".join(subset["Output Summary"].head(10).tolist()),
            "Similarity Notes": "Applications classified into the same output family using configured family/member list.",
            "Confidence Level": _rollup_confidence(subset["Confidence Level"].tolist()),
            "Evidence Type": "Direct CMDB Evidence + Inferred Analysis",
            "Source-of-Truth Labels in Cluster": ", ".join(sorted(set(subset.get("Source of Truth Label", pd.Series(dtype=object)).dropna().tolist()))) or "Not Available",
            "Reliability Labels in Cluster": ", ".join(sorted(set(subset.get("Reliability Label", pd.Series(dtype=object)).dropna().tolist()))) or "Not Available",
        })
    return pd.DataFrame(rows)


def _rollup_confidence(values: List[str]) -> str:
    if values and all(v == "High" for v in values):
        return "High"
    if values and any(v == "High" for v in values):
        return "Medium"
    return "Low"


def app_output_matrix(details_df: pd.DataFrame, output_families: Dict[str, List[str]]) -> pd.DataFrame:
    families = list(output_families.keys()) + ["Others"]
    rows = []
    for _, row in details_df.iterrows():
        assigned = {fam.strip() for fam in clean_text(row.get("Output Family Classification")).split(",") if fam.strip()}
        item = {"Application Name": row.get("Application Name")}
        for family in families:
            item[family] = "Yes" if family in assigned else "No"
        rows.append(item)
    return pd.DataFrame(rows)


def redundancy_alerts(details_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    families = sorted(set(
        fam.strip()
        for families in details_df.get("Output Family Classification", pd.Series(dtype=object)).tolist()
        for fam in clean_text(families).split(",")
        if fam.strip()
    ))
    for family in families:
        if family == "Others":
            continue
        subset = details_df[details_df["Output Family Classification"].str.contains(family, case=False, na=False, regex=False)]
        if len(subset) < 2:
            continue
        apps = subset["Application Name"].tolist()
        severity = "High" if len(subset) >= 4 else "Medium" if len(subset) == 3 else "Low"
        rows.append({
            "Applications Involved": ", ".join(apps),
            "Shared Output Family": family,
            "Similar or Duplicated Outputs": " | ".join(subset["Output Summary"].head(5).tolist()),
            "Business Impact": "Potential duplicated reporting, analytics, API, export, or data-processing capability.",
            "Redundancy Severity": severity,
            "Recommendation": "Review consumers, business process, dataset scope, and consolidation opportunity.",
            "Evidence Type": "Direct CMDB Evidence + Inferred Analysis",
            "Source of Truth Label": _mode_value(subset.get("Source of Truth Label")),
            "Reliability Label": _mode_value(subset.get("Reliability Label")),
        })
    return pd.DataFrame(rows)


def exceptions_others(details_df: pd.DataFrame) -> pd.DataFrame:
    subset = details_df[details_df["Output Family Classification"].str.contains("Others", case=False, na=False, regex=False)].copy()
    if subset.empty:
        return pd.DataFrame(columns=["Application Name", "Output Description", "Reason", "Confidence Level"])
    return subset.rename(columns={"Output Summary": "Output Description", "Why Classified": "Reason"})[[
        "Application Name", "Output Description", "Reason", "Confidence Level", "Evidence Type", "Missing Data Warnings"
    ]]


def _mode_value(series) -> str:
    if series is None or len(series) == 0:
        return "Not Available"
    mode = series.dropna().mode()
    return mode.iloc[0] if not mode.empty else "Not Available"
