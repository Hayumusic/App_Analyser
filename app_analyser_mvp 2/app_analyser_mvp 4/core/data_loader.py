from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

from .text_utils import clean_text, normalize_header, split_multi_value


@dataclass
class ColumnResolver:
    columns: List[str]

    def __post_init__(self):
        self.normalized_to_original = {normalize_header(c): c for c in self.columns}
        self.original_to_normalized = {c: normalize_header(c) for c in self.columns}

    def find_exact(self, name: str) -> Optional[str]:
        return self.normalized_to_original.get(normalize_header(name))

    def find_first(self, candidates: Iterable[str]) -> Optional[str]:
        for candidate in candidates:
            exact = self.find_exact(candidate)
            if exact:
                return exact
        normalized_candidates = [normalize_header(c) for c in candidates]
        for col in self.columns:
            norm = normalize_header(col)
            for candidate in normalized_candidates:
                if candidate and (candidate == norm or candidate in norm or norm in candidate):
                    return col
        return None

    def find_many_by_keywords(self, keywords: Iterable[str]) -> List[str]:
        normalized_keywords = [normalize_header(k) for k in keywords]
        matches = []
        for col in self.columns:
            norm = normalize_header(col)
            if any(k in norm for k in normalized_keywords if k):
                matches.append(col)
        return matches


def load_excel(uploaded_file) -> pd.DataFrame:
    df = pd.read_excel(uploaded_file, sheet_name=0, dtype=object)
    df = df.dropna(how="all")
    df.columns = [clean_text(c) or f"Unnamed_{i+1}" for i, c in enumerate(df.columns)]
    return df


def read_mandatory_fields_config(uploaded_file) -> List[str]:
    df = load_excel(uploaded_file)
    if df.empty:
        return []
    resolver = ColumnResolver(list(df.columns))
    field_col = resolver.find_first([
        "mandatory field", "mandatory_field", "cmdb field", "cmdb_field", "field name", "field_name",
        "attribute", "attribute name", "column", "column name", "field"
    ]) or df.columns[0]
    fields = []
    for value in df[field_col].tolist():
        text = clean_text(value)
        if text:
            fields.append(text)
    return list(dict.fromkeys(fields))


def read_output_family_config(uploaded_file) -> Dict[str, List[str]]:
    df = load_excel(uploaded_file)
    if df.empty:
        return {}
    resolver = ColumnResolver(list(df.columns))
    family_col = resolver.find_first(["output family", "output_family", "family", "category", "output category"]) or df.columns[0]
    member_col = resolver.find_first([
        "family member", "family members", "output family member", "output_family_member",
        "member", "members", "keywords", "output type", "output"
    ])
    result: Dict[str, List[str]] = {}
    for _, row in df.iterrows():
        family = clean_text(row.get(family_col))
        if not family:
            continue
        if family not in result:
            result[family] = []
        if member_col and member_col != family_col:
            for member in split_multi_value(row.get(member_col)):
                if member and member not in result[family]:
                    result[family].append(member)
    return result


def find_identity_columns(df: pd.DataFrame) -> Tuple[Optional[str], Optional[str]]:
    resolver = ColumnResolver(list(df.columns))
    app_id_col = resolver.find_first([
        "application id", "application_id", "app id", "app_id", "application identifier", "ci id", "cmdb id"
    ])
    app_name_col = resolver.find_first([
        "application name", "application_name", "app name", "app_name", "name", "system name", "service name"
    ])
    return app_id_col, app_name_col


def add_row_key(df: pd.DataFrame) -> pd.DataFrame:
    app_id_col, app_name_col = find_identity_columns(df)
    out = df.copy()
    keys = []
    labels = []
    for idx, row in out.iterrows():
        app_id = clean_text(row.get(app_id_col)) if app_id_col else ""
        app_name = clean_text(row.get(app_name_col)) if app_name_col else ""
        if app_id:
            keys.append(app_id)
        elif app_name:
            keys.append(app_name)
        else:
            keys.append(f"ROW_{idx + 1}")
        labels.append(app_name or app_id or f"Unnamed Application {idx + 1}")
    out["_app_key"] = keys
    out["_app_label"] = labels
    return out
