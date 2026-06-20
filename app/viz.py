"""Pluggable data-viz layer for Bíómonsi — swap rendering backends per view.

Each capability (network / sankey / treemap / trends / browse) can render through several backends.
`available_backends(cap)` returns only the ones actually installed; `backend_picker()` is a per-view
style dropdown. native + plotly always work; echarts / agraph / aggrid are optional upgrades that
appear automatically when pip-installed (graceful — no crash if absent).

Deps: plotly (required), networkx (for plotly/agraph layouts). Optional: streamlit-echarts,
streamlit-agraph, st-aggrid. STAGED — review + test before deploy.
"""
from __future__ import annotations

import importlib.util

import plotly.express as px
import plotly.graph_objects as go

FAMILY_IS = {"handrit": "Handrit", "throun": "Þróun", "framleidsla": "Framleiðsla",
             "eftirvinnsla": "Eftirvinnsla", "endurgreidsla": "Endurgreiðsla", "annad": "Aðrir"}
# One consistent, colorblind-safe encoding per family — reused across charts (DATAVIZ_GUIDE).
FAMILY_COLORS = {"Handrit": "#4C78A8", "Þróun": "#72B7B2", "Framleiðsla": "#E45756",
                 "Eftirvinnsla": "#F58518", "Endurgreiðsla": "#54A24B", "Aðrir": "#B279A2"}

# capability -> candidate backends in preference order
_CAPS = {
    # plotly/native FIRST = the working default (component libs lag new Streamlit); fancy ones are
    # offered second and fall back to plotly at render if they error on this Streamlit version.
    "network": ["plotly", "agraph", "echarts"],
    "sankey": ["plotly", "echarts"],
    "treemap": ["plotly"],
    "trends": ["plotly", "echarts"],
    "browse": ["native", "aggrid"],
}
_MODULE = {"echarts": "streamlit_echarts", "agraph": "streamlit_agraph", "aggrid": "st_aggrid"}
_LABEL = {"native": "Einfalt (Streamlit)", "plotly": "Plotly", "echarts": "ECharts",
          "agraph": "Net (agraph)", "aggrid": "Tafla (AgGrid)"}


def _installed(backend: str) -> bool:
    if backend in ("native", "plotly"):
        return backend != "plotly" or importlib.util.find_spec("plotly") is not None
    return importlib.util.find_spec(_MODULE[backend]) is not None


def available_backends(cap: str) -> list[str]:
    return [b for b in _CAPS.get(cap, []) if _installed(b)]


def backend_picker(st, cap: str, key: str, label: str = "Stíll"):
    opts = available_backends(cap)
    if len(opts) <= 1:
        return opts[0] if opts else None
    with st.expander(f"{label} ▾"):  # tuck the renderer switch away so the default carries the view
        return st.selectbox(label, opts, format_func=lambda b: _LABEL.get(b, b), key=key)


def _empty(st, msg="Engin gögn"):
    st.info(msg)


# ───────────────────────── network ─────────────────────────
def network(st, edges_df, backend: str | None = None, focus: str | None = None,
            min_weight: int = 2):
    """edges_df: columns a, b, weight (two people + #shared works). Designed AGAINST the hairball:
    with a `focus` we draw the ego-network (only edges touching it); otherwise we keep ties with
    weight >= min_weight (worked together more than once)."""
    if edges_df is None or edges_df.empty:
        return _empty(st, "Engin samstarfstengsl")
    d = edges_df.copy()
    if focus:
        d = d[(d["a"] == focus) | (d["b"] == focus)]
    elif min_weight and "weight" in d.columns:
        d = d[d["weight"] >= min_weight]
    if d.empty:
        return _empty(st, "Engin sterk samstarfstengsl (sía: ≥%d sameiginleg verk)" % min_weight)
    edges_df = d
    backend = backend or (available_backends("network") or ["plotly"])[0]
    try:
        if backend == "agraph":
            return _agraph_network(st, edges_df, focus)
        if backend == "echarts":
            return _echarts_network(st, edges_df, focus)
    except Exception:
        st.caption("(fínn teiknigrunnur óvirkur á þessari Streamlit-útgáfu — sýni Plotly)")
    return _plotly_network(st, edges_df, focus)


