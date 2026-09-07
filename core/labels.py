from __future__ import annotations

from typing import Dict, Iterable, List, Set

import pandas as pd

from .text_utils import clean_text


def map_confluence_to_apps(cmdb_df: pd.DataFrame, pdf_texts: Dict[str, str]) -> Dict[str, List[str]]:
    app_to_docs: Dict[str, List[str]] = {clean_text(row.get("_app_key")): [] for _, row in cmdb_df.iterrows()}
    combined_docs = {name: text.lower() for name, text in pdf_texts.items()}
    for _, row in cmdb_df.iterrows():
        key = clean_text(row.get("_app_key"))
        label = clean_text(row.get("_app_label"))
        needles = [x.lower() for x in [key, label] if x]
        for doc_name, text in combined_docs.items():
            if any(n and n in text for n in needles):
                app_to_docs[key].append(doc_name)
    return app_to_docs


def validation_app_keys(cmdb_df: pd.DataFrame, validation_results: Dict | None) -> Set[str]:
    if not validation_results or "row_results" not in validation_results:
        return set()
    df = validation_results["row_results"]
    keys = set()
    for _, vrow in df.iterrows():
        if vrow.get("Matched CMDB Application") != "Yes":
            continue
        supplied = clean_text(vrow.get("Application ID or Name")).lower()
        for _, row in cmdb_df.iterrows():
            if supplied in {clean_text(row.get("_app_key")).lower(), clean_text(row.get("_app_label")).lower()}:
                keys.add(clean_text(row.get("_app_key")))
    return keys


def assign_application_labels(cmdb_df: pd.DataFrame, validation_df: pd.DataFrame, confluence_map: Dict[str, List[str]], validation_keys: Set[str]) -> pd.DataFrame:
    out = cmdb_df[["_app_key", "_app_label"]].copy()
    out = out.merge(validation_df[["Application Key", "Completeness %"]], left_on="_app_key", right_on="Application Key", how="left")
    sot = []
    reliability = []
    validation_available = []
    confluence_available = []
    for _, row in out.iterrows():
        key = clean_text(row["_app_key"])
        has_conf = bool(confluence_map.get(key))
        has_val = key in validation_keys
        confluence_available.append("Yes" if has_conf else "No")
        validation_available.append("Yes" if has_val else "No")
        if has_conf and has_val:
            sot.append("Source of Truth 3")
        elif has_conf:
            sot.append("Source of Truth 2")
        else:
            sot.append("Source of Truth 1")
        completeness = float(row.get("Completeness %") or 0)
        reliability.append("High" if has_val and completeness >= 70 else "Average")
    out["Confluence Evidence Available"] = confluence_available
    out["Validation Evidence Available"] = validation_available
    out["Source of Truth Label"] = sot
    out["Reliability Label"] = reliability
    return out.drop(columns=[c for c in ["Application Key"] if c in out.columns])
