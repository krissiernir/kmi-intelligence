"""Collaboration network — the node connection map over person_collab.

Who has worked with whom, and how many times. People are coloured by functional layer
(creative / tech / production / cast / flagged) and the layers are TOGGLEABLE, so actors can be kept
separate or hidden. Two views: the whole industry (thresholded, to avoid a hairball) or the
ego-network around one person.
"""
from __future__ import annotations

import viz

LAYERS = ["creative", "tech", "production", "cast", "flagged"]


def render(st, q):
    st.title("🕸️ Samstarfsnet")
    st.caption("Hver hefur unnið með hverjum — og hversu oft. Leikarar eru sérstakt lag; "
               "kveiktu/slökktu á lögum og stilltu styrk tengsla.")

    picked = st.multiselect("Lög (hópar)", LAYERS, default=["creative", "tech", "production"],
                            format_func=lambda x: viz.LAYER_IS.get(x, x))
    if not picked:
        st.info("Veldu a.m.k. eitt lag.")
        return
    ph = ",".join("?" * len(picked))

    mode = st.radio("Sýn", ["Heild", "Einstaklingur"], horizontal=True)

    if mode == "Einstaklingur":
        names = q("SELECT display_name FROM person WHERE layer IS NOT NULL "
                  "ORDER BY credit_count DESC LIMIT 1500")["display_name"].tolist()
        who = st.selectbox("Einstaklingur", names, index=0 if names else None,
                           placeholder="Veldu manneskju…")
        if not who:
            return
        edges = q(f"""SELECT p1.display_name a, p2.display_name b, pc.shared weight,
                             p1.layer la, p2.layer lb
                      FROM person_collab pc
                      JOIN person p1 ON p1.id = pc.a_id
                      JOIN person p2 ON p2.id = pc.b_id
                      WHERE (p1.display_name = ? OR p2.display_name = ?)
                        AND p1.layer IN ({ph}) AND p2.layer IN ({ph})
                      ORDER BY pc.shared DESC""", (who, who, *picked, *picked))
        focus = who
        st.caption(f"{len(edges)} samstarfstengsl við **{who}** (innan valinna laga)")
    else:
        minw = st.slider("Lágmark sameiginlegra verka", 2, 15, 5)
        edges = q(f"""SELECT p1.display_name a, p2.display_name b, pc.shared weight,
                             p1.layer la, p2.layer lb
                      FROM person_collab pc
                      JOIN person p1 ON p1.id = pc.a_id
                      JOIN person p2 ON p2.id = pc.b_id
                      WHERE pc.shared >= ? AND p1.layer IN ({ph}) AND p2.layer IN ({ph})
                      ORDER BY pc.shared DESC LIMIT 250""", (minw, *picked, *picked))
        focus = None
        st.caption(f"Sterkustu {len(edges)} tengsl (≥{minw} sameiginleg verk, hámark 250)")

    if edges.empty:
        st.info("Engin tengsl með þessum síum.")
        return

    # legend + node-layer map for colouring
    node_layers = {}
    for r in edges.itertuples():
        node_layers[r.a] = r.la
        node_layers[r.b] = r.lb
    st.caption(" · ".join(f"🔵 {viz.LAYER_IS[x]}".replace("🔵", "●") for x in picked))
    viz.network(st, edges[["a", "b", "weight"]], focus=focus, min_weight=1, node_layers=node_layers)

    with st.expander("Sterkustu tengslin (tafla)"):
        t = edges[["a", "b", "weight"]].copy()
        t.columns = ["Aðili A", "Aðili B", "Saman (skipti)"]
        st.dataframe(t.head(40), use_container_width=True, hide_index=True)
