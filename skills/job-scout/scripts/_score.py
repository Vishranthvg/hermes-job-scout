"""Title, location, salary, and keyword scoring."""
from __future__ import annotations

import re
from typing import Optional

from _models import Job, Profile, ScoreBreakdown
from _text import normalize_space, phrase_in, strip_html, tokenize, word_set

# City / region -> country. Used so "Remote, Canada" matches a user in Toronto.
_PLACE_COUNTRY = {
    "toronto": "canada",
    "ontario": "canada",
    "vancouver": "canada",
    "montreal": "canada",
    "calgary": "canada",
    "ottawa": "canada",
    "mississauga": "canada",
    "edmonton": "canada",
    "winnipeg": "canada",
    "quebec": "canada",
    "british columbia": "canada",
    "alberta": "canada",
    "manitoba": "canada",
    "saskatchewan": "canada",
    "nova scotia": "canada",
    "new brunswick": "canada",
    "gta": "canada",
    "canada": "canada",
    "canadian": "canada",
    "united states": "united states",
    "usa": "united states",
    "america": "united states",
    "american": "united states",
    "new york": "united states",
    "nyc": "united states",
    "san francisco": "united states",
    "seattle": "united states",
    "chicago": "united states",
    "austin": "united states",
    "boston": "united states",
    "denver": "united states",
    "los angeles": "united states",
    "california": "united states",
    "washington": "united states",
    "london": "united kingdom",
    "united kingdom": "united kingdom",
    "england": "united kingdom",
    "uk": "united kingdom",
    "ireland": "ireland",
    "dublin": "ireland",
    "germany": "germany",
    "berlin": "germany",
    "france": "france",
    "paris": "france",
    "netherlands": "netherlands",
    "amsterdam": "netherlands",
    "spain": "spain",
    "mexico": "mexico",
    "brazil": "brazil",
    "australia": "australia",
    "singapore": "singapore",
    "india": "india",
    "emea": "emea",
    "europe": "europe",
    "worldwide": "worldwide",
    "anywhere": "worldwide",
    "global": "worldwide",
}


# Additional country names, mapped to themselves, so a remote role that is
# clearly limited to another country is not treated as unrestricted.
for _country in (
    "philippines", "japan", "south korea", "korea", "china", "taiwan",
    "vietnam", "thailand", "indonesia", "malaysia", "pakistan", "bangladesh",
    "nepal", "sri lanka", "new zealand", "argentina", "chile", "colombia",
    "peru", "italy", "belgium", "switzerland", "austria", "portugal",
    "sweden", "norway", "denmark", "finland", "poland", "romania",
    "czech republic", "scotland", "wales", "south africa", "nigeria",
    "kenya", "egypt", "israel", "united arab emirates", "uae", "dubai",
    "saudi arabia", "russia", "ukraine", "turkey", "greece", "hungary",
    "brazil", "mexico", "germany", "france", "spain", "netherlands",
    "ireland", "australia", "india", "singapore", "united kingdom",
    "united states", "canada",
):
    _PLACE_COUNTRY.setdefault(_country, _country)

_COUNTRY_ALIASES = {
    "u.s.": "united states",
    "u.s.a.": "united states",
    "u.s.a": "united states",
    "us": "united states",
    "usa": "united states",
    "uk": "united kingdom",
    "u.k.": "united kingdom",
    "can": "canada",
}

_REMOTE_RE = re.compile(
    r"\b(remote|work from home|wfh|distributed|anywhere|worldwide|work-from-home)\b",
    re.I,
)
_WORLD_RE = re.compile(r"\b(worldwide|anywhere|global|unrestricted|any location)\b", re.I)

_SALARY_RE = re.compile(
    r"(?P<cur>[$£€]|usd|cad|gbp|eur|aud)?\s*"
    r"(?P<num>\d{2,3}(?:[, ]\d{3})+|\d+(?:\.\d+)?)\s*"
    r"(?P<suf>k|m)?",
    re.I,
)


