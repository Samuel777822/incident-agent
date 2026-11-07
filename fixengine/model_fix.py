"""Deterministic fix for the most common vibe-coder outage: the app calls an AI model that was retired.

  error report ("model not found", "decommissioned", "deprecated", ...) or a scan finding
    -> which model, which provider (from the error text, the failing URL, or the model id itself)
    -> replacement from model_registry.json, double-checked against the provider's live model list (model_catalog)
    -> replace the model id everywhere it appears as a value in the code/config (never in .env secrets files)
    -> validate: the sandbox check when the sandbox is online, otherwise a parse-only check of every changed file
    -> normal PR flow (fix branch + pull request for human review)

No AI model is called and no tries are spent. If the model id is not in the repository (it lives in the hosting
dashboard's environment variables), the customer gets exact, plain-language instructions instead.
"""
from __future__ import annotations

import ast
import difflib
import json
import os
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path, PurePosixPath

from . import model_catalog

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "model_registry.json"
TEXT_EXT = (".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte", ".html", ".htm", ".json", ".yaml", ".yml",
            ".toml", ".ini", ".cfg", ".txt", ".astro")
SKIP_PARTS = {"node_modules", ".git", "venv", ".venv", "dist", "build", ".next", "out", "__pycache__", "coverage", "vendor"}
SKIP_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock", "incident_agent_monitor.py",
              "incident-agent-monitor.cjs", "incident-agent-monitor.js", "incident-agent-monitor.browser.js"}
ERROR_HINT = re.compile(r"model_not_found|model_decommissioned|invalid_model|unknown[_ ]model|not_found_error|"
                        r"model[^\n]{0,160}?(not[ _]found|does not exist|decommissioned|deprecated|no longer (supported|available)|"
                        r"retired|has been (shut down|removed)|is not supported|is not a valid model|not available)|"
                        r"(not a valid|invalid|unknown|unsupported) model", re.I)
CANDIDATE = re.compile(r"[`'\"]((?:models/)?[A-Za-z0-9][\w.:/-]{2,80})[`'\"]|\bmodel[\s:=\"'`]+((?:models/)?[A-Za-z0-9][\w.:/-]{2,80})|"
                       r"\bmodels/([\w.-]{3,80})", re.I)
MODEL_CONTEXT = re.compile(r"model|engine|llm|deployment", re.I)


@lru_cache(maxsize=1)
def _registry_cached(raw: str) -> dict:
    data = json.loads(raw)
    for prov in data["providers"].values():
        prov["_retired"] = [(re.compile(r"^(?:" + r["pattern"] + r")$", re.I), r.get("confidence", "likely"), bool(r.get("needs_context")))
                            for r in prov.get("retired", [])]
        prov["_hint"] = re.compile(prov.get("id_hint", "^$"), re.I)
    return data


def registry() -> dict:
    raw = os.getenv("MODEL_REGISTRY_JSON", "").strip() or REGISTRY_PATH.read_text(encoding="utf-8")
    return _registry_cached(raw)


# ----------------------------------------------------------------------------------------------------- recognising the problem
def provider_for(model_id: str, host: str = "", text: str = "") -> str:
    reg = registry()["providers"]
    host = (host or "").lower()
    for name, prov in reg.items():
        if host and any(host == h or host.endswith("." + h) or host.endswith(h) for h in prov.get("hosts", [])):
            return name
    for name, prov in reg.items():            # a URL inside the error text
        for h in prov.get("hosts", []):
            if h in (text or "").lower():
                return name
    mid = (model_id or "").lower()
    if "/" in mid and not mid.startswith("models/"):
        if mid.startswith(("meta-llama/", "moonshotai/", "openai/gpt-oss", "qwen/")) and "openrouter" not in (text or "").lower():
            return "groq"
        return "openrouter"
    for name in ("anthropic", "google", "openai", "groq"):
        if reg[name]["_hint"].search(mid):
            return name
    return ""


def is_retired(model_id: str, provider: str = "", *, line: str = "") -> str:
    """'certain' | 'likely' | '' for a model id the registry lists as retired."""
    reg = registry()["providers"]
    provider = provider or provider_for(model_id)
    for name in ([provider] if provider in reg else list(reg)):
        for pattern, confidence, needs_context in reg[name]["_retired"]:
            if pattern.match(model_id):
                if needs_context and not MODEL_CONTEXT.search(line or ""):
                    continue
                return confidence
    return ""


