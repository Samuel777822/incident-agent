from repo_sync import get_local_repo
from evidence import collect_repository

folder = get_local_repo("shop-api")
print("downloaded to:", folder)
files = collect_repository(folder)
print(len(files), "files:", sorted(files))