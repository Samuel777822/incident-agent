from db import get_incident, get_incident_events

inc = get_incident()
print(inc)
if inc:
    for e in get_incident_events(inc["id"]):
        print(e["id"], e["service"], e["message"])