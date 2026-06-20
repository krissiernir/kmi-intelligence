"""Ask Bíómonsi — conversational text-to-SQL over the KMÍ database, answering in Icelandic.

The model gets a READ-ONLY `run_sql` tool; it writes the SQL, the tool runs it (SELECT-only, read-only
connection), rows come back, it answers in Icelandic. The UI shows the answer AND every SQL + rows so a
wrong answer is catchable.

Backend: Anthropic (the user's ANTHROPIC_API_KEY) via a standard messages tool-use loop. Default model
claude-opus-4-8 (override via BIOMONSI_MODEL). Deps: anthropic (+ ANTHROPIC_API_KEY in env / a gitignored .env).
"""
from __future__ import annotations

import os
import sqlite3

import pandas as pd

MODEL = os.environ.get("BIOMONSI_MODEL", "claude-opus-4-8")
MAX_ROWS_TO_MODEL = 100      # protect context
MAX_ROWS_TO_SHOW = 500
MAX_TOOL_ROUNDS = 8

SYSTEM_TMPL = """Þú ert Bíómonsi, greiningaraðstoð fyrir íslenskan kvikmyndaframleiðanda.
Þú svarar spurningum um KMÍ-styrki og íslenska kvikmyndagerð með því að keyra SQL gegn gagnagrunninum.

Reglur:
- Notaðu `run_sql` tólið með SELECT-fyrirspurnum (ein fyrirspurn í einu, engar breytingar). Keyrðu eins
  margar fyrirspurnir og þarf til að svara — kannaðu skemað fyrst ef þú ert óviss.
- Svaraðu á ÍSLENSKU, hnitmiðað, með tölum úr gögnunum. Nefndu ef gögn vantar eða eru óviss.
- Athugaðu: úthlutanaskráin nær aðeins 2021–2024.
- Skýrðu stutt hvaða fyrirspurn þú keyrðir ef það hjálpar notandanum að treysta svarinu.

Gagnagrunnsskema (SQLite):
{schema}
"""

_TOOL = {
    "name": "run_sql",
    "description": ("Keyrðu eina read-only SQL SELECT (eða WITH … SELECT) fyrirspurn gegn KMÍ-"
                    "gagnagrunninum og fáðu línurnar til baka sem CSV. Engar breytingar."),
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Ein SQL SELECT fyrirspurn."}},
        "required": ["query"],
    },
}


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
    from anthropic import Anthropic

    steps: list[dict] = []

    def run_sql(query: str) -> str:
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

    try:
        client = Anthropic()
        system = SYSTEM_TMPL.format(schema=_schema(db_path))
        messages = [{"role": "user", "content": question}]
        answer = ""
        for _ in range(MAX_TOOL_ROUNDS):
            resp = client.messages.create(model=MODEL, max_tokens=4096, system=system,
                                          tools=[_TOOL], messages=messages)
            if resp.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": resp.content})
                results = [{"type": "tool_result", "tool_use_id": b.id,
                            "content": run_sql(b.input.get("query", ""))}
                           for b in resp.content if b.type == "tool_use" and b.name == "run_sql"]
                messages.append({"role": "user", "content": results})
            else:
                answer = "".join(b.text for b in resp.content if b.type == "text")
                break
    except Exception as e:                                                    # noqa: BLE001
        return {"answer": "", "steps": steps, "error": str(e)}
    return {"answer": answer or "(Bíómonsi gat ekki svarað)", "steps": steps, "error": None}


# ───────────────────────── Streamlit page ─────────────────────────
def render(st, db_path):
    st.title("Spyrðu Bíómonsa")
    st.caption("Spyrðu á íslensku eða ensku — t.d. „hvaða heimildamyndaleikstjórar fá mest "
               "en hafa engan erlendan meðframleiðanda?“")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.warning("ANTHROPIC_API_KEY vantar í umhverfið (.env) — Ask Bíómonsi er óvirkt.")
        return
    examples = ["Hver fékk mest í framleiðslustyrki 2021–2024?",
                "Hvaða fyrirtæki eru SÍK-félagar en fengu engan styrk?",
                "Hver eru tíðustu samstörf leikstjóra og framleiðenda?"]
    q = st.text_input("Spurning", value=st.session_state.get("ask_q", ""))
    cols = st.columns(len(examples))
    for col, ex in zip(cols, examples):
        if col.button(ex, use_container_width=True):
            st.session_state["ask_q"] = ex
            st.rerun()
    if st.button("Spyrja", type="primary") and q:
        with st.spinner("Bíómonsi hugsar…"):
            res = ask(q, db_path)
        if res.get("error"):
            st.error(f"Villa: {res['error']}")
        st.markdown(res["answer"])
        for i, step in enumerate(res["steps"], 1):
            with st.expander(f"SQL fyrirspurn {i} · {len(step['rows'])} línur"):
                st.code(step["sql"], language="sql")
                st.dataframe(step["rows"], use_container_width=True, hide_index=True)
        if res["steps"]:
            st.caption("⚠️ Staðfestu alltaf svarið gegn SQL-inu og línunum hér að ofan.")