def detect_error(message: str, traceback_text: str = "", context: dict | None = None) -> dict | None:
    """{model, provider, evidence} when an error report says an AI model is unknown/retired, else None."""
    text = f"{message}\n{traceback_text}"
    if not ERROR_HINT.search(text):
        return None
    host = str((context or {}).get("host") or "")
    if not host:
        m = re.search(r"https?://([\w.-]+)/", text)
        host = m.group(1) if m else ""
    found = []
    for match in CANDIDATE.finditer(text):
        cand = next(g for g in match.groups() if g)
        cand = cand.strip().rstrip(".,;")
        low = cand.lower()
        if low.startswith(("http", "www.")) or low in ("model", "models", "error", "message", "invalid_request_error", "not_found_error",
                                                        "model_not_found", "model_decommissioned", "type", "code"):
            continue
        prov = provider_for(cand, host, text)
        reg = registry()["providers"].get(prov)
        if reg and (reg["_hint"].search(cand) or is_retired(cand, prov, line="model")):
            found.append((cand.removeprefix("models/") if prov == "google" else cand, prov))
    if not found:
        return None
    model, prov = found[0]
    return {"model": model, "provider": prov, "host": host, "evidence": ERROR_HINT.search(text).group(0)[:200]}


# ----------------------------------------------------------------------------------------------------- choosing the new model
def _family_pick(provider: str, old: str, listing: list[dict]) -> str:
    fams = registry()["providers"].get(provider, {}).get("families") or {}
    for fam, pattern in fams.items():
        if fam in old.lower():
            regex = re.compile(pattern, re.I)
            hits = sorted((m for m in listing if regex.match(m["id"])), key=lambda m: (m.get("created") or 0, m["id"]), reverse=True)
            if hits:
                return hits[0]["id"]
    return ""


def choose_replacement(old: str, provider: str) -> dict:
    """{new, verified, note}. verified=True when the provider's live list shows the new model and (if it can tell) not the old."""
    prov = registry()["providers"].get(provider) or {}
    new = next((r["use"] for r in prov.get("replacements", []) if re.search(r["match"], old, re.I)), "")
    listing = model_catalog.models(provider)
    if listing is None:
        return {"new": new, "verified": False, "old_live": None,
                "note": "The provider's live model list could not be read, so the replacement is the documented one."}
    live = {m["id"] for m in listing}
    old_live = old in live or old.removeprefix("models/") in live
    if new in live:
        return {"new": new, "verified": True, "old_live": old_live, "note": "Checked against the provider's live model list."}
    picked = _family_pick(provider, old, listing)
    if picked:
        return {"new": picked, "verified": True, "old_live": old_live, "note": "Newest model of the same family on the provider's live list."}
    return {"new": new, "verified": False, "old_live": old_live,
            "note": f"{new} was not on the provider's live list; please check the model name before merging."}


# ----------------------------------------------------------------------------------------------------- finding and replacing it
def _eligible(path: str) -> bool:
    parts = PurePosixPath(path).parts
    name = parts[-1] if parts else ""
    if set(parts[:-1]) & SKIP_PARTS or name in SKIP_NAMES:
        return False
    if name.startswith(".env") and name not in (".env.example", ".env.sample", ".env.template"):
        return False                         # secrets files are never read or changed
    return name.endswith(TEXT_EXT) or name in (".env.example", ".env.sample", ".env.template")


def _occurrence(model_id: str) -> re.Pattern:
    return re.compile(r"(?<=[\"'`=:\s/(])" + re.escape(model_id) + r"(?=[\"'`\s,;)}\]]|$)", re.M)


def find_uses(files: dict[str, str], model_id: str) -> dict[str, int]:
    pat = _occurrence(model_id)
    return {p: len(pat.findall(t)) for p, t in files.items() if _eligible(p) and model_id in t and pat.search(t)}


def env_mentions(files: dict[str, str], model_id: str) -> list[str]:
    return [p for p, t in files.items() if PurePosixPath(p).name.startswith(".env") and model_id in t]


