from __future__ import annotations

import io
import json
from typing import Dict, List

import networkx as nx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core.data_loader import (
    ColumnResolver,
    add_row_key,
    find_identity_columns,
    load_excel,
    read_mandatory_fields_config,
    read_output_family_config,
)
from core.exports import df_to_csv_bytes, object_to_json_bytes
from core.labels import assign_application_labels, map_confluence_to_apps, validation_app_keys
from core.pdf_loader import extract_pdf_texts
from core.text_utils import clean_text
from core.validation import validate_cmdb, validate_validation_doc
from modules import outputs as outputs_module
from modules import similarity as similarity_module
from modules import technology as technology_module

st.set_page_config(page_title="App Analyser MVP", layout="wide", page_icon="AA")


def init_state():
    defaults = {
        "cmdb_df": None,
        "mandatory_fields": [],
        "output_families": {},
        "validation_results": None,
        "cmdb_validation": None,
        "app_labels": pd.DataFrame(),
        "confluence_texts": {},
        "confluence_map": {},
        "cloudwatch_dfs": {},
        "similarity_results": pd.DataFrame(),
        "tech_clusters": pd.DataFrame(),
        "integrations": pd.DataFrame(),
        "tech_risks": pd.DataFrame(),
        "output_details": pd.DataFrame(),
        "output_clusters": pd.DataFrame(),
        "output_matrix": pd.DataFrame(),
        "output_alerts": pd.DataFrame(),
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def app_ready() -> bool:
    return (
        st.session_state.cmdb_df is not None
        and bool(st.session_state.mandatory_fields)
        and bool(st.session_state.output_families)
        and st.session_state.cmdb_validation is not None
    )


def status_card(label: str, value: str, help_text: str = ""):
    st.metric(label, value, help=help_text or None)


def upload_panel():
    st.sidebar.header("Input Uploads")
    cmdb_file = st.sidebar.file_uploader("CMDB Excel - mandatory", type=["xlsx", "xls"], key="cmdb_upload")
    mandatory_file = st.sidebar.file_uploader("CMDB mandatory-fields config - mandatory", type=["xlsx", "xls"], key="mandatory_upload")
    output_family_file = st.sidebar.file_uploader("Output family config - mandatory", type=["xlsx", "xls"], key="output_family_upload")

    st.sidebar.divider()
    confluence_files = st.sidebar.file_uploader("Confluence PDF exports - optional", type=["pdf"], accept_multiple_files=True, key="conf_upload")
    validation_file = st.sidebar.file_uploader("Team validation document - optional", type=["xlsx", "xls"], key="validation_upload")
    cloudwatch_files = st.sidebar.file_uploader("CloudWatch Excel reports - optional", type=["xlsx", "xls"], accept_multiple_files=True, key="cloudwatch_upload")

    process = st.sidebar.button("Load and validate inputs", type="primary")
    if process:
        load_inputs(cmdb_file, mandatory_file, output_family_file, confluence_files, validation_file, cloudwatch_files)


def load_inputs(cmdb_file, mandatory_file, output_family_file, confluence_files, validation_file, cloudwatch_files):
    if not cmdb_file or not mandatory_file or not output_family_file:
        st.sidebar.error("Upload CMDB, mandatory-fields config, and output-family config before analysis.")
        return
    try:
        cmdb_df = add_row_key(load_excel(cmdb_file))
        mandatory_fields = read_mandatory_fields_config(mandatory_file)
        output_families = read_output_family_config(output_family_file)
        if not mandatory_fields:
            st.sidebar.error("Mandatory-fields config did not contain any fields.")
            return
        if not output_families:
            st.sidebar.error("Output-family config did not contain any output families.")
            return
        cmdb_validation = validate_cmdb(cmdb_df, mandatory_fields)

        confluence_texts = extract_pdf_texts(confluence_files) if confluence_files else {}
        confluence_map = map_confluence_to_apps(cmdb_df, confluence_texts) if confluence_texts else {clean_text(r.get("_app_key")): [] for _, r in cmdb_df.iterrows()}

        validation_results = None
        val_keys = set()
        if validation_file:
            validation_df = load_excel(validation_file)
            validation_results = validate_validation_doc(validation_df, cmdb_df)
            val_keys = validation_app_keys(cmdb_df, validation_results)

        cloudwatch_dfs = {}
        if cloudwatch_files:
            for f in cloudwatch_files:
                cloudwatch_dfs[f.name] = load_excel(f)

        labels = assign_application_labels(
            cmdb_df=cmdb_df,
            validation_df=cmdb_validation["row_results"],
            confluence_map=confluence_map,
            validation_keys=val_keys,
        )

        st.session_state.cmdb_df = cmdb_df
        st.session_state.mandatory_fields = mandatory_fields
        st.session_state.output_families = output_families
        st.session_state.cmdb_validation = cmdb_validation
        st.session_state.validation_results = validation_results
        st.session_state.confluence_texts = confluence_texts
        st.session_state.confluence_map = confluence_map
        st.session_state.cloudwatch_dfs = cloudwatch_dfs
        st.session_state.app_labels = labels
        clear_module_results()
        st.sidebar.success("Inputs loaded and CMDB validation completed.")
    except Exception as exc:
        st.sidebar.error(f"Could not load inputs: {exc}")


def clear_module_results():
    for key in [
        "similarity_results", "tech_clusters", "integrations", "tech_risks", "output_details",
        "output_clusters", "output_matrix", "output_alerts"
    ]:
        st.session_state[key] = pd.DataFrame()


def run_header():
    st.title("App Analyser MVP")
    st.caption("Local, CMDB-first enterprise application analysis. No dummy data is generated; analysis uses only uploaded inputs and configured rules.")

    if not app_ready():
        st.info("Upload the CMDB Excel, CMDB mandatory-fields configuration, and output-family configuration, then click 'Load and validate inputs'.")
    else:
        cmdb = st.session_state.cmdb_df
        validation = st.session_state.cmdb_validation
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            status_card("Applications", str(len(cmdb)))
        with c2:
            status_card("CMDB completeness", f"{validation['overall_completeness']}%")
        with c3:
            status_card("Mandatory fields", str(len(st.session_state.mandatory_fields)))
        with c4:
            status_card("Output families", str(len(st.session_state.output_families)))


def validation_tab():
    st.header("1. CMDB Validation and Source Labels")
    if not app_ready():
        st.warning("Required inputs are not loaded yet.")
        return
    validation = st.session_state.cmdb_validation
    cmdb = st.session_state.cmdb_df

    st.subheader("Mandatory field mapping")
    mapping_df = pd.DataFrame([
        {"Configured Mandatory Field": k, "Matched CMDB Column": v or "Missing column"}
        for k, v in validation["field_map"].items()
    ])
    st.dataframe(mapping_df, use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Completeness by application")
        st.dataframe(validation["row_results"], use_container_width=True)
        st.download_button("Download CMDB completeness CSV", df_to_csv_bytes(validation["row_results"]), "cmdb_completeness.csv", "text/csv")
    with col2:
        st.subheader("Validation issues")
        if validation["missing_columns"]:
            st.error("Missing configured mandatory CMDB columns: " + ", ".join(validation["missing_columns"]))
        else:
            st.success("All configured mandatory fields were found in the CMDB file.")
        if validation["duplicate_application_ids"]:
            st.warning("Duplicate application IDs: " + ", ".join(validation["duplicate_application_ids"]))
        if validation["duplicate_application_names"]:
            st.warning("Duplicate application names: " + ", ".join(validation["duplicate_application_names"]))
        if not validation["duplicate_application_ids"] and not validation["duplicate_application_names"]:
            st.success("No duplicate application IDs or names detected from available identity columns.")

    st.subheader("Source-of-truth and reliability labels")
    st.dataframe(st.session_state.app_labels, use_container_width=True)

    if st.session_state.validation_results:
        st.subheader("Team validation document checks")
        vr = st.session_state.validation_results
        st.dataframe(vr["row_results"], use_container_width=True)
        if vr["invalid_yes_no"]:
            st.warning("Invalid Yes/No values found in validation document.")
            st.dataframe(pd.DataFrame(vr["invalid_yes_no"]), use_container_width=True)
        if vr["unmatched_rows"]:
            st.warning("Validation rows not matched to CMDB applications.")
            st.dataframe(pd.DataFrame(vr["unmatched_rows"]), use_container_width=True)
        if vr["apps_missing_validation"]:
            st.info(f"Applications missing validation records: {len(vr['apps_missing_validation'])}")
            st.write(vr["apps_missing_validation"][:100])

    with st.expander("Configured output families"):
        st.json(st.session_state.output_families)


def choose_default_column(df: pd.DataFrame, candidates: List[str]) -> str:
    resolver = ColumnResolver(list(df.columns))
    match = resolver.find_first(candidates)
    return match or "Not Available"


def select_column(label: str, df: pd.DataFrame, candidates: List[str], key: str) -> str:
    options = ["Not Available"] + [c for c in df.columns if not c.startswith("_")]
    default = choose_default_column(df, candidates)
    index = options.index(default) if default in options else 0
    selected = st.selectbox(label, options, index=index, key=key)
    return "" if selected == "Not Available" else selected


def filter_apps_ui(df: pd.DataFrame, key_prefix: str) -> pd.DataFrame:
    candidate_filters = [
        "portfolio", "department", "business owner", "technology owner", "support owner", "criticality", "technology stack"
    ]
    resolver = ColumnResolver(list(df.columns))
    available = []
    for f in candidate_filters:
        col = resolver.find_first([f])
        if col and col not in available:
            available.append(col)
    filtered = df.copy()
    if available:
        with st.expander("Filters", expanded=False):
            cols = st.columns(min(3, len(available)))
            for idx, col in enumerate(available):
                values = sorted([x for x in filtered[col].map(clean_text).unique().tolist() if x])
                selected = cols[idx % len(cols)].multiselect(col, values, key=f"{key_prefix}_{col}")
                if selected:
                    filtered = filtered[filtered[col].map(clean_text).isin(selected)]
    return filtered


def merge_result_labels(results: pd.DataFrame) -> pd.DataFrame:
    labels = st.session_state.app_labels
    if results.empty or labels.empty:
        return results
    source_labels = labels[["_app_key", "Source of Truth Label", "Reliability Label"]].rename(columns={
        "_app_key": "Source Application Key",
        "Source of Truth Label": "Source Source-of-Truth Label",
        "Reliability Label": "Source Reliability Label",
    })
    compared_labels = labels[["_app_key", "Source of Truth Label", "Reliability Label"]].rename(columns={
        "_app_key": "Compared Application Key",
        "Source of Truth Label": "Compared Source-of-Truth Label",
        "Reliability Label": "Compared Reliability Label",
    })
    return results.merge(source_labels, on="Source Application Key", how="left").merge(compared_labels, on="Compared Application Key", how="left")


def similarity_tab():
    st.header("2. Application Similarity and Redundancy")
    if not app_ready():
        st.warning("Required inputs are not loaded yet.")
        return
    df = filter_apps_ui(st.session_state.cmdb_df, "sim_filter")
    st.subheader("Similarity rules")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        business_use_case = select_column("Business use case field", df, ["business use case", "use case", "description", "purpose"], "sim_buc")
        w_buc = st.number_input("Business use case weight", min_value=0.0, max_value=1.0, value=0.30, step=0.05)
    with c2:
        business_function = select_column("Business function field", df, ["business function", "function"], "sim_bf")
        w_bf = st.number_input("Business function weight", min_value=0.0, max_value=1.0, value=0.30, step=0.05)
    with c3:
        capability = select_column("Capability field", df, ["capability", "business capability"], "sim_cap")
        w_cap = st.number_input("Capability weight", min_value=0.0, max_value=1.0, value=0.30, step=0.05)
    with c4:
        process = select_column("Supported process field", df, ["supported process", "process", "value chain", "sub process"], "sim_proc")
        w_proc = st.number_input("Supported process weight", min_value=0.0, max_value=1.0, value=0.10, step=0.05)

    field_map = {
        "Business Use Case": business_use_case,
        "Business Function": business_function,
        "Capability": capability,
        "Supported Process": process,
    }
    weights = {
        "Business Use Case": w_buc,
        "Business Function": w_bf,
        "Capability": w_cap,
        "Supported Process": w_proc,
    }
    cluster_threshold = st.slider("Cluster threshold", 0, 100, 50)
    if st.button("Run similarity analysis", type="primary"):
        sim = similarity_module.calculate_similarity(df, field_map, weights)
        st.session_state.similarity_results = merge_result_labels(sim)

    sim_df = st.session_state.similarity_results
    if sim_df.empty:
        st.info("Run the similarity analysis to generate heatmap, top-5 list, clusters, and alerts.")
        return

    heatmap_tab, panel_tab, top_tab, cluster_tab, alert_tab, compare_tab = st.tabs([
        "App vs App Heatmap", "Similar Apps Panel", "Top 5 List", "Cluster Map", "Redundancy Alerts", "Direct Compare"
    ])
    with heatmap_tab:
        matrix = similarity_module.matrix_for_heatmap(sim_df)
        fig = px.imshow(matrix, text_auto=True, aspect="auto", color_continuous_scale="RdYlGn_r", zmin=0, zmax=100)
        fig.update_layout(height=max(500, 30 * len(matrix)))
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Hover over cells for overlap values. Detailed reasons are available in the result table and direct comparison card.")
        st.dataframe(sim_df, use_container_width=True)
    with panel_tab:
        app_options = sorted(sim_df["Source Application"].dropna().unique().tolist())
        selected = st.multiselect("Select one or more applications", app_options, key="sim_panel_apps")
        threshold = st.number_input("Minimum overlap %", min_value=0.0, max_value=100.0, value=5.0, step=1.0)
        panel = similarity_module.similar_apps_panel(sim_df, selected, threshold)
        st.dataframe(panel, use_container_width=True)
    with top_tab:
        top = similarity_module.top_n_similar(sim_df, 5)
        st.dataframe(top, use_container_width=True)
        st.download_button("Download top-5 similarity CSV", df_to_csv_bytes(top), "similarity_top5.csv", "text/csv")
    with cluster_tab:
        clusters = similarity_module.create_clusters(sim_df, threshold=cluster_threshold)
        st.dataframe(clusters, use_container_width=True)
        render_similarity_network(sim_df, cluster_threshold)
        st.download_button("Download clusters CSV", df_to_csv_bytes(clusters), "similarity_clusters.csv", "text/csv")
    with alert_tab:
        alerts = similarity_module.redundancy_alerts(sim_df)
        st.dataframe(alerts, use_container_width=True)
        st.download_button("Download redundancy alerts CSV", df_to_csv_bytes(alerts), "similarity_alerts.csv", "text/csv")
    with compare_tab:
        app_options = sorted(sim_df["Source Application"].dropna().unique().tolist())
        c1, c2 = st.columns(2)
        a = c1.selectbox("Application A", app_options, key="compare_a")
        b = c2.selectbox("Application B", app_options, key="compare_b")
        card = sim_df[(sim_df["Source Application"] == a) & (sim_df["Compared Application"] == b)]
        st.dataframe(card, use_container_width=True)
        st.caption("MVP uses dropdown-based direct comparison. Drag-and-drop can be added later with a custom Streamlit component.")

    st.download_button("Download full similarity results CSV", df_to_csv_bytes(sim_df), "similarity_results.csv", "text/csv")


def render_similarity_network(sim_df: pd.DataFrame, threshold: float):
    edges = sim_df[(sim_df["Source Application"] < sim_df["Compared Application"]) & (sim_df["Overlap %"] >= threshold)]
    if edges.empty:
        st.info("No similarity network edges meet the selected threshold.")
        return
    g = nx.Graph()
    for _, row in edges.iterrows():
        g.add_edge(row["Source Application"], row["Compared Application"], weight=row["Overlap %"])
    pos = nx.spring_layout(g, seed=42)
    edge_x, edge_y = [], []
    for edge in g.edges():
        x0, y0 = pos[edge[0]]
        x1, y1 = pos[edge[1]]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]
    node_x, node_y, labels = [], [], []
    for node in g.nodes():
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)
        labels.append(node)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=edge_x, y=edge_y, mode="lines", hoverinfo="none"))
    fig.add_trace(go.Scatter(x=node_x, y=node_y, mode="markers+text", text=labels, textposition="top center", marker=dict(size=18)))
    fig.update_layout(showlegend=False, height=550, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)


