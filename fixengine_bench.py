"""Run real bugs through the real engine, either as a FREE dry run (no model calls at all) or as a PAID run under a hard rupee budget.

    python bench/make_all_cases.py                           # (once) writes the sample repos: Python, Java, JavaScript, TypeScript, static site
    python -m fixengine.provider_check                       # free: are the keys, model ids and provider rules OK?
    python fixengine_bench.py --dry-run --sandbox docker --per-language 1     # free: sandbox + wiring, NO model call is possible
    python fixengine_bench.py --paid --budget 400 --credits 500 --pause-at 300    # the real test: spends money, asks you at Rs 300

You must choose --dry-run or --paid. There is no default, so a run can never spend money by accident.

--dry-run   forces FIXENGINE_DRY_RUN=1 before anything is imported. Every provider adapter then refuses to make a network call, whatever API keys
            are in your shell or in .env. Each case runs the real sandbox baseline and stops at the point where the model would be called.
--paid      real model calls. The run stops by itself at the global budget B, each bug has its own rupee cap, Opus (Extra) is OFF unless
            you pass --allow-opus, it pauses at --pause-at so you can decide, and it stops early when the provider is failing every case.
            Nothing is pushed to GitHub: PRs are only printed.
Use --sandbox local_unsafe ONLY on your own throw-away machine with your own sample repos: it runs the repo's tests directly.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

PROVIDER_KEYS = ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY")
EMAIL_KEYS = ("BREVO_API_KEY", "RESEND_API_KEY", "SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD")


def lang_of(case_name: str) -> str:
    """java_*, js_*, ts_*, static_* cases are named by language; every other case is Python (py_* and the original three)."""
    first = case_name.split("_")[0]
    return first if first in ("java", "js", "ts", "static") else "python"


def load_cases(root: Path, only: str | None):
    cases = []
    for d in sorted(p for p in root.iterdir() if p.is_dir() and (p / "repo").is_dir() and (p / "incident.json").is_file()):
        if only and only not in d.name:
            continue
        cases.append((d.name, d / "repo", json.loads((d / "incident.json").read_text())))
    return cases


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", default=str(Path(__file__).parent / "bench" / "cases"))
    ap.add_argument("--only", help="run only cases whose name contains this (e.g. java_, js_, ts_, static_, py_)")
    ap.add_argument("--language", choices=["python", "java", "js", "ts", "static"], help="run only the cases of one language")
    ap.add_argument("--per-language", type=int, default=0, help="run only the first N cases of each language (keeps a paid run cheap)")
    ap.add_argument("--limit", type=int, default=0, help="run at most this many cases")
    ap.add_argument("--dry-run", action="store_true", help="FREE: no model call is possible; runs the sandbox baseline and checks the wiring")
    ap.add_argument("--paid", action="store_true", help="PAID: make real model calls (you must choose this explicitly)")
    ap.add_argument("--budget", type=float, default=400.0, help="global budget B in rupees (kill switch)")
    ap.add_argument("--credits", type=float, default=500.0, help="credits you deposited, in rupees")
    ap.add_argument("--pause-at", type=float, default=300.0, help="paid run: stop and ask you when the cumulative spend reaches this many rupees")
    ap.add_argument("--spent-before", type=float, default=0.0, help="rupees already spent by earlier paid runs, so budget and pause apply cumulatively")
    ap.add_argument("--per-bug-cap", type=float, default=60.0)
    ap.add_argument("--usd-inr", type=float, default=90.0)
    ap.add_argument("--sandbox", choices=["docker", "remote", "local_unsafe"], default="docker")
    ap.add_argument("--allow-opus", action="store_true", help="paid run: allow the Extra (Opus) mode. Off by default.")
    ap.add_argument("--no-opus", action="store_true", help="kept for old command lines; Opus is already off unless --allow-opus")
    ap.add_argument("--keep-db", action="store_true", help="keep the run's private SQLite database and print its path (kept automatically when a fault happens)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    if args.dry_run == args.paid:
        print("Choose exactly one mode:\n  --dry-run   free, no model call is possible\n  --paid      real model calls, real money (hard budget, asks you at --pause-at)")
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="fx-bench-"))
    db_path = tmp / "bench.sqlite3"
    os.environ["PORTAL_DB_PATH"] = str(db_path)           # a private database for this run only (not your normal portal.db)
    os.environ["FIXENGINE_SANDBOX_MODE"] = args.sandbox
    if args.sandbox == "local_unsafe":
        os.environ["FIXENGINE_ALLOW_UNSAFE_LOCAL"] = "1"
    if args.dry_run:
        os.environ["FIXENGINE_DRY_RUN"] = "1"             # set BEFORE importing the engine: even a key in .env cannot make a call now
    else:
        os.environ.pop("FIXENGINE_DRY_RUN", None)
    sys.path.insert(0, str(Path(__file__).parent))
    import portal_db
    from fixengine import adapters as fx_adapters, config as fx_config, orchestrator, store    # importing fixengine loads .env
    from fixengine.guard import Guard
    if args.dry_run:
        for key in PROVIDER_KEYS:                           # belt and braces: .env was just loaded, so remove its keys again
            os.environ.pop(key, None)
    for key in EMAIL_KEYS:                                  # a benchmark never emails anyone (admins, customers), whatever .env holds
        os.environ.pop(key, None)

    lg = logging.getLogger("fixengine")                    # show why a case waits (for example "sandbox unavailable: Docker ...")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("   [engine] %(message)s"))
    lg.addHandler(handler)
    lg.setLevel(logging.INFO)
    lg.propagate = False

    cases = load_cases(Path(args.cases), args.only)
    if args.language:
        cases = [c for c in cases if lang_of(c[0]) == args.language]
    if args.per_language:
        seen: dict[str, int] = {}
        picked = []
        for item in cases:
            lang = lang_of(item[0])
            if seen.get(lang, 0) < args.per_language:
                picked.append(item)
                seen[lang] = seen.get(lang, 0) + 1
        cases = picked
    if args.limit:
        cases = cases[:args.limit]
    if not cases:
        print("No cases found. Run: python bench/make_all_cases.py")
        return 2
    worst = len(cases) * args.per_bug_cap
    remaining_budget = max(0.0, args.budget - args.spent_before)
    remaining_credits = max(0.0, args.credits - args.spent_before)
    pause_at = max(0.0, args.pause_at - args.spent_before)
    mode_text = "DRY RUN: no model call is possible, Rs 0 can be spent" if args.dry_run else \
        f"PAID RUN: real model calls. Budget Rs {args.budget:.0f} (Rs {args.spent_before:.2f} already spent), pause at Rs {args.pause_at:.0f}, Opus {'ON' if args.allow_opus else 'OFF'}"
    print(mode_text)
    print(f"{len(cases)} cases, per-bug cap Rs {args.per_bug_cap}: worst case Rs {worst:.0f} against Rs {remaining_credits:.0f} credits (B = Rs {remaining_budget:.0f}).")
    if args.paid and worst > remaining_credits and not args.force:
        print("The theoretical worst case is above your credits. The global budget still stops the run, but pass --force to continue.")
        return 2

    cfg = fx_config.load()
    cfg["budget"].update({"b_inr": remaining_budget, "credits_inr": remaining_credits})
    cfg["caps"].update({"per_bug_cost_inr": args.per_bug_cap, "tries_per_hour_per_user": 500, "new_bugs_per_hour_per_user": 500,
                        "cooldown_after_failures": 0, "user_month_ceiling_inr": remaining_credits})
    cfg["usd_inr"] = args.usd_inr
    cfg["sandbox"]["mode"] = args.sandbox
    cfg["warn_at"].update({"haiku": 0, "sonnet": 0, "opus": 0})
    cfg["warn_every_use"]["opus"] = False
    if args.paid:
        cfg["quotas"].update({"haiku": 200, "sonnet": 60})
        if not args.allow_opus:
            cfg["quotas"]["opus"] = 0
    # Show the route each tier will really use BEFORE anything runs, so nothing is a surprise (keys are never printed).
    adapters = fx_adapters.build_adapters(cfg)
    print("Routes:")
    for tier in fx_config.TIERS:
        ad = adapters[tier]
        note = "" if ad.configured() else "   (not configured: no key, this tier will not be used)"
        if tier == "opus" and args.paid and not args.allow_opus:
            note = "   (switched off for this run)"
        print(f"  {tier:6s} {fx_config.USER_MODE_NAMES[tier]:10s} -> {ad.describe()}{note}")
    if args.paid and not any(adapters[t].configured() for t in fx_config.TIERS):
        print("\nNo AI provider is configured (no API key found in the environment or .env). Nothing was run.\nRun: python -m fixengine.provider_check")
        shutil.rmtree(tmp, ignore_errors=True)
        return 2

    portal_db.init_db()
    user_id = portal_db.create_user("bench@example.com", "x", "Bench")
    guard = Guard(cfg)
    prs: list = []

    def fake_pr(project, **kw):
        prs.append(kw)
        return {"url": "https://example.invalid/pr/1", "number": 1, "branch": "bench", "path": ", ".join(kw["new_files"]), "diff": kw["diff"], "ci_status": "pending"}

    results = []
    any_fault = False
    consecutive_fault_cases = 0
    stop_note = ""
    exit_code = 0
    for name, repo, incident in cases:
        if guard.level() >= 4:
            stop_note = f"global budget reached (Rs {guard.month_spend():.2f} of Rs {remaining_budget:.0f})"
            print(f"\nStopping: {stop_note}.")
            break
        if args.paid and guard.month_spend() >= pause_at:
            stop_note = (f"paused at Rs {guard.month_spend() + args.spent_before:.2f} cumulative (pause point Rs {args.pause_at:.0f}). "
                         f"To continue after you have checked the results, re-run with --spent-before {guard.month_spend() + args.spent_before:.2f} "
                         f"and a higher --pause-at")
            print(f"\nPAUSED: {stop_note}.")
            exit_code = 4
            break
        project_id = portal_db.create_project(user_id, name=name, repo_owner="bench", repo_name=name, branch="main", mode="pr",
                                              token_ciphertext="x", ingest_key_hash="k-" + name, ai_consent_at="2026-01-01T00:00:00+00:00")
        store._run("UPDATE projects SET active_until='2099-01-01T00:00:00+00:00' WHERE id=?", (project_id,))

        @contextlib.contextmanager
        def provider(project, repo=repo):
            work = Path(tempfile.mkdtemp(prefix="fx-bench-repo-"))
            try:
                shutil.copytree(repo, work / "r")
                yield work / "r"
            finally:
                shutil.rmtree(work, ignore_errors=True)
        incident_id, _ = portal_db.ingest_event(project_id, timestamp="2020-01-01T00:00:00Z", level="ERROR", message=incident["message"],
                                                traceback=incident["traceback"], signature=f"bench:{name}")
        engine = orchestrator.Engine(cfg, adapters=adapters, repo_provider=provider, commits_provider=lambda p: "", pr_opener=fake_pr, guard=guard)
        claimed = portal_db.claim_next_incident(min_occurrences=1, min_age_seconds=0)
        started = time.time()
        outcome = engine.handle_incident(claimed)
        bug = store.get_bug_by_incident(incident_id)
        attempts = store.list_attempts(bug["id"]) if bug else []
        real = [a for a in attempts if a["result"] != "system_fault"]
        faults = [a for a in attempts if a["result"] == "system_fault"]
        results.append({"case": name, "outcome": outcome,
                        "tries": [{"tier": a["tier"], "model": a["model"], "result": a["result"], "error": a["error_summary"] if a["result"] == "system_fault" else ""}
                                  for a in attempts],
                        "model_attempts": len(real), "faults": len(faults), "baseline_failing": (bug or {}).get("baseline_failing"),
                        "cost_inr": round(sum(a["cost_inr"] or 0 for a in attempts), 2), "seconds": round(time.time() - started, 1),
                        "tokens_in": sum(a["tokens_in"] or 0 for a in attempts), "tokens_out": sum(a["tokens_out"] or 0 for a in attempts),
                        "cache_read": sum(a["cache_read"] or 0 for a in attempts), "stop_reason": (bug or {}).get("stop_reason", ""),
                        "baseline_output_tail": ((bug or {}).get("baseline_output") or "")[-400:]})
        r = results[-1]
        print(f"\n[{name}] {outcome}  Rs {r['cost_inr']}  {r['seconds']}s  tokens in/out {r['tokens_in']}/{r['tokens_out']}  "
              f"model attempts {r['model_attempts']}, faults {r['faults']}")
        if args.dry_run:
            bf = r["baseline_failing"]
            shown = "no result" if bf is None else ("failing, count not parsed" if bf == -1 else ("passing already?" if bf == 0 else f"{bf} failing"))
            print(f"   sandbox baseline: {shown};  model calls made: 0")
            if bf == -1:
                tail = " | ".join(ln.strip() for ln in r["baseline_output_tail"].splitlines()[-3:] if ln.strip())
                print(f"   baseline output ends: {tail[:200]}")
        for a in attempts:
            line = f"   try: {a['tier']} [{a['model']}] -> {a['result']}"
            print(line)
            if a["result"] == "system_fault":
                print(f"        FAULT: {a['error_summary']}")
        if not attempts and not args.dry_run:
            print("   no model calls")
        if outcome == "waiting" and not faults:
            print("   waiting = a fault happened before any model call (see the [engine] line above, usually the sandbox).")
        if r["stop_reason"]:
            print("   stopped:", r["stop_reason"])
        if outcome == "pr_opened":
            print("   diff:\n" + "\n".join("     " + ln for ln in prs[-1]["diff"].splitlines()[:14]))
        any_fault = any_fault or bool(faults) or outcome == "waiting"
        # Paid-run safety: if the provider fails every case, stop spending time and money and show the cause.
        if args.paid:
            consecutive_fault_cases = consecutive_fault_cases + 1 if (faults and not real) else 0
            if consecutive_fault_cases >= 2:
                stop_note = "the provider failed every attempt in 2 cases in a row (see FAULT lines). Stopped so nothing more is spent."
                print(f"\nSTOPPED: {stop_note}\nRun: python -m fixengine.provider_check")
                exit_code = 3
                break

    print("\n=== summary ===")
    for row in store.spend_by_tier():
        print(f"{row['tier']:7s} {row['model']:30s} model attempts {row['tries']:3d}  faults {row['faults']:3d}  passes {row['passes'] or 0}"
              f"  in {row['tokens_in']}  out {row['tokens_out']}  Rs {row['spend']:.2f}")
    total = guard.month_spend()
    if args.dry_run:
        reached = sum(1 for r in results if r["outcome"] == "dry_run")
        counted = sum(1 for r in results if (r["baseline_failing"] or 0) >= 1)
        unparsed = [r["case"] for r in results if r["baseline_failing"] == -1]
        clean = [r["case"] for r in results if r["baseline_failing"] == 0 or r["baseline_failing"] is None]
        print(f"DRY RUN: {reached}/{len(results)} cases reached the model-call step. 0 model calls were made, Rs 0.00 spent.")
        print(f"Sandbox baseline reproduced the planted failure with a counted number of failing tests in {counted}/{len(results)} cases.")
        if unparsed:
            print(f"  Tests failed but the failing count could not be read in: {', '.join(unparsed)}. Usually fine for static sites; for others check the 'baseline output ends' "
                  "line (a missing tool or image looks the same as a real failure).")
        if clean:
            print(f"  WARNING: the baseline did not fail (the planted bug was not reproduced) in: {', '.join(clean)}")
            exit_code = exit_code or 1
        if reached != len(results):
            print("Some cases did NOT get that far: read the [engine] and FAULT lines above (usually Docker or a missing image).")
            exit_code = exit_code or 1
    else:
        solved = sum(1 for r in results if r["outcome"] == "pr_opened")
        print(f"TOTAL Rs {total:.2f} this run, Rs {total + args.spent_before:.2f} cumulative, of Rs {args.budget:.0f} budget (Rs {args.credits:.0f} credits). "
              f"Solved {solved}/{len(results)}.")
    report = Path("bench_report.json")
    report.write_text(json.dumps({"mode": "dry_run" if args.dry_run else "paid", "results": results, "total_inr": round(total, 2),
                                  "spent_before_inr": args.spent_before, "budget_inr": args.budget, "stopped": stop_note}, indent=2))
    print(f"Per-case detail in {report}." + ("" if args.dry_run else " Compare the real tokens above with the plan's estimates before trusting the router's cost numbers."))
    if args.keep_db or any_fault:
        print(f"Run database kept at: {db_path}\n  Inspect it with:  PORTAL_DB_PATH=\"{db_path}\"  (PowerShell: $env:PORTAL_DB_PATH=\"{db_path}\")  then query fx_attempts")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