def _plotly_network(st, edges_df, focus):
    import networkx as nx
    G = nx.Graph()
    for _, r in edges_df.iterrows():
        G.add_edge(str(r["a"]), str(r["b"]), weight=float(r.get("weight", 1)))
    pos = nx.spring_layout(G, seed=42, k=0.6)
    ex, ey = [], []
    for a, b in G.edges():
        ex += [pos[a][0], pos[b][0], None]; ey += [pos[a][1], pos[b][1], None]
    nodes = list(G.nodes())
    nt = go.Scatter(
        x=[pos[n][0] for n in nodes], y=[pos[n][1] for n in nodes], mode="markers+text",
        text=nodes, textposition="top center", textfont=dict(size=9),
        hovertext=[f"{n} ({G.degree(n)} samstarf)" for n in nodes], hoverinfo="text",
        marker=dict(size=[8 + 3 * G.degree(n) for n in nodes],
                    color=["#d9534f" if n == focus else "#4a90d9" for n in nodes]))
    fig = go.Figure([go.Scatter(x=ex, y=ey, mode="lines", line=dict(width=0.6, color="#bbb"),
                                hoverinfo="none"), nt])
    fig.update_layout(title="Samstarfsnet", showlegend=False, xaxis_visible=False,
                      yaxis_visible=False, height=600)
    st.plotly_chart(fig, use_container_width=True)


def _echarts_network(st, edges_df, focus):
    from streamlit_echarts import st_echarts
    deg: dict[str, int] = {}
    for _, r in edges_df.iterrows():
        deg[str(r["a"])] = deg.get(str(r["a"]), 0) + 1
        deg[str(r["b"])] = deg.get(str(r["b"]), 0) + 1
    nodes = [{"name": n, "symbolSize": 8 + 3 * d,
              "itemStyle": {"color": "#d9534f" if n == focus else "#4a90d9"}} for n, d in deg.items()]
    links = [{"source": str(r["a"]), "target": str(r["b"])} for _, r in edges_df.iterrows()]
    st_echarts({"title": {"text": "Samstarfsnet"},
                "series": [{"type": "graph", "layout": "force", "roam": True, "label": {"show": True},
                            "force": {"repulsion": 120}, "data": nodes, "links": links}]}, height="600px")


def _agraph_network(st, edges_df, focus):
    from streamlit_agraph import Config, Edge, Node, agraph
    seen = set()
    nodes, edges = [], []
    for _, r in edges_df.iterrows():
        for x in (str(r["a"]), str(r["b"])):
            if x not in seen:
                seen.add(x)
                nodes.append(Node(id=x, label=x, color="#d9534f" if x == focus else "#4a90d9"))
        edges.append(Edge(source=str(r["a"]), target=str(r["b"])))
    agraph(nodes=nodes, edges=edges,
           config=Config(width="100%", height=600, directed=False, physics=True))