def technology_tab():
    st.header("3. Technology and Integration Visualization")
    if not app_ready():
        st.warning("Required inputs are not loaded yet.")
        return
    df = filter_apps_ui(st.session_state.cmdb_df, "tech_filter")
    if st.button("Run technology and integration analysis", type="primary"):
        integrations = technology_module.detect_integrations(df)
        clusters = technology_module.technology_clusters(df, st.session_state.app_labels)
        risks = technology_module.risk_analysis(df, integrations, st.session_state.app_labels)
        st.session_state.integrations = integrations
        st.session_state.tech_clusters = clusters
        st.session_state.tech_risks = risks

    integrations = st.session_state.integrations
    clusters = st.session_state.tech_clusters
    risks = st.session_state.tech_risks
    if clusters.empty and risks.empty:
        st.info("Run technology and integration analysis to generate maps, clusters, risk heatmap, and modernization matrix.")
        return

    map_tab, portfolio_tab, cluster_tab, obsolete_tab, risk_tab, modernization_tab = st.tabs([
        "Application Integration Map", "Portfolio Integration Map", "Technology Stack Clusters", "Obsolete Technology", "Risk Heatmap", "Modernization Matrix"
    ])
    with map_tab:
        if integrations.empty:
            st.warning("Insufficient data: no upstream/downstream/integration fields were found or populated.")
        else:
            app = st.selectbox("Select application", sorted(integrations["Selected Application"].unique().tolist()))
            subset = integrations[integrations["Selected Application"] == app]
            render_integration_flow(app, subset)
            st.dataframe(subset, use_container_width=True)
    with portfolio_tab:
        portfolio_col = choose_default_column(st.session_state.cmdb_df, ["portfolio"])
        if portfolio_col == "Not Available":
            st.warning("Portfolio field not available in CMDB. Portfolio-level map cannot be generated.")
        elif integrations.empty:
            st.warning("Insufficient integration data for portfolio map.")
        else:
            portfolio = st.selectbox("Select portfolio", sorted([x for x in st.session_state.cmdb_df[portfolio_col].map(clean_text).unique().tolist() if x]))
            apps = st.session_state.cmdb_df[st.session_state.cmdb_df[portfolio_col].map(clean_text) == portfolio]["_app_label"].tolist()
            subset = integrations[integrations["Selected Application"].isin(apps)]
            render_portfolio_network(subset)
            st.dataframe(subset, use_container_width=True)
    with cluster_tab:
        st.dataframe(clusters, use_container_width=True)
        grouped = clusters.groupby("Technology Stack Bucket").size().reset_index(name="Application Count")
        fig = px.bar(grouped, x="Technology Stack Bucket", y="Application Count")
        fig.update_layout(xaxis_tickangle=-30)
        st.plotly_chart(fig, use_container_width=True)
    with obsolete_tab:
        obsolete = risks[risks["Risk Flags"].str.contains("Obsolete|unsupported|legacy", case=False, na=False)]
        if obsolete.empty:
            st.info("No obsolete or unsupported technology was identified from available fields.")
        else:
            st.dataframe(obsolete, use_container_width=True)
    with risk_tab:
        st.dataframe(risks, use_container_width=True)
        render_risk_heatmap(risks)
    with modernization_tab:
        render_modernization_matrix(risks)
        st.dataframe(risks, use_container_width=True)

    export_cols = st.columns(3)
    export_cols[0].download_button("Download technology clusters CSV", df_to_csv_bytes(clusters), "technology_clusters.csv", "text/csv")
    export_cols[1].download_button("Download integrations CSV", df_to_csv_bytes(integrations), "integrations.csv", "text/csv")
    export_cols[2].download_button("Download risk analysis CSV", df_to_csv_bytes(risks), "technology_risks.csv", "text/csv")


