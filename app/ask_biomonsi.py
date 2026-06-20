"""Ask Bíómonsi — conversational text-to-SQL over the KMÍ database, answering in Icelandic.

Gives Claude a READ-ONLY `run_sql` tool; it writes the SQL, the tool runs it (SELECT-only, read-only
connection), rows come back, it answers in Icelandic. The UI shows the answer AND every SQL + rows so a
wrong answer is catchable. Default model claude-opus-4-8.

Deps: anthropic (+ ANTHROPIC_API_KEY env). STAGED — review + test before deploy.
Verify the SDK exposes `client.beta.messages.tool_runner(... system=, thinking=)` for your anthropic version.
"""
from __future__ import annotations

import os
import sqlite3

import pandas as pd

MODEL = os.environ.get("BIOMONSI_MODEL", "claude-opus-4-8")
MAX_ROWS_TO_MODEL = 100      # protect context
MAX_ROWS_TO_SHOW = 500

SYSTEM_TMPL = """Þú ert Bíómonsi, greiningaraðstoð fyrir íslenskan kvikmyndaframleiðanda.
Þú svarar spurningum um KMÍ-styrki og íslenska kvikmyndagerð með því að keyra SQL gegn gagnagrunninum.

Reglur:
- Notaðu EINGÖNGU `run_sql` tólið með SELECT-fyrirspurnum (ein fyrirspurn í einu, engar breytingar).
- Svaraðu á ÍSLENSKU, hnitmiðað, með tölum úr gögnunum. Nefndu ef gögn vantar eða eru óviss.
- Athugaðu: úthlutanaskráin nær aðeins 2021–2024.
- Skýrðu stutt hvaða fyrirspurn þú keyrðir ef það hjálpar notandanum að treysta svarinu.

Gagnagrunnsskema (SQLite):
{schema}
"""


def _schema(db_path: str) -> str:
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as c:
        rows = c.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL ORDER BY name"
        ).fetchall()
    return "\n\n".join(r[0] for r in rows)


def _select_only(query: str) -> str | None:
    """Return an error message if the query isn't a single read-only SELECT, else None."""
    q = query.strip().rstrip(";").lower()
    if ";" in q:
        return "Aðeins ein fyrirspurn í einu er leyfð."
    if not (q.startswith("select") or q.startswith("with")):
        return "Aðeins SELECT (lesfyrirspurnir) eru leyfðar."
    return None


def ask(question: str, db_path: str) -> dict:
    """Returns {'answer': str, 'steps': [{'sql': str, 'rows': DataFrame}], 'error': str|None}."""
    from anthropic import Anthropic, beta_tool

    steps: list[dict] = []

    @beta_tool
    def run_sql(query: str) -> str:
        """Keyrðu read-only SQL SELECT fyrirspurn gegn KMÍ-gagnagrunninum og fáðu línurnar til baka.

        Args:
            query: Ein SQL SELECT (eða WITH … SELECT) fyrirspurn. Engar breytingar (INSERT/UPDATE/DELETE).
        """
        err = _select_only(query)
        if err:
            return f"VILLA: {err}"
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as c:   # read-only enforces it too
                df = pd.read_sql_query(query, c)
        except Exception as e:                                                # noqa: BLE001
            return f"VILLA við keyrslu: {e}"
        steps.append({"sql": query, "rows": df.head(MAX_ROWS_TO_SHOW)})
        head = df.head(MAX_ROWS_TO_MODEL)
        note = f"\n({len(df)} línur alls, sýni {len(head)})" if len(df) > len(head) else ""
        return head.to_csv(index=False) + note

    client = Anthropic()
    system = SYSTEM_TMPL.format(schema=_schema(db_path))
    runner = client.beta.messages.tool_runner(
        model=MODEL, max_tokens=4096, system=system, tools=[run_sql],
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": question}],
    )
    final = None
    for message in runner:
        final = message
    answer = "".join(b.text for b in (final.content if final else []) if b.type == "text")
    refused = final and getattr(final, "stop_reason", None) == "refusal"
    return {"answer": answer or ("(Bíómonsi gat ekki svarað)" if not refused else "(beiðni hafnað)"),
            "steps": steps, "error": None}


# ───────────────────────── Streamlit page ─────────────────────────
def render(st, db_path):
    st.title("Spyrðu Bíómonsa")
    st.caption("Spyrðu á íslensku eða ensku — t.d. „hvaða heimildamyndaleikstjórar fá mest "
               "en hafa engan erlendan meðframleiðanda?“")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.warning("ANTHROPIC_API_KEY vantar í umhverfið — Ask Bíómonsi er óvirkt.")
        return
    # seed example questions so the box isn't a blank stare
    examples = ["Hver fékk mest í framleiðslustyrki 2021–2024?",
                "Hvaða fyrirtæki eru SÍK-félagar en fengu engan styrk?",
                "Hver eru tíðustu samstörf leikstjóra og framleiðenda?"]
    q = st.text_input("Spurning", value=st.session_state.get("ask_q", ""))
    cols = st.columns(len(examples))
    for col, ex in zip(cols, examples):
        if col.button(ex, use_container_width=True):
            st.session_state["ask_q"] = ex; st.rerun()
    if st.button("Spyrja", type="primary") and q:
        with st.spinner("Bíómonsi hugsar…"):
            res = ask(q, db_path)
        st.markdown(res["answer"])
        for i, step in enumerate(res["steps"], 1):
            with st.expander(f"SQL fyrirspurn {i} · {len(step['rows'])} línur"):
                st.code(step["sql"], language="sql")
                st.dataframe(step["rows"], use_container_width=True, hide_index=True)
        st.caption("⚠️ Staðfestu alltaf svarið gegn SQL-inu og línunum hér að ofan.")