def scan_files(files: dict[str, str]) -> list[dict]:
    """Retired model ids written in the code (first scan and every push). [{model, provider, confidence, files}]"""
    hits: dict[str, dict] = {}
    literal = re.compile(r"[\"'`]((?:models/)?[A-Za-z0-9][\w.:/-]{1,80})[\"'`]|(?<=[=:]\s)((?:models/)?[A-Za-z0-9][\w.:/-]{1,80})\s*$|"
                         r"(?<==)((?:models/)?[A-Za-z0-9][\w.:/-]{1,80})\s*$", re.M)
    for path, text in files.items():
        if not _eligible(path) or len(text) > 400_000:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if len(line) > 2000:
                continue
            for m in literal.finditer(line):
                cand = next(g for g in m.groups() if g)
                prov = provider_for(cand)
                if not prov:
                    continue
                conf = is_retired(cand.removeprefix("models/"), prov, line=line) or is_retired(cand, prov, line=line)
                if not conf:
                    continue
                entry = hits.setdefault(cand, {"model": cand, "provider": prov, "confidence": conf, "files": []})
                if f"{path}:{lineno}" not in entry["files"]:
                    entry["files"].append(f"{path}:{lineno}")
    return sorted(hits.values(), key=lambda h: h["model"])


def plan_fix(files: dict[str, str], old: str, new: str) -> tuple[dict[str, str], str, list[str]]:
    """({path: new text}, unified diff, ['file (n×)']) replacing every value-like use of `old` with `new`."""
    pat = _occurrence(old)
    new_files, diffs, places = {}, [], []
    for path, count in sorted(find_uses(files, old).items()):
        before = files[path]
        after = pat.sub(new, before)
        if after == before:
            continue
        new_files[path] = after
        places.append(f"{path} ({count}×)")
        diffs.append("".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                                  fromfile=f"a/{path}", tofile=f"b/{path}")))
    return new_files, "\n".join(diffs), places


# ----------------------------------------------------------------------------------------------------- validating without running code
def _node_parses(text: str, suffix: str) -> bool | None:
    node = shutil.which("node")
    if not node:
        return None
    with tempfile.TemporaryDirectory(prefix="fx-parse-") as tmp:
        ok = False
        for ext in ((suffix,) if suffix in (".mjs", ".cjs") else (".cjs", ".mjs")):
            path = Path(tmp) / ("check" + ext)
            path.write_text(text, encoding="utf-8")
            try:   # --check only parses the file; nothing in it is executed
                if subprocess.run([node, "--check", str(path)], capture_output=True, timeout=20).returncode == 0:
                    ok = True
                    break
            except (OSError, subprocess.TimeoutExpired):
                return None
        return ok


def static_validate(before: dict[str, str], after: dict[str, str]) -> tuple[bool, list[str]]:
    """Parse every changed file (Python, JSON, plain JS). A file that already failed to parse before the change is ignored."""
    notes, ok = [], True
    for path, new in after.items():
        old = before.get(path, "")
        suffix = PurePosixPath(path).suffix.lower()
        if suffix == ".py":
            def parses(t):
                try:
                    ast.parse(t)
                    return True
                except SyntaxError:
                    return False
            good_before, good_after = parses(old), parses(new)
        elif suffix == ".json":
            def loads(t):
                try:
                    json.loads(t)
                    return True
                except ValueError:
                    return False
            good_before, good_after = loads(old), loads(new)
        elif suffix in (".js", ".mjs", ".cjs"):
            good_after = _node_parses(new, suffix)
            if good_after is None:
                notes.append(f"{path}: not parsed (Node.js is not installed here)")
                continue
            good_before = _node_parses(old, suffix)
        else:
            notes.append(f"{path}: text change only")
            continue
        if good_before and not good_after:
            ok = False
            notes.append(f"{path}: would not parse after the change")
        else:
            notes.append(f"{path}: parses")
    return ok, notes


def pr_text(old: str, new: str, provider: str, places: list[str], choice: dict, validation: str, runtime_error: str = "") -> tuple[str, str]:
    title = f"fix: switch retired AI model {old} to {new} [agent-daemon]"
    body = (f"## Agent Daemon fix: retired AI model\n\n"
            f"Your app asks {provider or 'the AI provider'} for the model `{old}`, which is no longer available"
            + (f" (the provider answered: \"{runtime_error[:300]}\")" if runtime_error else "") + ".\n\n"
            f"This pull request switches it to `{new}` everywhere it is set in your code:\n\n"
            + "\n".join(f"- `{p}`" for p in places) + "\n\n"
            f"### How the new model was chosen\n{choice.get('note', '')}\n\n"
            f"### Verification\n{validation}\n\n"
            "Answers from a newer model can differ a little in style and price. Try your chatbot once after merging.\n"
            "No AI tries were used for this fix.")
    return title, body