def render_integration_flow(app: str, subset: pd.DataFrame):
    fig = go.Figure()
    nodes = {app: (0, 0)}
    upstream = subset[subset["Direction"] == "Upstream"]
    downstream = subset[subset["Direction"] == "Downstream"]
    for idx, (_, row) in enumerate(upstream.iterrows(), start=1):
        connected = clean_text(row.get("Connected Application or System"))
        if connected and connected != "Not Available":
            nodes[connected] = (-1, idx)
    for idx, (_, row) in enumerate(downstream.iterrows(), start=1):
        connected = clean_text(row.get("Connected Application or System"))
        if connected and connected != "Not Available":
            nodes[connected] = (1, idx)
    for name, (x, y) in nodes.items():
        fig.add_trace(go.Scatter(x=[x], y=[y], mode="markers+text", text=[name], textposition="bottom center", marker=dict(size=20)))
    for _, row in subset.iterrows():
        connected = clean_text(row["Connected Application or System"])
        if connected not in nodes or connected == "Not Available":
            continue
        if row["Direction"] == "Upstream":
            x0, y0 = nodes[connected]
            x1, y1 = nodes[app]
        elif row["Direction"] == "Downstream":
            x0, y0 = nodes[app]
            x1, y1 = nodes[connected]
        else:
            continue
        fig.add_annotation(x=x1, y=y1, ax=x0, ay=y0, xref="x", yref="y", axref="x", ayref="y", showarrow=True, arrowhead=3, text=row.get("Integration Type", ""))
    fig.update_layout(showlegend=False, height=550, margin=dict(l=10, r=10, t=10, b=10), xaxis=dict(visible=False), yaxis=dict(visible=False))
    st.plotly_chart(fig, use_container_width=True)


