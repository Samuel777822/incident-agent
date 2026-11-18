"""Removes the app's own old scratch folders from temporary disk. Off unless TEMP_CLEANUP_ENABLED=1.

Only a folder that passes every check is removed:
  * it sits directly inside the temp folder (or FIXENGINE_SCRATCH) and its name starts with a prefix this app creates,
  * it is a real folder (not a symbolic link) owned by the user running the app,
  * nothing inside it changed for TEMP_CLEANUP_MAX_AGE_HOURS, so a case still working in it is left alone.
Database records, dumps and every other file are out of reach. Each decision is logged.
"""
from __future__ import annotations

import logging
import os
import shutil
import stat
import tempfile
import time
from pathlib import Path

LOG = logging.getLogger("temp_cleanup")

OWNED_PREFIXES = ("fx-", "incident-agent-")
MIN_AGE_HOURS = 6.0
DEFAULT_AGE_HOURS = 24.0
DEFAULT_INTERVAL_SECONDS = 3600
MIN_INTERVAL_SECONDS = 300


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def enabled() -> bool:
    return _flag("TEMP_CLEANUP_ENABLED")


def dry_run() -> bool:
    return _flag("TEMP_CLEANUP_DRY_RUN")


def max_age_hours() -> float:
    try:
        hours = float(os.getenv("TEMP_CLEANUP_MAX_AGE_HOURS", "") or DEFAULT_AGE_HOURS)
    except ValueError:
        hours = DEFAULT_AGE_HOURS
    return max(MIN_AGE_HOURS, hours)


def interval_seconds() -> int:
    raw = os.getenv("TEMP_CLEANUP_INTERVAL_SECONDS", "").strip()
    seconds = int(raw) if raw.isdigit() else DEFAULT_INTERVAL_SECONDS
    return max(MIN_INTERVAL_SECONDS, seconds)


def _roots() -> list[Path]:
    roots = [Path(tempfile.gettempdir())]
    scratch = os.getenv("FIXENGINE_SCRATCH", "").strip()
    if scratch and Path(scratch) not in roots:
        roots.append(Path(scratch))
    return roots


def _owned_by_me(info: os.stat_result) -> bool:
    return not hasattr(os, "getuid") or info.st_uid == os.getuid()


def _newest_change_and_size(folder: Path) -> tuple[float, int]:
    """The latest modification time anywhere in the folder and its size. Symbolic links are never followed."""
    newest, size = folder.lstat().st_mtime, 0
    for base, dirs, files in os.walk(folder, followlinks=False):
        for name in dirs + files:
            info = os.lstat(os.path.join(base, name))
            newest = max(newest, info.st_mtime)
            if stat.S_ISREG(info.st_mode):
                size += info.st_size
    return newest, size


def _candidates(root: Path):
    try:
        entries = list(os.scandir(root))
    except OSError:
        return
    for entry in entries:
        try:
            if not entry.name.startswith(OWNED_PREFIXES) or entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                continue
            if _owned_by_me(entry.stat(follow_symlinks=False)):
                yield Path(entry.path)
        except OSError:                 # it vanished while we looked (a finished case removed its own folder)
            continue


def sweep(now: float | None = None) -> dict:
    """One pass. Never raises: a cleanup problem must not stop the worker."""
    report = {"enabled": enabled(), "dry_run": dry_run(), "removed": 0, "would_remove": 0, "kept": 0, "errors": 0, "bytes": 0}
    if not report["enabled"]:
        return report
    now = time.time() if now is None else now
    cutoff = now - max_age_hours() * 3600
    for root in _roots():
        for folder in _candidates(root):
            try:
                newest, size = _newest_change_and_size(folder)
                if newest >= cutoff:
                    report["kept"] += 1
                    continue
                age_hours = (now - newest) / 3600
                if report["dry_run"]:
                    report["would_remove"] += 1
                    report["bytes"] += size
                    LOG.info("Temp cleanup (dry run) would remove %s (%s bytes, unchanged for %.1f h)", folder.name, size, age_hours)
                    continue
                shutil.rmtree(folder)
                report["removed"] += 1
                report["bytes"] += size
                LOG.info("Temp cleanup removed %s (%s bytes, unchanged for %.1f h)", folder.name, size, age_hours)
            except OSError as exc:
                report["errors"] += 1
                LOG.warning("Temp cleanup skipped %s (%s)", folder.name, exc.__class__.__name__)
    try:
        usage = shutil.disk_usage(tempfile.gettempdir())
        report["disk_used_percent"] = round(usage.used * 100 / usage.total, 1) if usage.total else 0.0
    except OSError:
        report["disk_used_percent"] = None
    LOG.info("Temp cleanup finished: %s", report)
    return report
