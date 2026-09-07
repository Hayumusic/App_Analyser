from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

import networkx as nx
import pandas as pd

from core.text_utils import clean_text, jaccard, tokenize

DEFAULT_WEIGHTS = {
    "Business Use Case": 0.30,
    "Business Function": 0.30,
    "Capability": 0.30,
    "Supported Process": 0.10,
}

BUCKETS = [
    (80, 100, "High Overlap"),
    (50, 79.999, "Medium Overlap"),
    (20, 49.999, "Low Overlap"),
    (0, 19.999, "Unique"),
]


def redundancy_bucket(score: float) -> str:
    for lo, hi, label in BUCKETS:
        if lo <= score <= hi:
            return label
    return "Unique"


def calculate_similarity(cmdb_df: pd.DataFrame, field_map: Dict[str, str], weights: Dict[str, float] | None = None) -> pd.DataFrame:
    weights = weights or DEFAULT_WEIGHTS
    rows = []
    apps = cmdb_df.reset_index(drop=True)
    for i in range(len(apps)):
        for j in range(len(apps)):
            app_a = apps.iloc[i]
            app_b = apps.iloc[j]
            if i == j:
                score = 100.0
                reason = "Same application"
                shared_notes = {logical: "Self comparison" for logical in field_map}
                missing = []
            else:
                weighted_score = 0.0
                weight_total = 0.0
                reason_parts = []
                shared_notes = {}
                missing = []
                for logical, col in field_map.items():
                    weight = float(weights.get(logical, 0.0))
                    if not col or col not in cmdb_df.columns or weight <= 0:
                        missing.append(logical)
                        continue
                    tokens_a = tokenize(app_a.get(col))
                    tokens_b = tokenize(app_b.get(col))
                    if not tokens_a or not tokens_b:
                        missing.append(logical)
                        continue
                    field_score = jaccard(tokens_a, tokens_b) * 100
                    shared = sorted(tokens_a & tokens_b)
                    shared_notes[logical] = ", ".join(shared[:10]) if shared else "No shared values found"
                    if shared:
                        reason_parts.append(f"{logical}: {', '.join(shared[:5])}")
                    weighted_score += field_score * weight
                    weight_total += weight
                score = round(weighted_score / weight_total, 2) if weight_total else 0.0
                reason = "; ".join(reason_parts) if reason_parts else "Insufficient data" if missing else "No meaningful overlap found"
            rows.append({
                "Source Application Key": app_a.get("_app_key"),
                "Source Application": app_a.get("_app_label"),
                "Compared Application Key": app_b.get("_app_key"),
                "Compared Application": app_b.get("_app_label"),
                "Overlap %": score,
                "Redundancy Bucket": redundancy_bucket(score),
                "Shared Business Functions": shared_notes.get("Business Function", "Insufficient data"),
                "Shared Capabilities": shared_notes.get("Capability", "Insufficient data"),
                "Similarity Reason": reason,
                "Evidence Fields Used": ", ".join([v for v in field_map.values() if v]),
                "Missing Data Warnings": ", ".join(sorted(set(missing))) if i != j and missing else "None",
                "Analysis Type": "Direct CMDB Evidence + Inferred Analysis",
            })
    return pd.DataFrame(rows)


