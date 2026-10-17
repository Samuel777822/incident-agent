import sqlite3
import pathlib

DB_PATH = "incidents.db"
SCHEMA_PATH = pathlib.Path(__file__).parent / "schema.sql"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()
    conn.close()


def save_event(ts, level, service, message, traceback=None, signature=None):
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO log_events (ts, level, service, message, traceback, signature) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ts, level, service, message, traceback, signature),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


if __name__ == "__main__":
    init_db()
    print("tables created")