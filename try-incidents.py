from db import record_incident, get_connection



for r in get_connection().execute(
    "SELECT id, signature, status, occurrences, last_seen FROM incidents"
):
    print(dict(r))