def expand_user_places(locations: list[str]) -> tuple[set[str], set[str]]:
    places: set[str] = set()
    countries: set[str] = set()
    for loc in locations:
        phrase = normalize_space(loc).lower()
        if not phrase:
            continue
        places.add(phrase)
        country = _PLACE_COUNTRY.get(phrase) or _COUNTRY_ALIASES.get(phrase)
        if country:
            countries.add(country)
            places.add(country)
    return places, countries


def extract_job_places(location: str) -> tuple[set[str], set[str], bool, bool]:
    text = normalize_space(location or "")
    lower = text.lower()
    is_remote = bool(_REMOTE_RE.search(lower))
    is_worldwide = bool(_WORLD_RE.search(lower))

    # "CA, US" / "Remote, CA, US" is California, not Canada.
    us_present = bool(re.search(r"\b(united states|usa|u\.s\.a?\.?|us-remote|remote[- ]us)\b", lower))
    us_present = us_present or bool(re.search(r",?\s*us\b", lower)) or lower.endswith(" us")
    if us_present:
        lower_for_places = re.sub(r"\bca\b", "california", lower)
    else:
        # Do not treat bare "CA" as Canada; it is too ambiguous.
        lower_for_places = re.sub(r"\bca\b", " ", lower)

    lower_for_places = re.sub(r"\bu\.s\.a\.?\b", "united states", lower_for_places)
    lower_for_places = re.sub(r"\bu\.s\.?\b", "united states", lower_for_places)
    lower_for_places = re.sub(r"\busa\b", "united states", lower_for_places)
    lower_for_places = re.sub(r"\bus-remote\b", "united states remote", lower_for_places)
    lower_for_places = re.sub(r"\bremote[- ]us\b", "remote united states", lower_for_places)
    lower_for_places = re.sub(r"\bu\.k\.?\b", "united kingdom", lower_for_places)

    places: set[str] = set()
    countries: set[str] = set()
    phrases = sorted(_PLACE_COUNTRY.keys(), key=len, reverse=True)
    consumed = " " + lower_for_places + " "
    for phrase in phrases:
        pat = r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])"
        if re.search(pat, consumed):
            places.add(phrase)
            countries.add(_PLACE_COUNTRY[phrase])
            consumed = re.sub(pat, " ", consumed)

    if re.search(r"\b(on|ab|bc|ns|mb|sk|nb|nl|pe|yt|nt|nu)\b", lower) and (
        "canada" in lower or re.search(r"\b(on,?\s*ab|ab,?\s*bc)\b", lower)
    ):
        countries.add("canada")
        places.add("canada")

    if is_worldwide:
        countries.add("worldwide")
    return places, countries, is_remote, is_worldwide


def location_decision(job: Job, profile: Profile) -> tuple[Optional[str], int, str]:
    places, countries, loc_remote, is_worldwide = extract_job_places(job.location)
    is_remote = job.remote if job.remote is not None else loc_remote
    user_places, user_countries = expand_user_places(profile.locations)

    if user_places and (places & user_places):
        hit = sorted(places & user_places, key=len, reverse=True)[0]
        return None, 20, f"matches {hit}"

    if user_countries and (countries & user_countries):
        hit = sorted(countries & user_countries)[0]
        return None, 18, f"in {hit}"

    if is_worldwide:
        if profile.remote_ok:
            return None, 14, "worldwide / anywhere"
        return "worldwide role but remote_ok is false", 0, ""

    if is_remote and profile.remote_ok:
        restricted = countries - {"worldwide", "emea", "europe"}
        if restricted and user_countries and not (restricted & user_countries):
            return (
                f"remote but restricted to {', '.join(sorted(restricted))}",
                0,
                "",
            )
        return None, 16, "remote-friendly"

    if not job.location.strip() or job.location.strip().lower() in {"n/a", "unspecified", "unknown"}:
        if profile.remote_ok:
            return None, 8, "location not listed"
        return "no location listed and remote_ok is false", 0, ""

    return f"location {job.location!r} is outside your target area", 0, ""


