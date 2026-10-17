from db import get_incident, get_incident_events
from repo_sync import get_local_repo
from git_evidence import get_git_evidence

inc = get_incident()
service = get_incident_events(inc["id"])[0]["service"]
folder = get_local_repo(service)
print(get_git_evidence(folder))