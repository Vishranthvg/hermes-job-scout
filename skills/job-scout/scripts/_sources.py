"""Public job-source adapters. Each fetcher returns a list of Job objects."""
from __future__ import annotations

import os
import time
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Callable, Optional

from _http import DEFAULT_TIMEOUT, FetchError, http_get, http_get_json
from _models import Job, Profile
from _score import expand_user_places, remote_from_text
from _text import normalize_space

ATS_DELAY_SEC = 0.25


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(_as_str(v) for v in value if v)
    if isinstance(value, dict):
        for key in ("name", "label", "city", "location"):
            if value.get(key):
                return _as_str(value[key])
        return ""
    return normalize_space(str(value))


def _boolish(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in {"true", "1", "yes", "remote"}:
        return True
    if s in {"false", "0", "no", "onsite", "on-site"}:
        return False
    return None


def fetch_remotive(_profile: Profile, timeout: int) -> list[Job]:
    data = http_get_json("https://remotive.com/api/remote-jobs", timeout=timeout)
    jobs = []
    for item in data.get("jobs") or []:
        jobs.append(
            Job(
                source="remotive",
                source_id=str(item.get("id") or item.get("url") or ""),
                title=_as_str(item.get("title")),
                company=_as_str(item.get("company_name")),
                url=_as_str(item.get("url")),
                location=_as_str(item.get("candidate_required_location")),
                remote=True,
                salary_text=_as_str(item.get("salary")),
                description=_as_str(item.get("description")),
                published_at=_as_str(item.get("publication_date")),
                tags=list(item.get("tags") or []) + ([item["category"]] if item.get("category") else []),
            )
        )
    return jobs


def fetch_arbeitnow(profile: Profile, timeout: int) -> list[Job]:
    jobs: list[Job] = []
    url: Optional[str] = "https://www.arbeitnow.com/api/job-board-api"
    pages = max(1, profile.arbeitnow_pages)
    for _ in range(pages):
        if not url:
            break
        data = http_get_json(url, timeout=timeout)
        for item in data.get("data") or []:
            jobs.append(
                Job(
                    source="arbeitnow",
                    source_id=_as_str(item.get("slug") or item.get("url")),
                    title=_as_str(item.get("title")),
                    company=_as_str(item.get("company_name")),
                    url=_as_str(item.get("url")),
                    location=_as_str(item.get("location")),
                    remote=_boolish(item.get("remote")),
                    description=_as_str(item.get("description")),
                    published_at=_as_str(item.get("created_at")),
                    tags=list(item.get("tags") or []) + list(item.get("job_types") or []),
                )
            )
        url = (data.get("links") or {}).get("next")
        if url:
            time.sleep(ATS_DELAY_SEC)
    return jobs


def fetch_jobicy(_profile: Profile, timeout: int) -> list[Job]:
    # The tag filter often returns an empty page. Fetch a general recent
    # page and filter locally.
    data = http_get_json("https://jobicy.com/api/v2/remote-jobs?count=50", timeout=timeout)
    jobs = []
    for item in data.get("jobs") or []:
        jobs.append(
            Job(
                source="jobicy",
                source_id=str(item.get("id") or item.get("jobSlug") or ""),
                title=_as_str(item.get("jobTitle")),
                company=_as_str(item.get("companyName")),
                url=_as_str(item.get("url")),
                location=_as_str(item.get("jobGeo")),
                remote=True,
                description=_as_str(item.get("jobDescription") or item.get("jobExcerpt")),
                published_at=_as_str(item.get("pubDate")),
                tags=[_as_str(item.get("jobIndustry")), _as_str(item.get("jobType")), _as_str(item.get("jobLevel"))],
            )
        )
    return jobs


def fetch_remoteok(_profile: Profile, timeout: int) -> list[Job]:
    data = http_get_json("https://remoteok.com/api", timeout=timeout)
    if not isinstance(data, list):
        raise FetchError("unexpected RemoteOK payload")
    jobs = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if item.get("legal") and not item.get("position"):
            continue
        title = _as_str(item.get("position") or item.get("title"))
        if not title:
            continue
        low, high = item.get("salary_min"), item.get("salary_max")
        try:
            low_i = int(low) if low else None
            high_i = int(high) if high else None
        except (TypeError, ValueError):
            low_i = high_i = None
        if low_i == 0:
            low_i = None
        if high_i == 0:
            high_i = None
        salary_text = ""
        if low_i or high_i:
            salary_text = f"{low_i or '?'} - {high_i or '?'} USD"
        jobs.append(
            Job(
                source="remoteok",
                source_id=str(item.get("id") or item.get("slug") or ""),
                title=title,
                company=_as_str(item.get("company")),
                url=_as_str(item.get("url") or item.get("apply_url")),
                location=_as_str(item.get("location")),
                remote=True,
                salary_text=salary_text,
                salary_min=low_i,
                salary_max=high_i,
                salary_currency="USD" if (low_i or high_i) else "",
                description=_as_str(item.get("description")),
                published_at=_as_str(item.get("date")),
                tags=list(item.get("tags") or []),
            )
        )
    return jobs


def fetch_himalayas(profile: Profile, timeout: int) -> list[Job]:
    # The public API does not reliably filter by keyword. Paginate a few
    # recent pages and filter locally.
    jobs: list[Job] = []
    cursor = None
    pages = max(1, profile.himalayas_pages)
    size = max(1, min(50, profile.himalayas_page_size))
    for _ in range(pages):
        params = {"limit": str(size)}
        if cursor:
            params["cursor"] = cursor
        url = "https://himalayas.app/jobs/api?" + urllib.parse.urlencode(params)
        data = http_get_json(url, timeout=timeout)
        for item in data.get("jobs") or []:
            restrictions = item.get("locationRestrictions") or []
            location = ", ".join(_as_str(r) for r in restrictions) if restrictions else ""
            if item.get("timezoneRestrictions") and not location:
                location = "remote (timezone-restricted)"
            low, high = item.get("minSalary"), item.get("maxSalary")
            try:
                low_i = int(low) if low else None
                high_i = int(high) if high else None
            except (TypeError, ValueError):
                low_i = high_i = None
            currency = _as_str(item.get("currency"))
            salary_text = ""
            if low_i or high_i:
                period = _as_str(item.get("salaryPeriod") or "annual")
                salary_text = f"{low_i or '?'} - {high_i or '?'} {currency} {period}".strip()
            jobs.append(
                Job(
                    source="himalayas",
                    source_id=_as_str(item.get("guid") or item.get("applicationLink")),
                    title=_as_str(item.get("title")),
                    company=_as_str(item.get("companyName")),
                    url=_as_str(item.get("applicationLink") or item.get("guid")),
                    location=location or "remote",
                    remote=True,
                    salary_text=salary_text,
                    salary_min=low_i,
                    salary_max=high_i,
                    salary_currency=currency,
                    description=_as_str(item.get("description") or item.get("excerpt")),
                    published_at=_as_str(item.get("pubDate")),
                    tags=list(item.get("categories") or []) + list(item.get("parentCategories") or []),
                )
            )
        cursor = data.get("nextCursor")
        if not cursor:
            break
        time.sleep(ATS_DELAY_SEC)
    return jobs


def _local_tag(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def fetch_weworkremotely(_profile: Profile, timeout: int) -> list[Job]:
    feeds = [
        "https://weworkremotely.com/categories/remote-product-jobs.rss",
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-customer-success-jobs.rss",
        "https://weworkremotely.com/categories/remote-sales-and-marketing-jobs.rss",
        "https://weworkremotely.com/categories/remote-management-jobs.rss",
    ]
    jobs: list[Job] = []
    seen_urls: set[str] = set()
    last_error: Optional[Exception] = None
    fetched_any = False
    for feed in feeds:
        try:
            _status, _ctype, body = http_get(feed, timeout=timeout)
            fetched_any = True
        except FetchError as exc:
            last_error = exc
            continue
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            last_error = FetchError(f"invalid RSS from {feed}: {exc}")
            continue
        for item in root.iter():
            if _local_tag(item.tag).lower() != "item":
                continue
            fields = {_local_tag(c.tag).lower(): (c.text or "") for c in list(item)}
            url = (fields.get("link") or fields.get("guid") or "").strip()
            title_raw = (fields.get("title") or "").strip()
            company = ""
            title = title_raw
            if ":" in title_raw:
                company, _, title = title_raw.partition(":")
                company, title = company.strip(), title.strip()
            location_bits = [
                fields.get("region", "").strip(),
                fields.get("country", "").strip(),
                fields.get("state", "").strip(),
            ]
            location = ", ".join(b for b in location_bits if b)
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            jobs.append(
                Job(
                    source="weworkremotely",
                    source_id=url,
                    title=title or title_raw,
                    company=company,
                    url=url,
                    location=location,
                    remote=True,
                    description=fields.get("description") or "",
                    published_at=fields.get("pubdate") or "",
                    tags=[fields.get("category", ""), fields.get("type", ""), fields.get("skills", "")],
                )
            )
        time.sleep(ATS_DELAY_SEC)
    if not fetched_any and last_error:
        raise last_error
    return jobs


def fetch_greenhouse(profile: Profile, timeout: int) -> list[Job]:
    boards = (profile.ats_boards or {}).get("greenhouse") or []
    jobs: list[Job] = []
    errors: list[str] = []
    for token in boards:
        token = str(token).strip()
        if not token:
            continue
        url = f"https://boards-api.greenhouse.io/v1/boards/{urllib.parse.quote(token)}/jobs"
        try:
            data = http_get_json(url, timeout=timeout)
        except FetchError as exc:
            errors.append(f"{token}: {exc}")
            time.sleep(ATS_DELAY_SEC)
            continue
        for item in data.get("jobs") or []:
            loc = item.get("location")
            jobs.append(
                Job(
                    source="greenhouse",
                    source_id=str(item.get("id") or item.get("internal_job_id") or ""),
                    title=_as_str(item.get("title")),
                    company=_as_str(item.get("company_name") or token),
                    url=_as_str(item.get("absolute_url")),
                    location=_as_str(loc),
                    remote=remote_from_text(_as_str(loc)),
                    description=_as_str(item.get("content")),
                    published_at=_as_str(item.get("updated_at") or item.get("first_published")),
                    tags=[_as_str(d.get("name")) for d in (item.get("departments") or []) if isinstance(d, dict)],
                )
            )
        time.sleep(ATS_DELAY_SEC)
    if errors and not jobs:
        raise FetchError("greenhouse boards failed: " + "; ".join(errors))
    fetch_greenhouse.last_warnings = errors  # type: ignore[attr-defined]
    return jobs


def fetch_lever(profile: Profile, timeout: int) -> list[Job]:
    boards = (profile.ats_boards or {}).get("lever") or []
    jobs: list[Job] = []
    errors: list[str] = []
    for token in boards:
        token = str(token).strip()
        if not token:
            continue
        url = f"https://api.lever.co/v0/postings/{urllib.parse.quote(token)}?mode=json"
        try:
            data = http_get_json(url, timeout=timeout)
        except FetchError as exc:
            errors.append(f"{token}: {exc}")
            time.sleep(ATS_DELAY_SEC)
            continue
        if not isinstance(data, list):
            errors.append(f"{token}: unexpected payload")
            continue
        for item in data:
            cats = item.get("categories") or {}
            location = _as_str(cats.get("location") or item.get("country"))
            all_locs = cats.get("allLocations") or []
            if all_locs:
                location = ", ".join(_as_str(x) for x in all_locs)
            workplace = _as_str(item.get("workplaceType")).lower()
            if workplace == "remote":
                remote = True
            elif workplace in {"onsite", "on-site"}:
                remote = False
            else:
                remote = remote_from_text(location)
            jobs.append(
                Job(
                    source="lever",
                    source_id=str(item.get("id") or ""),
                    title=_as_str(item.get("text") or item.get("title")),
                    company=_as_str(item.get("company") or token),
                    url=_as_str(item.get("hostedUrl") or item.get("applyUrl")),
                    location=location,
                    remote=remote,
                    description=_as_str(item.get("descriptionPlain") or item.get("description")),
                    published_at=_as_str(item.get("createdAt")),
                    tags=[_as_str(cats.get("team")), _as_str(cats.get("commitment"))],
                )
            )
        time.sleep(ATS_DELAY_SEC)
    if errors and not jobs:
        raise FetchError("lever boards failed: " + "; ".join(errors))
    fetch_lever.last_warnings = errors  # type: ignore[attr-defined]
    return jobs


def fetch_ashby(profile: Profile, timeout: int) -> list[Job]:
    boards = (profile.ats_boards or {}).get("ashby") or []
    jobs: list[Job] = []
    errors: list[str] = []
    for token in boards:
        token = str(token).strip()
        if not token:
            continue
        url = f"https://api.ashbyhq.com/posting-api/job-board/{urllib.parse.quote(token)}"
        try:
            data = http_get_json(url, timeout=timeout)
        except FetchError as exc:
            errors.append(f"{token}: {exc}")
            time.sleep(ATS_DELAY_SEC)
            continue
        for item in data.get("jobs") or []:
            if item.get("isListed") is False:
                continue
            secondary = item.get("secondaryLocations") or []
            loc_bits = [_as_str(item.get("location"))]
            for sec in secondary:
                loc_bits.append(_as_str(sec))
            location = ", ".join(b for b in loc_bits if b)
            workplace = _as_str(item.get("workplaceType")).lower()
            remote = _boolish(item.get("isRemote"))
            if remote is None:
                remote = True if workplace == "remote" else remote_from_text(location)
            company = _as_str(item.get("companyName") or item.get("company"))
            if not company:
                company = token.replace("-", " ").title()
            jobs.append(
                Job(
                    source="ashby",
                    source_id=str(item.get("id") or ""),
                    title=_as_str(item.get("title")),
                    company=company,
                    url=_as_str(item.get("jobUrl") or item.get("applyUrl")),
                    location=location,
                    remote=remote,
                    description=_as_str(item.get("descriptionPlain") or item.get("descriptionHtml")),
                    published_at=_as_str(item.get("publishedAt")),
                    tags=[
                        _as_str(item.get("department")),
                        _as_str(item.get("team")),
                        _as_str(item.get("employmentType")),
                    ],
                )
            )
        time.sleep(ATS_DELAY_SEC)
    if errors and not jobs:
        raise FetchError("ashby boards failed: " + "; ".join(errors))
    fetch_ashby.last_warnings = errors  # type: ignore[attr-defined]
    return jobs


def _country_code_for_adzuna(profile: Profile) -> str:
    _places, countries = expand_user_places(profile.locations)
    mapping = {
        "canada": "ca",
        "united states": "us",
        "united kingdom": "gb",
        "germany": "de",
        "france": "fr",
        "netherlands": "nl",
        "australia": "au",
        "india": "in",
        "singapore": "sg",
        "ireland": "ie",
        "spain": "es",
        "mexico": "mx",
        "brazil": "br",
    }
    for c in countries:
        if c in mapping:
            return mapping[c]
    return os.environ.get("ADZUNA_COUNTRY", "ca")


def fetch_adzuna(profile: Profile, timeout: int) -> list[Job]:
    app_id = os.environ.get("ADZUNA_APP_ID", "").strip()
    app_key = os.environ.get("ADZUNA_APP_KEY", "").strip()
    if not app_id or not app_key:
        raise FetchError("skipped (set ADZUNA_APP_ID and ADZUNA_APP_KEY)", status=0)
    country = _country_code_for_adzuna(profile)
    what = " ".join(profile.target_titles[:2]) or "project manager"
    where = profile.locations[0] if profile.locations else ""
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "what": what,
        "results_per_page": "50",
        "content-type": "application/json",
    }
    if where:
        params["where"] = where
    url = (
        f"https://api.adzuna.com/v1/api/jobs/{urllib.parse.quote(country)}/search/1?"
        + urllib.parse.urlencode(params)
    )
    data = http_get_json(url, timeout=timeout)
    jobs = []
    for item in data.get("results") or []:
        loc = item.get("location") or {}
        area = loc.get("display_name") or ", ".join(loc.get("area") or [])
        low, high = item.get("salary_min"), item.get("salary_max")
        try:
            low_i = int(low) if low else None
            high_i = int(high) if high else None
        except (TypeError, ValueError):
            low_i = high_i = None
        salary_text = f"{low_i or '?'} - {high_i or '?'}" if (low_i or high_i) else ""
        jobs.append(
            Job(
                source="adzuna",
                source_id=str(item.get("id") or ""),
                title=_as_str(item.get("title")),
                company=_as_str((item.get("company") or {}).get("display_name")),
                url=_as_str(item.get("redirect_url") or item.get("adref")),
                location=_as_str(area),
                remote=remote_from_text(_as_str(area) + " " + _as_str(item.get("description"))),
                salary_min=low_i,
                salary_max=high_i,
                salary_text=salary_text,
                description=_as_str(item.get("description")),
                published_at=_as_str(item.get("created")),
                tags=[_as_str((item.get("category") or {}).get("label"))],
            )
        )
    return jobs


def fetch_serpapi(profile: Profile, timeout: int) -> list[Job]:
    key = os.environ.get("SERPAPI_API_KEY", "").strip()
    if not key:
        raise FetchError("skipped (set SERPAPI_API_KEY)", status=0)
    query = " ".join(filter(None, [
        profile.target_titles[0] if profile.target_titles else "project manager",
        profile.locations[0] if profile.locations else "",
    ]))
    params = {"engine": "google_jobs", "q": query, "api_key": key}
    if profile.locations:
        params["location"] = profile.locations[0]
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(params)
    data = http_get_json(url, timeout=timeout)
    if data.get("error"):
        raise FetchError(str(data["error"]))
    jobs = []
    for item in data.get("jobs_results") or []:
        loc = _as_str(item.get("location"))
        detected = item.get("detected_extensions") or {}
        apply_opts = item.get("apply_options") or [{}]
        apply_link = ""
        if apply_opts and isinstance(apply_opts, list):
            apply_link = _as_str((apply_opts[0] or {}).get("link"))
        jobs.append(
            Job(
                source="serpapi",
                source_id=_as_str(item.get("job_id") or item.get("share_link") or item.get("title")),
                title=_as_str(item.get("title")),
                company=_as_str(item.get("company_name")),
                url=_as_str(item.get("share_link") or item.get("apply_link") or apply_link),
                location=loc,
                remote=_boolish(detected.get("work_from_home")) or remote_from_text(loc),
                salary_text=_as_str(detected.get("salary") or item.get("salary")),
                description=_as_str(item.get("description")),
                published_at=_as_str(detected.get("posted_at")),
                tags=list(item.get("extensions") or []),
            )
        )
    return jobs


def fetch_usajobs(profile: Profile, timeout: int) -> list[Job]:
    key = os.environ.get("USAJOBS_API_KEY", "").strip()
    email = os.environ.get("USAJOBS_USER_AGENT", "").strip()
    if not key or not email:
        raise FetchError("skipped (set USAJOBS_API_KEY and USAJOBS_USER_AGENT)", status=0)
    what = profile.target_titles[0] if profile.target_titles else "project manager"
    params = {"Keyword": what, "ResultsPerPage": "25"}
    if profile.locations:
        params["LocationName"] = profile.locations[0]
    url = "https://data.usajobs.gov/api/Search?" + urllib.parse.urlencode(params)
    headers = {
        "Host": "data.usajobs.gov",
        "User-Agent": email,
        "Authorization-Key": key,
    }
    data = http_get_json(url, headers=headers, timeout=timeout)
    items = (data.get("SearchResult") or {}).get("SearchResultItems") or []
    jobs = []
    for wrapper in items:
        item = wrapper.get("MatchedObjectDescriptor") or wrapper
        locs = item.get("PositionLocation") or []
        location = ", ".join(
            filter(
                None,
                (
                    (_as_str(loc.get("LocationName") or loc.get("CityName")) + " " + _as_str(loc.get("CountryCode"))).strip()
                    for loc in locs
                ),
            )
        )
        remun = item.get("PositionRemuneration") or []
        salary_text = ""
        low_i = high_i = None
        if remun:
            salary_text = (
                f"{remun[0].get('MinimumRange', '')} - {remun[0].get('MaximumRange', '')} "
                f"{remun[0].get('CurrencyCode', '')}"
            ).strip()
            try:
                low_i = int(float(remun[0].get("MinimumRange")))
                high_i = int(float(remun[0].get("MaximumRange")))
            except (TypeError, ValueError):
                pass
        apply = item.get("ApplyURI")
        apply_url = apply[0] if isinstance(apply, list) and apply else apply
        user_area = item.get("UserArea")
        summary = ""
        if isinstance(user_area, dict):
            summary = _as_str((user_area.get("Details") or {}).get("JobSummary"))
        if not summary:
            summary = _as_str(item.get("QualificationSummary"))
        offering = item.get("PositionOfferingType")
        offering_text = ""
        if isinstance(offering, list) and offering:
            offering_text = _as_str(offering[0])
        jobs.append(
            Job(
                source="usajobs",
                source_id=_as_str(item.get("PositionID") or item.get("PositionURI")),
                title=_as_str(item.get("PositionTitle")),
                company=_as_str(item.get("OrganizationName") or item.get("DepartmentName")),
                url=_as_str(item.get("PositionURI") or apply_url),
                location=location,
                remote=remote_from_text(location + " " + offering_text),
                salary_text=salary_text,
                salary_min=low_i,
                salary_max=high_i,
                description=summary,
                published_at=_as_str(item.get("PublicationStartDate")),
            )
        )
    return jobs


SOURCE_FETCHERS: dict[str, Callable[[Profile, int], list[Job]]] = {
    "remotive": fetch_remotive,
    "arbeitnow": fetch_arbeitnow,
    "jobicy": fetch_jobicy,
    "remoteok": fetch_remoteok,
    "himalayas": fetch_himalayas,
    "weworkremotely": fetch_weworkremotely,
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "adzuna": fetch_adzuna,
    "serpapi": fetch_serpapi,
    "usajobs": fetch_usajobs,
}

OPTIONAL_KEY_SOURCES = {"adzuna", "serpapi", "usajobs"}