def parse_salary_values(text: str) -> tuple[Optional[int], Optional[int], str]:
    if not text:
        return None, None, ""
    raw = strip_html(text)
    currency = ""
    cl = raw.lower()
    if "cad" in cl or "c$" in cl or "canadian" in cl:
        currency = "CAD"
    elif "usd" in cl or "u.s." in cl or "us$" in cl:
        currency = "USD"
    elif "gbp" in cl or "£" in cl:
        currency = "GBP"
    elif "eur" in cl or "€" in cl:
        currency = "EUR"
    nums: list[int] = []
    for m in _SALARY_RE.finditer(raw):
        token = m.group("num").replace(",", "").replace(" ", "")
        try:
            value = float(token)
        except ValueError:
            continue
        suf = (m.group("suf") or "").lower()
        if suf == "k":
            value *= 1000
        elif suf == "m":
            value *= 1_000_000
        if value < 1000:
            continue
        nums.append(int(value))
        if not currency and m.group("cur"):
            cur = m.group("cur").upper()
            currency = {"$": "", "£": "GBP", "€": "EUR"}.get(cur, cur)
    if not nums:
        return None, None, currency
    return min(nums), max(nums), currency


def salary_decision(job: Job, profile: Profile) -> tuple[Optional[str], int, str]:
    floor = profile.salary_floor
    if not floor:
        return None, 0, ""
    low, high, currency = job.salary_min, job.salary_max, job.salary_currency
    if low is None and high is None and job.salary_text:
        low, high, currency = parse_salary_values(job.salary_text)
    if low is None and high is None:
        return None, 0, "salary not listed"
    pc = (profile.salary_currency or "").upper()
    jc = (currency or "").upper()
    if pc and jc and pc != jc:
        shown = job.salary_text or high
        return None, 0, f"salary {shown} {jc} (not compared to {pc} floor)"
    top = high if high is not None else low
    if top is not None and top < floor:
        return f"salary max {top} is below the floor {floor}", 0, ""
    bottom = low if low is not None else high
    if bottom is not None and bottom >= floor:
        return None, 5, f"salary at or above {floor}"
    return None, 2, "salary range crosses the floor"


def title_score(title: str, targets: list[str]) -> tuple[int, str]:
    t = (title or "").lower()
    best = 0
    hit = ""
    for target in targets:
        tgt = target.strip().lower()
        if not tgt:
            continue
        if t == tgt:
            sc = 40
        elif re.search(r"\b" + re.escape(tgt) + r"\b", t):
            sc = 36
        elif tgt in t:
            sc = 28
        else:
            tgt_tokens = [w for w in tokenize(tgt) if w not in {"and", "the", "of"}]
            title_tokens = set(tokenize(t))
            if tgt_tokens and all(w in title_tokens for w in tgt_tokens):
                sc = 32
            elif tgt_tokens and (sum(w in title_tokens for w in tgt_tokens) / len(tgt_tokens)) >= 0.7:
                sc = 18
            else:
                sc = 0
        # Prefer the longer, more specific target when scores tie
        # ("Technical Program Manager" over "Program Manager").
        if sc > best or (sc == best and sc > 0 and len(target) > len(hit)):
            best, hit = sc, target
    return best, hit


_RESUME_STOP = {
    "summary", "experience", "education", "skills", "present", "years",
    "leading", "comfortable", "certified", "based", "open", "hybrid",
    "roles", "teams", "size", "with", "from", "that", "this", "have",
    "been", "were", "including", "across", "through", "three", "four",
    "five", "eight", "twelve", "plus", "used", "using", "also", "such",
    "other", "their", "your", "ours", "manager", "project", "senior",
    "canada", "canadian", "toronto", "ontario", "united", "states",
    "remote", "hybrid", "office", "commerce", "university", "professional",
}