def top_n_similar(similarity_df: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    df = similarity_df[similarity_df["Source Application Key"] != similarity_df["Compared Application Key"]].copy()
    df = df.sort_values(["Source Application", "Overlap %"], ascending=[True, False])
    df["Rank"] = df.groupby("Source Application")["Overlap %"].rank(method="first", ascending=False).astype(int)
    cols = [
        "Source Application", "Rank", "Compared Application", "Overlap %", "Redundancy Bucket",
        "Shared Capabilities", "Similarity Reason", "Evidence Fields Used", "Missing Data Warnings",
        "Source Source-of-Truth Label", "Source Reliability Label",
        "Compared Source-of-Truth Label", "Compared Reliability Label",
    ]
    return df[df["Rank"] <= n][[c for c in cols if c in df.columns]]


def similar_apps_panel(similarity_df: pd.DataFrame, selected_apps: List[str], threshold: float = 5.0) -> pd.DataFrame:
    if not selected_apps:
        return pd.DataFrame()
    df = similarity_df[
        (similarity_df["Source Application"].isin(selected_apps))
        & (similarity_df["Source Application Key"] != similarity_df["Compared Application Key"])
        & (similarity_df["Overlap %"] > threshold)
    ].copy()
    return df.sort_values(["Source Application", "Overlap %"], ascending=[True, False])


def create_clusters(similarity_df: pd.DataFrame, threshold: float = 50.0) -> pd.DataFrame:
    graph = nx.Graph()
    for _, row in similarity_df.iterrows():
        a = row["Source Application"]
        b = row["Compared Application"]
        if a == b:
            graph.add_node(a)
        elif float(row["Overlap %"]) >= threshold:
            graph.add_edge(a, b, weight=float(row["Overlap %"]))
    clusters = []
    for idx, component in enumerate(nx.connected_components(graph), start=1):
        apps = sorted(component)
        sub_edges = []
        for a in apps:
            for b in apps:
                if a >= b:
                    continue
                match = similarity_df[(similarity_df["Source Application"] == a) & (similarity_df["Compared Application"] == b)]
                if not match.empty:
                    sub_edges.append(float(match.iloc[0]["Overlap %"]))
        avg_score = round(sum(sub_edges) / len(sub_edges), 2) if sub_edges else 100.0 if len(apps) == 1 else 0.0
        risk = "High" if avg_score >= 80 and len(apps) > 1 else "Medium" if avg_score >= 50 and len(apps) > 1 else "Low"
        cluster_rows = similarity_df[similarity_df["Source Application"].isin(apps)]
        sot_labels = sorted(set(cluster_rows.get("Source Source-of-Truth Label", pd.Series(dtype=object)).dropna().tolist()))
        reliability_labels = sorted(set(cluster_rows.get("Source Reliability Label", pd.Series(dtype=object)).dropna().tolist()))
        clusters.append({
            "Cluster Name": f"Similarity Cluster {idx}",
            "Applications in Cluster": ", ".join(apps),
            "Application Count": len(apps),
            "Average Overlap %": avg_score,
            "Potential Redundancy Risk": risk,
            "Why Clustered": "Applications connected by overlap threshold" if len(apps) > 1 else "Standalone application",
            "Evidence Type": "Inferred Analysis",
            "Source-of-Truth Labels in Cluster": ", ".join(sot_labels) if sot_labels else "Not Available",
            "Reliability Labels in Cluster": ", ".join(reliability_labels) if reliability_labels else "Not Available",
        })
    return pd.DataFrame(clusters)


def redundancy_alerts(similarity_df: pd.DataFrame, owner_col_values: Dict[str, str] | None = None) -> pd.DataFrame:
    rows = []
    deduped = similarity_df[similarity_df["Source Application"] < similarity_df["Compared Application"]].copy()
    for _, row in deduped.iterrows():
        score = float(row["Overlap %"])
        if score >= 80:
            severity = "High"
            reason = "High overlap between applications"
        elif score >= 50 and row.get("Shared Capabilities") not in {"", "No shared values found", "Insufficient data"}:
            severity = "Medium"
            reason = "Multiple applications share capabilities"
        else:
            continue
        rows.append({
            "Applications Involved": f"{row['Source Application']} | {row['Compared Application']}",
            "Overlap %": score,
            "Severity": severity,
            "Reason for Alert": reason,
            "Similarity Reason": row.get("Similarity Reason", "Insufficient data"),
            "Recommended Action": "Review ownership, usage, roadmap, and retirement/consolidation opportunity.",
            "Evidence Fields Used": row.get("Evidence Fields Used", "Not Available"),
            "Evidence Type": row.get("Analysis Type", "Inferred Analysis"),
            "Missing Data Warnings": row.get("Missing Data Warnings", "None"),
            "Source Application SoT": row.get("Source Source-of-Truth Label", "Not Available"),
            "Source Application Reliability": row.get("Source Reliability Label", "Not Available"),
            "Compared Application SoT": row.get("Compared Source-of-Truth Label", "Not Available"),
            "Compared Application Reliability": row.get("Compared Reliability Label", "Not Available"),
        })
    return pd.DataFrame(rows)


def matrix_for_heatmap(similarity_df: pd.DataFrame) -> pd.DataFrame:
    return similarity_df.pivot(index="Source Application", columns="Compared Application", values="Overlap %").fillna(0)
