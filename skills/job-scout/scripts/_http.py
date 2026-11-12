"""HTTP helper and seen-list persistence."""
from __future__ import annotations

import hashlib
import http.client
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from _models import Job
from _text import now_iso, normalize_url

USER_AGENT = "hermes-job-scout/1.0 (public job search assistant)"
DEFAULT_TIMEOUT = 25


class FetchError(Exception):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def http_get(
    url: str,
    headers: Optional[dict[str, str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[int, str, bytes]:
    combined = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        combined.update(headers)
    req = urllib.request.Request(url, headers=combined, method="GET")
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                ctype = resp.headers.get("Content-Type", "")
                return resp.status, ctype, body
        except http.client.IncompleteRead as exc:
            last_err = exc
            if exc.partial:
                # Retry; a partial body is not trusted as a complete payload.
                pass
        except urllib.error.HTTPError as exc:
            try:
                exc.read()
            except Exception:
                pass
            raise FetchError(f"HTTP {exc.code} for {url}", status=exc.code) from exc
        except urllib.error.URLError as exc:
            last_err = exc
        except TimeoutError as exc:
            last_err = exc
        if attempt < 2:
            time.sleep(0.6 * (attempt + 1))
            continue
        break
    raise FetchError(f"network error for {url}: {last_err}") from last_err


def http_get_json(
    url: str,
    headers: Optional[dict[str, str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Any:
    _status, _ctype, body = http_get(url, headers=headers, timeout=timeout)
    try:
        return json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise FetchError(f"invalid JSON from {url}: {exc}") from exc


def job_keys(job: Job) -> list[str]:
    keys: list[str] = []
    url = normalize_url(job.url)
    if url:
        keys.append("url:" + url)
    if job.source and job.source_id:
        keys.append(f"id:{job.source}:{job.source_id}")
    company = re.sub(r"[^a-z0-9]+", " ", (job.company or "").lower())
    title = re.sub(r"[^a-z0-9]+", " ", (job.title or "").lower())
    fp = " ".join(company.split()) + "|" + " ".join(title.split())
    if fp.strip() != "|":
        digest = hashlib.sha1(fp.encode("utf-8")).hexdigest()[:16]
        keys.append("fp:" + digest)
    return keys


def load_seen(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "items": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "items": {}}
    if not isinstance(data, dict):
        return {"version": 1, "items": {}}
    data.setdefault("version", 1)
    data.setdefault("items", {})
    return data


def is_seen(job: Job, seen: dict[str, Any]) -> bool:
    items = seen.get("items") or {}
    return any(k in items for k in job_keys(job))


def mark_seen(seen: dict[str, Any], job: Job, shown_at: Optional[str] = None) -> None:
    items = seen.setdefault("items", {})
    stamp = shown_at or now_iso()
    record = {
        "url": job.url,
        "title": job.title,
        "company": job.company,
        "source": job.source,
        "first_seen": stamp,
        "shown_at": stamp,
    }
    for key in job_keys(job):
        if key in items and items[key].get("first_seen"):
            record["first_seen"] = items[key]["first_seen"]
            break
    for key in job_keys(job):
        items[key] = record


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
