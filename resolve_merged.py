import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # optional: only used to read a local .env file
    def load_dotenv(*_args, **_kwargs):
        return False

from db import get_connection, resolve_incident

load_dotenv(Path(__file__).parent / ".env")

PR_URL = re.compile(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)")


def pr_is_merged(pr_url, token):
    m = PR_URL.search(pr_url or "")
    if not m:
        return False
    owner, repo, number = m.groups()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "AI-OnCall-Engineer",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return bool(json.loads(resp.read().decode("utf-8")).get("merged"))
    except Exception as err:
        print(f"[resolve_merged] could not check {pr_url}: {err}")
        return False


def resolve_merged_prs():
    """Mark incidents resolved once their pull request has been merged."""
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        return []
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, pr_url FROM incidents "
            "WHERE status = 'pr_opened' AND resolved_at IS NULL AND pr_url IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    done = []
    for row in rows:
        if pr_is_merged(row["pr_url"], token) and resolve_incident(row["id"]):
            print(f"[resolve_merged] Incident #{row['id']}: PR merged, marked resolved.")
            done.append(row["id"])
    return done


if __name__ == "__main__":
    if "--watch" in sys.argv:
        while True:
            resolve_merged_prs()
            time.sleep(10)
    else:
        result = resolve_merged_prs()
        print("Resolved:", result if result else "nothing to resolve")