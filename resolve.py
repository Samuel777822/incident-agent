import sys

from db import resolve_incident

if len(sys.argv) < 2:
    print("Usage: resolve.py <incident id>")
    sys.exit(1)

incident_id = int(sys.argv[1])
if resolve_incident(incident_id):
    print(f"Incident {incident_id} marked resolved.")
else:
    print(f"Nothing changed: incident {incident_id} doesn't exist or is already resolved.")
