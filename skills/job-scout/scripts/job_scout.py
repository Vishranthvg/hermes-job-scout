#!/usr/bin/env python3
"""Scan public job APIs, score postings against a profile, and print new matches.

This script is the mechanical half of the Hermes job-scout skill. It only talks
to sources that publish a documented public feed or JSON API. It does not
scrape LinkedIn or Indeed. Run it on its own for a dry run, or let a Hermes
cron job invoke it and deliver the result to Telegram.

Default paths (overridable by flags or environment variables):
  profile:  ~/.hermes/job-scout/profile.yaml
  state:    ~/.hermes/job-scout/seen.json
  last run: ~/.hermes/job-scout/last_run.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Iterable, Optional

# Allow `python3 scripts/job_scout.py` from any cwd.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _http import (  # noqa: E402
    DEFAULT_TIMEOUT,
    FetchError,
    is_seen,
    job_keys,
    load_seen,
    mark_seen,
    save_json,
)
from _models import Job, Profile, ScoreBreakdown, SourceReport  # noqa: E402
from _score import score_job  # noqa: E402
from _sources import OPTIONAL_KEY_SOURCES, SOURCE_FETCHERS  # noqa: E402
from _text import now_iso  # noqa: E402
from _yaml import load_yaml_file  # noqa: E402

VERSION = "1.0.0"
HOMEDIR = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
DEFAULT_PROFILE = HOMEDIR / "job-scout" / "profile.yaml"
DEFAULT_STATE = HOMEDIR / "job-scout" / "seen.json"
DEFAULT_LAST_RUN = HOMEDIR / "job-scout" / "last_run.json"


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def load_profile(path: Path, resume_override: Optional[Path] = None) -> Profile:
    if not path.exists():
        raise FileNotFoundError(
            f"Profile not found: {path}\n"
            "Copy profile.example.yaml to that path and edit it."
        )
    raw = load_yaml_file(path) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Profile {path} must be a YAML mapping.")

    resume_path = resume_override
    if resume_path is None and raw.get("resume_path"):
        resume_path = Path(str(raw["resume_path"])).expanduser()
        if not resume_path.is_absolute():
            resume_path = (path.parent / resume_path).resolve()
    resume_text = ""
    if resume_path and resume_path.exists():
        resume_text = resume_path.read_text(encoding="utf-8", errors="replace")
    elif resume_path:
        raise FileNotFoundError(f"Resume not found: {resume_path}")

    sources_raw = raw.get("sources") or {}
    if isinstance(sources_raw, list):
        sources = {str(s): True for s in sources_raw}
    elif isinstance(sources_raw, dict):
        sources = {str(k): _as_bool(v, True) for k, v in sources_raw.items()}
    else:
        sources = {name: True for name in SOURCE_FETCHERS}

    ats = raw.get("ats_boards") or {}
    ats_boards: dict[str, list[str]] = {}
    if isinstance(ats, dict):
        for key, val in ats.items():
            ats_boards[str(key)] = _as_list(val)

    salary_floor = raw.get("salary_floor")
    if salary_floor is not None and salary_floor != "":
        salary_floor = int(salary_floor)
    else:
        salary_floor = None

    return Profile(
        target_titles=_as_list(raw.get("target_titles")),
        locations=_as_list(raw.get("locations")),
        remote_ok=_as_bool(raw.get("remote_ok"), True),
        salary_floor=salary_floor,
        salary_currency=str(raw.get("salary_currency") or "CAD").upper(),
        must_haves=_as_list(raw.get("must_haves")),
        deal_breakers=_as_list(raw.get("deal_breakers")),
        keywords=_as_list(raw.get("keywords")),
        resume_path=resume_path,
        resume_text=resume_text,
        max_results=int(raw.get("max_results") or 10),
        min_score=int(raw.get("min_score") or 25),
        schedule_time=str(raw.get("schedule_time") or "08:00"),
        timezone=str(raw.get("timezone") or ""),
        sources=sources,
        ats_boards=ats_boards,
        himalayas_pages=int(raw.get("himalayas_pages") or 3),
        himalayas_page_size=int(raw.get("himalayas_page_size") or 20),
        arbeitnow_pages=int(raw.get("arbeitnow_pages") or 1),
        update_seen_on_scan=_as_bool(raw.get("update_seen_on_scan"), False),
        origin_dir=path.parent,
    )


def collect_jobs(
    profile: Profile,
    enabled: Optional[Iterable[str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
    verbose: bool = False,
) -> tuple[list[Job], list[SourceReport]]:
    names = list(enabled) if enabled is not None else [
        name for name, on in (profile.sources or {n: True for n in SOURCE_FETCHERS}).items() if on
    ]
    order = [n for n in SOURCE_FETCHERS if n in names]
    for n in names:
        if n not in SOURCE_FETCHERS:
            raise SystemExit(f"Unknown source {n!r}. Known: {', '.join(SOURCE_FETCHERS)}")
        if n not in order:
            order.append(n)

    collected: list[Job] = []
    reports: list[SourceReport] = []
    for name in order:
        report = SourceReport(name=name)
        fetcher = SOURCE_FETCHERS[name]
        if verbose:
            print(f"# fetching {name}...", file=sys.stderr)
        try:
            batch = fetcher(profile, timeout)
        except FetchError as exc:
            if exc.status == 0:
                report.skipped = str(exc)
            else:
                report.error = str(exc)
            reports.append(report)
            if verbose:
                print(f"# {name}: {exc}", file=sys.stderr)
            continue
        except Exception as exc:  # noqa: BLE001 - isolate a bad source
            report.error = f"unexpected error: {exc}"
            reports.append(report)
            if verbose:
                print(f"# {name}: {report.error}", file=sys.stderr)
            continue
        warnings = getattr(fetcher, "last_warnings", None)
        if warnings:
            report.error = "partial: " + "; ".join(warnings)
        report.fetched = len(batch)
        collected.extend(batch)
        reports.append(report)
    return collected, reports


def _dedupe_batch(jobs: list[Job]) -> list[Job]:
    seen: set[str] = set()
    unique: list[Job] = []
    for job in jobs:
        keys = job_keys(job)
        if any(k in seen for k in keys):
            continue
        for k in keys:
            seen.add(k)
        if not job.title or not job.url:
            continue
        unique.append(job)
    return unique


def rank_jobs(
    jobs: list[Job], profile: Profile, seen: dict[str, Any]
) -> tuple[list[tuple[Job, ScoreBreakdown]], int, int]:
    unique = _dedupe_batch(jobs)
    already = 0
    ranked: list[tuple[Job, ScoreBreakdown]] = []
    excluded = 0
    for job in unique:
        if is_seen(job, seen):
            already += 1
            continue
        breakdown = score_job(job, profile)
        if breakdown.excluded or breakdown.total < profile.min_score:
            excluded += 1
            continue
        ranked.append((job, breakdown))
    ranked.sort(key=lambda pair: (-pair[1].total, pair[0].title.lower()))
    return ranked[: max(1, profile.max_results)], already, excluded


def format_digest(
    matches: list[tuple[Job, ScoreBreakdown]],
    reports: list[SourceReport],
    profile: Profile,
    already: int,
    excluded: int,
    fetched: int,
) -> str:
    titles = ", ".join(profile.target_titles[:3]) or "your target roles"
    loc = ", ".join(profile.locations[:3]) or "your locations"
    failed = [r for r in reports if r.error or r.skipped]
    lines: list[str] = []
    if not matches:
        lines.append("NO_NEW_MATCHES")
        lines.append(
            f"Job scout found 0 new postings above the score floor "
            f"(min_score={profile.min_score}) for {titles} ({loc})."
        )
        lines.append(
            f"Fetched {fetched} jobs from {len(reports)} source(s); "
            f"{already} already seen; {excluded} dropped by filters."
        )
    else:
        noun = "match" if len(matches) == 1 else "matches"
        lines.append(f"Job scout: {len(matches)} new {noun} for {titles} ({loc}).")
        lines.append(
            f"Fetched {fetched} jobs; {already} already seen; "
            f"{excluded} dropped by filters."
        )
        lines.append("")
        for i, (job, bd) in enumerate(matches, 1):
            loc_bit = job.location or ("remote" if job.remote else "")
            meta = " | ".join(
                p for p in [f"score {bd.total}", loc_bit, job.source, job.salary_text] if p
            )
            lines.append(f"{i}. {job.title} at {job.company}")
            lines.append(f"   {meta}")
            lines.append(f"   Why: {bd.reason}")
            lines.append(f"   {job.url}")
            lines.append("")
    if failed:
        lines.append("Sources:")
        for r in reports:
            status = f"{r.fetched} fetched"
            if r.skipped:
                status = r.skipped
            elif r.error:
                status = f"{status}; {r.error}"
            lines.append(f"  - {r.name}: {status}")
    return "\n".join(lines).rstrip() + "\n"


def matches_to_json(
    matches: list[tuple[Job, ScoreBreakdown]],
    reports: list[SourceReport],
    already: int,
    excluded: int,
) -> dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "already_seen": already,
        "excluded": excluded,
        "matches": [
            {
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "remote": job.remote,
                "url": job.url,
                "source": job.source,
                "source_id": job.source_id,
                "salary": job.salary_text,
                "score": bd.total,
                "reason": bd.reason,
                "published_at": job.published_at,
                "keys": job_keys(job),
            }
            for job, bd in matches
        ],
        "sources": [asdict(r) for r in reports],
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Scan public job sources and print new matches for a Hermes job-scout run.",
    )
    p.add_argument("--profile", type=Path, default=None, help="Path to profile.yaml")
    p.add_argument("--state", type=Path, default=None, help="Path to seen.json")
    p.add_argument("--last-run", type=Path, default=None, help="Path to last_run.json")
    p.add_argument("--resume", type=Path, default=None, help="Override resume text path")
    p.add_argument("--dry-run", action="store_true", help="Scan and print; do not write state files")
    p.add_argument("--update-seen", action="store_true", help="Mark last_run jobs as seen; do not scan")
    p.add_argument(
        "--update-seen-after-scan",
        action="store_true",
        help="Scan, print, and mark those matches as seen (for --no-agent cron jobs)",
    )
    p.add_argument("--json", action="store_true", dest="as_json", help="Print JSON instead of text")
    p.add_argument("--max-results", type=int, default=None, help="Override profile max_results")
    p.add_argument("--min-score", type=int, default=None, help="Override profile min_score")
    p.add_argument("--sources", default=None, help="Comma-separated source names to run")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--version", action="version", version=f"job-scout {VERSION}")
    return p


def _resolve_paths(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    profile = Path(os.environ.get("JOB_SCOUT_PROFILE") or args.profile or DEFAULT_PROFILE).expanduser()
    state = Path(os.environ.get("JOB_SCOUT_STATE") or args.state or DEFAULT_STATE).expanduser()
    last_run = Path(os.environ.get("JOB_SCOUT_LAST_RUN") or args.last_run or DEFAULT_LAST_RUN).expanduser()
    return profile, state, last_run


def _jobs_from_last_run(path: Path) -> list[Job]:
    if not path.exists():
        raise FileNotFoundError(f"No last_run file at {path}. Run a scan first.")
    data = json.loads(path.read_text(encoding="utf-8"))
    jobs = []
    for item in data.get("matches") or []:
        jobs.append(
            Job(
                source=item.get("source") or "",
                source_id=item.get("source_id") or "",
                title=item.get("title") or "",
                company=item.get("company") or "",
                url=item.get("url") or "",
                location=item.get("location") or "",
            )
        )
    return jobs


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    profile_path, state_path, last_run_path = _resolve_paths(args)

    if args.update_seen and not args.update_seen_after_scan:
        seen = load_seen(state_path)
        jobs = _jobs_from_last_run(last_run_path)
        for job in jobs:
            mark_seen(seen, job)
        if not args.dry_run:
            save_json(state_path, seen)
        print(f"Marked {len(jobs)} posting(s) as seen in {state_path}")
        return 0

    try:
        profile = load_profile(profile_path, resume_override=args.resume)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.max_results is not None:
        profile = replace(profile, max_results=args.max_results)
    if args.min_score is not None:
        profile = replace(profile, min_score=args.min_score)

    enabled = None
    if args.sources:
        enabled = [s.strip() for s in args.sources.split(",") if s.strip()]

    seen = load_seen(state_path)
    jobs, reports = collect_jobs(profile, enabled=enabled, timeout=args.timeout, verbose=args.verbose)
    matches, already, excluded = rank_jobs(jobs, profile, seen)
    fetched = sum(r.fetched for r in reports)

    payload = matches_to_json(matches, reports, already, excluded)
    text = format_digest(matches, reports, profile, already, excluded, fetched)

    if args.as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        sys.stdout.write(text)

    if not args.dry_run:
        save_json(last_run_path, payload)
        commit = args.update_seen_after_scan or profile.update_seen_on_scan
        if commit:
            for job, _bd in matches:
                mark_seen(seen, job)
            save_json(state_path, seen)

    hard = [
        r for r in reports
        if r.error and not r.fetched and not r.skipped and r.name not in OPTIONAL_KEY_SOURCES
    ]
    enabled_count = len([r for r in reports if not r.skipped])
    if enabled_count and len(hard) == enabled_count:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