def resume_terms(text: str) -> list[str]:
    phrases = re.findall(r"\b[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){1,3}\b", text)
    lowered: list[str] = []
    for p in phrases:
        lp = p.strip().lower()
        if lp in _RESUME_STOP or any(w in _RESUME_STOP for w in lp.split()):
            # Keep meaningful multi-word skill phrases such as "Project Management".
            if " " not in lp:
                continue
        if lp not in lowered and len(lp) > 4:
            lowered.append(lp)
    counts: dict[str, int] = {}
    for tok in word_set(text):
        if len(tok) >= 5 and tok not in _RESUME_STOP:
            counts[tok] = counts.get(tok, 0) + 1
    for tok, _n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:15]:
        if tok not in lowered:
            lowered.append(tok)
    return lowered[:20]


def reason_line(job: Job, bd: ScoreBreakdown, sal_note: str) -> str:
    bits: list[str] = []
    if bd.title_hit:
        bits.append(f"title matches {bd.title_hit}")
    if bd.location_note:
        bits.append(bd.location_note)
    if bd.must_have_hits:
        bits.append("must-haves: " + ", ".join(bd.must_have_hits[:3]))
    if bd.keyword_hits:
        bits.append("keywords: " + ", ".join(bd.keyword_hits[:3]))
    elif bd.resume_hits:
        bits.append("resume overlap: " + ", ".join(bd.resume_hits[:3]))
    if sal_note and "not listed" not in sal_note:
        bits.append(sal_note)
    if not bits:
        bits.append("fits the target title")
    line = "; ".join(bits)
    if not line.endswith("."):
        line += "."
    return line[0].upper() + line[1:]


def score_job(job: Job, profile: Profile) -> ScoreBreakdown:
    haystack = " ".join(
        [
            job.title,
            job.company,
            job.location,
            " ".join(job.tags),
            job.truncated_description(2500),
        ]
    )

    for phrase in profile.deal_breakers:
        if phrase and phrase_in(phrase, haystack):
            return ScoreBreakdown(total=0, excluded=f"deal-breaker: {phrase}")

    t_score, t_hit = title_score(job.title, profile.target_titles)
    if t_score < 18:
        return ScoreBreakdown(total=0, excluded="title does not match a target title")

    loc_excl, loc_score, loc_note = location_decision(job, profile)
    if loc_excl:
        return ScoreBreakdown(total=0, title=t_score, title_hit=t_hit, excluded=loc_excl)

    sal_excl, sal_score, sal_note = salary_decision(job, profile)
    if sal_excl:
        return ScoreBreakdown(
            total=0, title=t_score, title_hit=t_hit,
            location=loc_score, location_note=loc_note, excluded=sal_excl,
        )

    kw_hits = [k for k in profile.keywords if k and phrase_in(k, haystack)]
    kw_score = round(15 * len(kw_hits) / max(len(profile.keywords), 1)) if profile.keywords else 0

    mh_hits = [m for m in profile.must_haves if m and phrase_in(m, haystack)]
    mh_score = round(10 * len(mh_hits) / max(len(profile.must_haves), 1)) if profile.must_haves else 0

    resume_hits: list[str] = []
    resume_score = 0
    if profile.resume_text:
        terms = resume_terms(profile.resume_text)
        present = [term for term in terms if phrase_in(term, haystack)]
        resume_hits = present[:6]
        if terms:
            resume_score = min(15, round(15 * len(present) / max(min(len(terms), 12), 1)))

    total = max(0, min(100, t_score + loc_score + kw_score + mh_score + resume_score + sal_score))
    bd = ScoreBreakdown(
        total=total,
        title=t_score,
        title_hit=t_hit,
        location=loc_score,
        location_note=loc_note,
        keywords=kw_score,
        keyword_hits=kw_hits,
        resume=resume_score,
        resume_hits=resume_hits,
        must_haves=mh_score,
        must_have_hits=mh_hits,
        salary=sal_score,
    )
    bd.reason = reason_line(job, bd, sal_note)
    return bd


def remote_from_text(location: str) -> Optional[bool]:
    if not location:
        return None
    if _REMOTE_RE.search(location):
        return True
    if re.search(r"\b(on-?site|in-office|office)\b", location, re.I):
        return False
    return None
