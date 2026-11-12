"""Text and URL helpers for job-scout."""
from __future__ import annotations

import html
import re
import urllib.parse
from datetime import datetime, timezone

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "gh_src", "gh_jid", "source", "ref", "referral", "s", "trackingid",
}

_STOP = {
    "a", "an", "the", "and", "or", "for", "to", "of", "in", "on", "at",
    "with", "by", "from", "as", "is", "are", "be", "this", "that", "it",
    "we", "you", "our", "your", "their", "job", "role", "team", "work",
    "will", "plus", "etc", "using", "used", "into", "about", "over",
}


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(str(text))
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def word_set(text: str) -> set[str]:
    return {t for t in tokenize(text) if len(t) > 2 and t not in _STOP}


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def normalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parts = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return url.strip()
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=False)
    filtered = [(k, v) for k, v in query if k.lower() not in _TRACKING_PARAMS]
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/")
    return urllib.parse.urlunsplit(
        (parts.scheme.lower(), netloc, path, urllib.parse.urlencode(filtered), "")
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def phrase_in(phrase: str, text: str) -> bool:
    phrase = phrase.strip().lower()
    if not phrase:
        return False
    if " " in phrase:
        return phrase in text.lower()
    return bool(re.search(r"\b" + re.escape(phrase) + r"\b", text.lower()))
