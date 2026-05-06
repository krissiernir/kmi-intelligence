from src.kmi_intelligence.db import get_connection, create_schema
from src.kmi_intelligence.seed import load_seed_data


def test_seed_load_counts():
    conn = get_connection(":memory:")
    create_schema(conn)
    load_seed_data(conn)

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM grants")
    assert cur.fetchone()[0] >= 1

    cur.execute("SELECT COUNT(*) FROM projects WHERE title = 'Great Fire'")
    assert cur.fetchone()[0] == 1