# ----------------------------------------------------------------------------------------------------- the whole fix, end to end
SCAN_SIGNATURE = "Retired AI model: "             # found by the code scan
RUNTIME_SIGNATURE = "AI model unavailable: "       # reported by a running monitor


def scan_signature(model_id: str) -> str:
    return (SCAN_SIGNATURE + model_id)[:250]


def read_repo(root: Path, limit_bytes: int = 4_000_000) -> dict[str, str]:
    files, total = {}, 0
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_PARTS]
        for name in filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if not (_eligible(rel) or name.startswith(".env")):
                continue
            try:
                size = path.stat().st_size
                if size > 400_000 or total + size > limit_bytes:
                    continue
                files[rel] = path.read_text(encoding="utf-8")
                total += size
            except (OSError, UnicodeDecodeError):
                continue
    return files


def run(claimed: dict, event: dict, *, repo_provider=None, runner=None, pr_opener=None, status_setter=None) -> str | None:
    """Handle one incident if it is a retired-model problem. Returns the outcome, or None when it is not one (the normal
    fix engine then takes it). Every outcome is recorded on the incident: error, diagnosis, fix, PR link, status."""
    import portal_db
    from . import notify, store
    from . import config as fx_config, git_ops, repo_context, sandbox

    incident_id, project_id = claimed["incident_id"], claimed["project_id"]
    message, tb = str(event.get("message", "")), str(event.get("traceback", ""))
    from_scan = claimed.get("source") == "scan" or str(claimed.get("signature", "")).startswith(SCAN_SIGNATURE)
    if from_scan:
        model = str(claimed.get("signature", ""))[len(SCAN_SIGNATURE):].strip()
        found = re.search(r"\(provider: (\w+)\)", message)
        det = {"model": model, "provider": found.group(1) if found else provider_for(model), "evidence": "scan"} if model else None
    else:
        det = detect_error(message, tb)
    if not det:
        return None
    project = store.get_project_row(project_id)
    if not project:
        portal_db.fail_diagnosis(incident_id, project_id, "Project no longer exists")
        return "failed"
    old, provider = det["model"], det["provider"]
    choice = choose_replacement(old, provider)
    new = choice["new"]

    def stage(name, detail=""):
        try:
            portal_db.set_incident_stage(incident_id, name, detail)
        except Exception:
            pass

    def needs_human(reason: str, report: str) -> str:
        portal_db.complete_diagnosis(incident_id, project_id, {"category": "config", "confidence": "high", "root_cause": reason,
                                                               "report": report})
        portal_db.mark_remediation_needs_human(incident_id, project_id, reason)
        stage("needs_human", reason[:250])
        return "needs_human"

    if from_scan and choice.get("old_live") is True:
        portal_db.resolve_incident(incident_id, project_id, f"{old} is still served by the provider: nothing to change")
        return "resolved"
    if from_scan and is_retired(old, provider, line="model") != "certain" and choice.get("old_live") is None:
        return needs_human(f"{old} may be retired soon or already", f"Your code uses the AI model `{old}`, which the provider has "
                           f"retired or announced for retirement. We could not confirm it right now. Recommended replacement: `{new}`.")
    if not new:
        return needs_human(f"{old} is no longer available", f"Your app uses the AI model `{old}`, which the provider no longer serves. "
                           "We do not know a safe replacement for it yet; pick a current model on the provider's website.")
    stage("downloading", f"looking for {old} in {project.get('repo_owner')}/{project.get('repo_name')}")
    cfg = fx_config.load()
    repo_provider = repo_provider or (lambda p: git_ops.repo_snapshot(p, cfg))
    pr_opener = pr_opener or git_ops.open_pr
    with repo_provider(project) as root:
        root = Path(root)
        files = read_repo(root)
        new_files, diff, places = plan_fix(files, old, new)
        env_files = env_mentions(files, old)
        diagnosis = (f"The app calls the AI model `{old}` ({provider or 'AI provider'}), which is no longer available"
                     + (f": {message[:300]}" if not from_scan else " (found by the scan of your code)") + f". Replacement: `{new}`.")
        if not new_files:
            where = (f" It is written in {', '.join(env_files)}, which we never change because it holds secrets." if env_files else "")
            return needs_human(diagnosis, diagnosis + "\n\nThe model name is not written in your code." + where +
                               f"\n\nWhat to do: open your hosting dashboard (Render, Vercel, Netlify, Railway, ...) → Environment "
                               f"variables, find the setting that holds `{old}` (often OPENAI_MODEL, MODEL or AI_MODEL) and change it to "
                               f"`{new}`. Then re-deploy.")
        if (project.get("mode") or claimed.get("mode")) == "report":
            portal_db.complete_diagnosis(incident_id, project_id, {"category": "config", "confidence": "high", "root_cause": diagnosis,
                                                                   "report": diagnosis + "\n\nChange it in: " + ", ".join(places)})
            stage("diagnosed", f"report mode: change {old} to {new}")
            return "diagnosed"
        stage("testing_fix", "checking the change: " + ("sandbox" if runner else "parse check"))
        if runner is not None:
            work = Path(tempfile.mkdtemp(prefix="fx-model-"))
            try:
                patched = work / "repo"
                shutil.copytree(root, patched, ignore=shutil.ignore_patterns(".git"))
                for rel, text in new_files.items():
                    (patched / rel).write_text(text, encoding="utf-8")
                scan = repo_context.scan_repo(root, max_files=int(cfg["sandbox"]["max_repo_files"]))
                profile = sandbox.detect_profiles(root, scan["files"])
                after = sandbox.run_profile(runner, patched, profile)
                if after.system_fault:
                    runner = None
                elif after.passed:
                    ok, validation = True, "The sandbox check (install, build, tests, start-up) passes with the new model name."
                else:
                    before = sandbox.run_profile(runner, root, profile)
                    ok = not before.passed
                    validation = ("The sandbox check already failed before this change for another reason; this change does not make it worse."
                                  if ok else "The sandbox check fails with this change.")
            finally:
                shutil.rmtree(work, ignore_errors=True)
        if runner is None:
            ok, notes = static_validate(files, new_files)
            validation = "Every changed file still parses (" + "; ".join(notes[:6]) + "). The test sandbox was not used."
        if not ok:
            return needs_human(diagnosis, diagnosis + "\n\n" + validation)
    title, body = pr_text(old, new, provider, places, choice, validation, "" if from_scan else message)
    stage("pushing", "fix branch + pull request")
    try:
        import hashlib
        pr = pr_opener(project, bug_id="model-" + hashlib.sha1(f"{old}>{new}".encode()).hexdigest()[:8], incident_id=incident_id,
                       new_files=new_files, diff=diff,
                       title=title, body=body)
    except Exception as exc:
        from monitoring_installer import PublicRepoError
        if isinstance(exc, PublicRepoError):
            portal_db.park_incident_for_gate(incident_id, project_id)
            return "waiting_private"
        portal_db.fail_diagnosis(incident_id, project_id, f"could not open the pull request ({exc.__class__.__name__})", retry_delay_seconds=300)
        return "failed"
    proven = ok and choice.get("verified")
    verify = validation + " " + choice.get("note", "")
    portal_db.complete_diagnosis(incident_id, project_id, {"category": "config", "confidence": "high", "root_cause": diagnosis,
                                                           "report": f"{diagnosis}\n\nFix: {title}\nChanged: {', '.join(places)}"})
    store.record_pr(incident_id, project_id, branch=pr.get("branch", ""), file_path=pr.get("path", ""), diff=diff, pr_url=pr["url"],
                    pr_number=int(pr["number"]), verification_text=verify)
    if proven and pr.get("head_sha"):
        try:
            (status_setter or __import__("push_watch").set_commit_status)(
                {**project, "branch": pr["head_sha"], "project_id": project_id}, pr["head_sha"], "success",
                f"Agent Daemon: {old} → {new}, checked")
        except Exception:
            pass
    else:
        store.block_automerge(incident_id)
    stage("pr_open", "review and merge the pull request on GitHub")
    try:
        notify.user_pr_opened(project["user_id"], project.get("name", ""), pr["url"], verify)
    except Exception:
        pass
    return "pr_opened"
