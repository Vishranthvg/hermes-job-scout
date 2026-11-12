"""Shared data types for job-scout."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from _text import strip_html


@dataclass
class Job:
    source: str
    source_id: str
    title: str
    company: str
    url: str
    location: str = ""
    remote: Optional[bool] = None
    salary_text: str = ""
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: str = ""
    description: str = ""
    published_at: str = ""
    tags: list[str] = field(default_factory=list)

    def truncated_description(self, limit: int = 2000) -> str:
        text = strip_html(self.description)
        if len(text) > limit:
            return text[:limit].rsplit(" ", 1)[0] + "..."
        return text


@dataclass
class SourceReport:
    name: str
    fetched: int = 0
    kept: int = 0
    error: Optional[str] = None
    skipped: Optional[str] = None


@dataclass
class ScoreBreakdown:
    total: int
    title: int = 0
    title_hit: str = ""
    location: int = 0
    location_note: str = ""
    keywords: int = 0
    keyword_hits: list[str] = field(default_factory=list)
    resume: int = 0
    resume_hits: list[str] = field(default_factory=list)
    must_haves: int = 0
    must_have_hits: list[str] = field(default_factory=list)
    salary: int = 0
    reason: str = ""
    excluded: Optional[str] = None


@dataclass
class Profile:
    target_titles: list[str]
    locations: list[str]
    remote_ok: bool
    salary_floor: Optional[int]
    salary_currency: str
    must_haves: list[str]
    deal_breakers: list[str]
    keywords: list[str]
    resume_path: Optional[Path]
    resume_text: str
    max_results: int
    min_score: int
    schedule_time: str
    timezone: str
    sources: dict[str, bool]
    ats_boards: dict[str, list[str]]
    himalayas_pages: int
    himalayas_page_size: int
    arbeitnow_pages: int
    update_seen_on_scan: bool
    origin_dir: Path
