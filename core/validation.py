from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from .data_loader import ColumnResolver, find_identity_columns
from .text_utils import clean_text, is_populated, normalize_header


def validate_cmdb(cmdb_df: pd.DataFrame, mandatory_fields: List[str]) -> Dict:
    resolver = ColumnResolver(list(cmdb_df.columns))
    field_map = {field: resolver.find_exact(field) for field in mandatory_fields}
    missing_columns = [field for field, actual in field_map.items() if actual is None]
    app_id_col, app_name_col = find_identity_columns(cmdb_df)

    rows = []
    total_fields = len(mandatory_fields)
    populated_total = 0
    possible_total = max(len(cmdb_df) * total_fields, 1)

    for idx, row in cmdb_df.iterrows():
        populated = 0
        missing_values = []
        for field in mandatory_fields:
            actual_col = field_map.get(field)
            if actual_col is None:
                missing_values.append(field)
            else:
                if is_populated(row.get(actual_col)):
                    populated += 1
                else:
                    missing_values.append(field)
        populated_total += populated
        completeness = round((populated / total_fields) * 100, 2) if total_fields else 0.0
        rows.append({
            "Application Key": row.get("_app_key", f"ROW_{idx + 1}"),
            "Application Name": row.get("_app_label", f"Unnamed Application {idx + 1}"),
            "Mandatory Fields Populated": populated,
            "Mandatory Fields Total": total_fields,
            "Completeness %": completeness,
            "Missing Mandatory Fields": ", ".join(missing_values) if missing_values else "None",
        })

    duplicate_ids = []
    duplicate_names = []
    if app_id_col:
        s = cmdb_df[app_id_col].map(clean_text)
        duplicate_ids = sorted([x for x in s[s.duplicated(keep=False)].unique().tolist() if x])
    if app_name_col:
        s = cmdb_df[app_name_col].map(lambda x: clean_text(x).lower())
        duplicate_names = sorted([x for x in s[s.duplicated(keep=False)].unique().tolist() if x])

    overall_completeness = round((populated_total / possible_total) * 100, 2) if total_fields else 0.0
    return {
        "field_map": field_map,
        "missing_columns": missing_columns,
        "app_id_col": app_id_col,
        "app_name_col": app_name_col,
        "row_results": pd.DataFrame(rows),
        "overall_completeness": overall_completeness,
        "duplicate_application_ids": duplicate_ids,
        "duplicate_application_names": duplicate_names,
    }


def validate_validation_doc(validation_df: pd.DataFrame, cmdb_df: pd.DataFrame) -> Dict:
    from .data_loader import ColumnResolver, find_identity_columns

    resolver = ColumnResolver(list(validation_df.columns))
    val_id_col = resolver.find_first(["application id", "app id", "application_id", "app_id", "application name", "app name", "name"])
    cmdb_up_to_date_col = resolver.find_first(["cmdb data up to date", "cmdb up to date", "cmdb current"])
    confluence_up_to_date_col = resolver.find_first(["confluence up to date", "documentation up to date", "docs up to date"])
    context_col = resolver.find_first(["additional context", "context", "comments", "notes", "application context"])

    cmdb_id_col, cmdb_name_col = find_identity_columns(cmdb_df)
    cmdb_keys = set(cmdb_df.get("_app_key", pd.Series(dtype=object)).map(clean_text).str.lower().tolist())
    cmdb_names = set(cmdb_df.get("_app_label", pd.Series(dtype=object)).map(clean_text).str.lower().tolist())

    matched_keys = set()
    rows = []
    invalid_yes_no = []
    unmatched = []

    for idx, row in validation_df.iterrows():
        supplied_key = clean_text(row.get(val_id_col)) if val_id_col else ""
        cmdb_flag = clean_text(row.get(cmdb_up_to_date_col)) if cmdb_up_to_date_col else ""
        conf_flag = clean_text(row.get(confluence_up_to_date_col)) if confluence_up_to_date_col else ""
        context = clean_text(row.get(context_col)) if context_col else ""
        for col_name, flag in [("CMDB Data Up to Date", cmdb_flag), ("Confluence Up to Date", conf_flag)]:
            if flag and flag.lower() not in {"yes", "no", "y", "n"}:
                invalid_yes_no.append({"Row": idx + 2, "Field": col_name, "Value": flag})
        lookup = supplied_key.lower()
        matched = lookup in cmdb_keys or lookup in cmdb_names
        if matched:
            matched_keys.add(lookup)
        else:
            unmatched.append({"Row": idx + 2, "Application ID or Name": supplied_key})
        rows.append({
            "Validation Row": idx + 2,
            "Application ID or Name": supplied_key,
            "Matched CMDB Application": "Yes" if matched else "No",
            "CMDB Data Up to Date": cmdb_flag or "Not Available",
            "Confluence Up to Date": conf_flag or "Not Available",
            "Additional Context": context or "Not Available",
        })

    apps_missing_validation = []
    for _, row in cmdb_df.iterrows():
        key = clean_text(row.get("_app_key")).lower()
        label = clean_text(row.get("_app_label")).lower()
        if key not in matched_keys and label not in matched_keys:
            apps_missing_validation.append(row.get("_app_label", row.get("_app_key")))

    return {
        "id_col": val_id_col,
        "cmdb_up_to_date_col": cmdb_up_to_date_col,
        "confluence_up_to_date_col": confluence_up_to_date_col,
        "context_col": context_col,
        "row_results": pd.DataFrame(rows),
        "invalid_yes_no": invalid_yes_no,
        "unmatched_rows": unmatched,
        "apps_missing_validation": apps_missing_validation,
    }