def render_portfolio_network(subset: pd.DataFrame):
    if subset.empty:
        st.info("No integration records available for selected portfolio.")
        return
    g = nx.DiGraph()
    for _, row in subset.iterrows():
        app = row["Selected Application"]
        conn = row["Connected Application or System"]
        if not conn or conn == "Not Available":
            continue
        if row["Direction"] == "Upstream":
            g.add_edge(conn, app)
        elif row["Direction"] == "Downstream":
            g.add_edge(app, conn)
    if not g.nodes:
        st.info("Integration details are present but connected application names are not available.")
        return
    pos = nx.spring_layout(g, seed=42)
    edge_x, edge_y = [], []
    for a, b in g.edges():
        x0, y0 = pos[a]
        x1, y1 = pos[b]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]
    node_x, node_y, labels = [], [], []
    for node in g.nodes():
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)
        labels.append(node)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=edge_x, y=edge_y, mode="lines"))
    fig.add_trace(go.Scatter(x=node_x, y=node_y, mode="markers+text", text=labels, textposition="top center", marker=dict(size=16)))
    fig.update_layout(showlegend=False, height=600, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)


def risk_value(label: str) -> int:
    return {"Low Risk": 1, "Medium Risk": 2, "High Risk": 3, "Critical Risk": 4}.get(label, 0)