# ───────────────────────── sankey ─────────────────────────
def sankey(st, alloc_df, backend: str | None = None):
    d = alloc_df[alloc_df["amount_isk"].notna()].copy()
    if d.empty:
        return _empty(st)
    d["family"] = d["family"].map(lambda f: FAMILY_IS.get(f, f))
    d["format_track"] = d["format_track"].fillna("—")
    d["company"] = d["company"].fillna("(óþekkt)").str.split("/").str[0].str.strip()
    # top-8 named companies as nodes, everything else bucketed → keeps the column readable (~10 nodes)
    top = d[d["company"] != "(óþekkt)"].groupby("company")["amount_isk"].sum() \
        .sort_values(ascending=False).head(8).index
    d["company"] = d["company"].where(d["company"].isin(top), "Annað")
    if d.empty:
        return _empty(st)
    backend = backend or (available_backends("sankey") or ["plotly"])[0]
    labels, idx, src, tgt, val = [], {}, [], [], []

    def node(name):
        if name not in idx:
            idx[name] = len(labels); labels.append(name)
        return idx[name]

    for (a, b), amt in d.groupby(["family", "format_track"])["amount_isk"].sum().items():
        src.append(node(str(a))); tgt.append(node("· " + str(b))); val.append(float(amt))
    for (b, c), amt in d.groupby(["format_track", "company"])["amount_isk"].sum().items():
        src.append(node("· " + str(b))); tgt.append(node(str(c))); val.append(float(amt))

    if backend == "echarts":
        try:
            from streamlit_echarts import st_echarts
            st_echarts({"title": {"text": "Flæði fjármagns"},
                        "series": [{"type": "sankey", "data": [{"name": n} for n in labels],
                                    "links": [{"source": labels[s], "target": labels[t], "value": v}
                                              for s, t, v in zip(src, tgt, val)]}]}, height="600px")
            return
        except Exception:
            st.caption("(ECharts óvirkt á þessari Streamlit-útgáfu — sýni Plotly)")
    fig = go.Figure(go.Sankey(node=dict(label=labels, pad=15, thickness=14),
                              link=dict(source=src, target=tgt, value=val)))
    fig.update_layout(title="Flæði fjármagns: flokkur → tegund → fyrirtæki", font_size=11)
    st.plotly_chart(fig, use_container_width=True)


# ───────────────────────── treemap & trends ─────────────────────────
def treemap(st, alloc_df, top: int = 25):
    d = alloc_df[(alloc_df["family"] == "framleidsla") & alloc_df["amount_isk"].notna()].copy()
    if d.empty:
        return _empty(st)
    d["company"] = d["company"].fillna("(óþekkt)").str.split("/").str[0].str.strip()
    d = d[d["company"] != "(óþekkt)"]   # concentration of NAMED companies
    agg = d.groupby("company")["amount_isk"].sum().sort_values(ascending=False).head(top).reset_index()
    fig = px.treemap(agg, path=["company"], values="amount_isk",
                     title="Framleiðslufé þjappast á fáein fyrirtæki")
    st.plotly_chart(fig, use_container_width=True)


def trends(st, alloc_df, backend: str | None = None):
    d = alloc_df[alloc_df["family"] == "framleidsla"]
    if d.empty:
        return _empty(st)
    counts = d.groupby(["year", "format_track"]).size().reset_index(name="n")
    fig = px.line(counts, x="year", y="n", color="format_track", markers=True,
                  labels={"year": "Ár", "n": "Fjöldi", "format_track": "Tegund"},
                  title="Framleiðslustyrkir eftir tegund og ári")
    st.plotly_chart(fig, use_container_width=True)


# ───────────────────────── browse table (native ↔ aggrid) ─────────────────────────
def browse_table(st, df, id_col: str, backend: str | None = None, key: str = "browse"):
    """Render a table; return the selected row's id_col value (or None). df must include id_col."""
    backend = backend or (available_backends("browse") or ["native"])[0]
    if backend == "aggrid":
        try:
            from st_aggrid import AgGrid, GridOptionsBuilder
            gob = GridOptionsBuilder.from_dataframe(df)
            gob.configure_selection("single")
            grid = AgGrid(df, gridOptions=gob.build(), height=420, key=key)
            sel = grid.get("selected_rows") or []
            return sel[0][id_col] if sel else None
        except Exception:
            pass  # fall through to native dataframe
    try:
        ev = st.dataframe(df, use_container_width=True, hide_index=True,
                          on_select="rerun", selection_mode="single-row", key=key)
        rows = ev.selection.rows if ev and ev.selection else []
        return df.iloc[rows[0]][id_col] if rows else None
    except TypeError:
        st.dataframe(df, use_container_width=True, hide_index=True)
        return None
