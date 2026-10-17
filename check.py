from db import get_connection

for r in get_connection().execute("SELECT id, level, signature FROM log_events"):
    print(dict(r))