def render_risk_heatmap(risks: pd.DataFrame):
    if risks.empty:
        return
    risk_table = risks[["Application Name", "Risk Label"]].copy()
    risk_table["Risk Score"] = risk_table["Risk Label"].map(risk_value)
    matrix = risk_table.pivot_table(index="Application Name", values="Risk Score", aggfunc="max")
    fig = px.imshow(matrix, text_auto=True, aspect="auto", color_continuous_scale="YlOrRd", zmin=0, zmax=4)
    fig.update_layout(height=max(400, 30 * len(matrix)))
    st.plotly_chart(fig, use_container_width=True)


def render_modernization_matrix(risks: pd.DataFrame):
    if risks.empty:
        return
    chart = risks.copy()
    chart["Risk Score"] = chart["Risk Label"].map(risk_value)
    chart["Integration Count"] = pd.to_numeric(chart["Integration Count"], errors="coerce").fillna(0)
    fig = px.scatter(chart, x="Integration Count", y="Risk Score", text="Application Name", hover_data=["Risk Flags", "Modernization Label"])
    fig.update_traces(textposition="top center")
    fig.update_layout(yaxis=dict(tickmode="array", tickvals=[1, 2, 3, 4], ticktext=["Low", "Medium", "High", "Critical"]), height=600)
    st.plotly_chart(fig, use_container_width=True)


