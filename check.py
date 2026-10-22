from db import get_connection

conn = get_connection()

for r in conn.execute(
    "SELECT id, level, signature, incident_id FROM log_events"
):
    print(dict(r))

conn.close()