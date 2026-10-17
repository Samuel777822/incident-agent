import json
import os
import re
import sys
import time

from db import init_db, save_event,record_incident,get_connection

FRAME = re.compile(r'File "([^"]+)", line (\d+)')


def signature(tb):
    if not tb:
        return None
    lines = [l for l in tb.strip().splitlines() if l.strip()]
    err = lines[-1].split(":")[0].strip()
    frames = FRAME.findall(tb)
    mine = [f for f in frames if "site-packages" not in f[0]]
    path, line = (mine or frames or [("?", "0")])[-1]
    return f"{err}:{os.path.basename(path)}:{line}"


def handle_line(line):
    print("got line:", line[:60])

    try:
        e = json.loads(line)
    except json.JSONDecodeError as err:
        print("SKIPPED, not valid JSON:", err)
        return

    tb = e.get("traceback")
    sig = signature(tb)

    row_id = save_event(
        e.get("ts"),
        e.get("level"),
        e.get("service"),
        e.get("message"),
        tb,
        sig,
    )
    print("saved row", row_id)

    if e.get("level") == "ERROR" and sig:
        incident_id, is_new = record_incident(sig, e.get("ts"))

        conn = get_connection()
        conn.execute(
            "UPDATE log_events SET incident_id = ? WHERE id = ?",
            (incident_id, row_id),
        )
        conn.commit()
        conn.close()

        print("incident", incident_id, "new:", is_new)


def tail(path, from_start=False):
    init_db()
    with open(path, encoding="utf-8") as f:
        if not from_start:
            f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.5)
                continue
            handle_line(line)


if __name__ == "__main__":
    tail(sys.argv[1], from_start="--from-start" in sys.argv)