def outputs_tab():
    st.header("4. Application Outputs Analysis")
    if not app_ready():
        st.warning("Required inputs are not loaded yet.")
        return
    df = filter_apps_ui(st.session_state.cmdb_df, "output_filter")
    st.caption("Classification uses the uploaded output-family list and assigns Others when no configured family clearly matches.")
    if st.button("Run output analysis", type="primary"):
        details = outputs_module.application_output_details(df, st.session_state.output_families, st.session_state.app_labels)
        clusters = outputs_module.output_family_clusters(details)
        matrix = outputs_module.app_output_matrix(details, st.session_state.output_families)
        alerts = outputs_module.redundancy_alerts(details)
        st.session_state.output_details = details
        st.session_state.output_clusters = clusters
        st.session_state.output_matrix = matrix
        st.session_state.output_alerts = alerts

    details = st.session_state.output_details
    if details.empty:
        st.info("Run output analysis to generate output family clusters, matrix, details, alerts, and Others exceptions.")
        return
    clusters_tab, matrix_tab, alerts_tab, details_tab, others_tab = st.tabs([
        "Output Family Clusters", "App vs Output Family Matrix", "Redundancy Alerts", "Output Details", "Exceptions / Others"
    ])
    with clusters_tab:
        st.dataframe(st.session_state.output_clusters, use_container_width=True)
    with matrix_tab:
        st.dataframe(st.session_state.output_matrix, use_container_width=True)
        if not st.session_state.output_matrix.empty:
            plot_df = st.session_state.output_matrix.set_index("Application Name").replace({"Yes": 1, "No": 0})
            fig = px.imshow(plot_df, text_auto=True, aspect="auto", color_continuous_scale="Blues", zmin=0, zmax=1)
            fig.update_layout(height=max(400, 30 * len(plot_df)))
            st.plotly_chart(fig, use_container_width=True)
    with alerts_tab:
        st.dataframe(st.session_state.output_alerts, use_container_width=True)
    with details_tab:
        st.dataframe(details, use_container_width=True)
    with others_tab:
        others = outputs_module.exceptions_others(details)
        st.dataframe(others, use_container_width=True)

    c1, c2, c3 = st.columns(3)
    c1.download_button("Download output details CSV", df_to_csv_bytes(details), "output_details.csv", "text/csv")
    c2.download_button("Download output clusters CSV", df_to_csv_bytes(st.session_state.output_clusters), "output_clusters.csv", "text/csv")
    c3.download_button("Download output alerts CSV", df_to_csv_bytes(st.session_state.output_alerts), "output_alerts.csv", "text/csv")


def export_tab():
    st.header("5. Export Center")
    if not app_ready():
        st.warning("Required inputs are not loaded yet.")
        return
    exports = {
        "processed_cmdb.csv": st.session_state.cmdb_df,
        "application_labels.csv": st.session_state.app_labels,
        "cmdb_completeness.csv": st.session_state.cmdb_validation["row_results"],
        "similarity_results.csv": st.session_state.similarity_results,
        "technology_clusters.csv": st.session_state.tech_clusters,
        "integrations.csv": st.session_state.integrations,
        "technology_risks.csv": st.session_state.tech_risks,
        "output_details.csv": st.session_state.output_details,
        "output_clusters.csv": st.session_state.output_clusters,
        "output_matrix.csv": st.session_state.output_matrix,
        "output_alerts.csv": st.session_state.output_alerts,
    }
    for filename, df in exports.items():
        if isinstance(df, pd.DataFrame) and not df.empty:
            st.download_button(f"Download {filename}", df_to_csv_bytes(df), filename, "text/csv")
    st.download_button(
        "Download rules and config JSON",
        object_to_json_bytes({
            "mandatory_fields": st.session_state.mandatory_fields,
            "output_families": st.session_state.output_families,
            "source_of_truth_rules": {
                "Source of Truth 1": "CMDB only",
                "Source of Truth 2": "CMDB + Confluence",
                "Source of Truth 3": "CMDB + Confluence + Team Validation Document",
                "CloudWatch": "Enrichment only; does not change SoT label in this MVP",
            },
            "reliability_rules": {
                "High": "Validation document is available AND mandatory CMDB completeness is 70% or more",
                "Average": "Validation document is missing OR mandatory CMDB completeness is below 70%",
            },
        }),
        "app_analyser_rules_config.json",
        "application/json",
    )


def main():
    init_state()
    upload_panel()
    run_header()
    tabs = st.tabs([
        "Validate Inputs", "Similarity", "Technology & Integrations", "Outputs", "Export"
    ])
    with tabs[0]:
        validation_tab()
    with tabs[1]:
        similarity_tab()
    with tabs[2]:
        technology_tab()
    with tabs[3]:
        outputs_tab()
    with tabs[4]:
        export_tab()


if __name__ == "__main__":
    main()
