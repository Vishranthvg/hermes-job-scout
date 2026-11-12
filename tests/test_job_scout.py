#!/usr/bin/env python3
"""Offline unit tests for scoring, location, salary, dedupe, and YAML."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "job-scout" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from _http import is_seen, job_keys, load_seen, mark_seen  # noqa: E402
from _models import Job, Profile  # noqa: E402
from _score import (  # noqa: E402
    extract_job_places,
    location_decision,
    parse_salary_values,
    salary_decision,
    score_job,
    title_score,
)
from _text import normalize_url, strip_html  # noqa: E402
from _yaml import parse_yaml_text  # noqa: E402
from job_scout import load_profile  # noqa: E402


def _profile(**kwargs) -> Profile:
    base = dict(
        target_titles=["Project Manager", "Program Manager", "Product Manager"],
        locations=["Toronto", "Ontario", "Canada"],
        remote_ok=True,
        salary_floor=80000,
        salary_currency="CAD",
        must_haves=["stakeholder"],
        deal_breakers=["unpaid", "internship"],
        keywords=["PMP", "Scrum", "Agile"],
        resume_path=None,
        resume_text="PMP certified project manager. Stakeholder management, Agile, Scrum.",
        max_results=10,
        min_score=25,
        schedule_time="08:00",
        timezone="America/Toronto",
        sources={},
        ats_boards={},
        himalayas_pages=3,
        himalayas_page_size=20,
        arbeitnow_pages=1,
        update_seen_on_scan=False,
        origin_dir=ROOT,
    )
    base.update(kwargs)
    return Profile(**base)


def _job(**kwargs) -> Job:
    base = dict(
        source="test",
        source_id="1",
        title="Senior Project Manager",
        company="Acme",
        url="https://example.com/jobs/1",
        location="Toronto, Canada",
        remote=True,
        description="Lead stakeholders through an Agile delivery. PMP preferred. Scrum team.",
    )
    base.update(kwargs)
    return Job(**base)


class YamlTests(unittest.TestCase):
    def test_example_profile_loads(self):
        profile = load_profile(ROOT / "profile.example.yaml")
        self.assertIn("Project Manager", profile.target_titles)
        self.assertEqual(profile.salary_floor, 80000)
        self.assertTrue(profile.remote_ok)
        self.assertFalse(profile.sources["usajobs"])
        self.assertIn("stripe", profile.ats_boards["greenhouse"])
        self.assertIn("wealthsimple", profile.ats_boards["ashby"])
        self.assertTrue(profile.resume_text)
        self.assertIn("Jordan Lee", profile.resume_text)

    def test_subset_parser(self):
        data = parse_yaml_text(
            "a: 1\n"
            "b:\n"
            "  - x\n"
            "  - y\n"
            "c:\n"
            "  d: true\n"
            "  e: \"hello\"\n"
        )
        # Force the stdlib parser even if PyYAML is installed by calling internals
        self.assertEqual(data["a"], 1)
        self.assertEqual(data["b"], ["x", "y"])
        self.assertIs(data["c"]["d"], True)
        self.assertEqual(data["c"]["e"], "hello")


class TitleTests(unittest.TestCase):
    def test_exact_and_seniority(self):
        score, hit = title_score("Senior Project Manager", ["Project Manager"])
        self.assertGreaterEqual(score, 36)
        self.assertEqual(hit, "Project Manager")

    def test_unrelated_title_is_low(self):
        score, _hit = title_score("Staff Software Engineer", ["Project Manager"])
        self.assertLess(score, 18)

    def test_prefers_more_specific_title(self):
        _score, hit = title_score(
            "Principal Technical Program Manager",
            ["Program Manager", "Technical Program Manager"],
        )
        self.assertEqual(hit, "Technical Program Manager")


class LocationTests(unittest.TestCase):
    def test_toronto_matches(self):
        excl, score, note = location_decision(_job(location="Toronto, Ontario"), _profile())
        self.assertIsNone(excl)
        self.assertGreaterEqual(score, 18)
        self.assertTrue("toronto" in note.lower() or "ontario" in note.lower() or "canada" in note.lower(), note)

    def test_remote_canada_matches_toronto_user(self):
        excl, score, note = location_decision(
            _job(location="Remote (Canada)", remote=True), _profile()
        )
        self.assertIsNone(excl)
        self.assertGreaterEqual(score, 18)
        self.assertIn("canada", note.lower())

    def test_us_remote_excluded_for_canada_profile(self):
        excl, score, _note = location_decision(
            _job(location="US-Remote", remote=True), _profile()
        )
        self.assertIsNotNone(excl)
        self.assertEqual(score, 0)
        self.assertIn("united states", excl)

    def test_california_ca_us_is_not_canada(self):
        places, countries, _remote, _world = extract_job_places("San Francisco, CA, US")
        self.assertIn("united states", countries)
        self.assertNotIn("canada", countries)
        excl, _s, _n = location_decision(
            _job(location="Remote, CA, US", remote=True), _profile()
        )
        self.assertIsNotNone(excl)

    def test_worldwide_ok_when_remote_ok(self):
        excl, score, note = location_decision(
            _job(location="Worldwide", remote=True), _profile()
        )
        self.assertIsNone(excl)
        self.assertGreaterEqual(score, 14)
        self.assertIn("worldwide", note.lower())

    def test_philippines_remote_excluded_for_canada_profile(self):
        excl, score, _note = location_decision(
            _job(location="Philippines", remote=True), _profile()
        )
        self.assertIsNotNone(excl)
        self.assertEqual(score, 0)
        self.assertIn("philippines", excl.lower())

    def test_canada_and_us_listing_matches(self):
        excl, score, _note = location_decision(
            _job(location="Remote, Canada; Remote, United States", remote=True),
            _profile(),
        )
        self.assertIsNone(excl)
        self.assertGreaterEqual(score, 18)


class SalaryTests(unittest.TestCase):
    def test_parse_range(self):
        low, high, _cur = parse_salary_values("$90,000 - $120,000 CAD")
        self.assertEqual(low, 90000)
        self.assertEqual(high, 120000)

    def test_parse_k_suffix(self):
        low, high, _cur = parse_salary_values("OTE 80k-110k")
        self.assertEqual(low, 80000)
        self.assertEqual(high, 110000)

    def test_below_floor_excluded(self):
        excl, _s, _n = salary_decision(
            _job(salary_text="$50,000 - $60,000 CAD", salary_currency="CAD"),
            _profile(),
        )
        self.assertIsNotNone(excl)
        self.assertIn("below the floor", excl)

    def test_cross_currency_not_excluded(self):
        excl, _s, note = salary_decision(
            _job(salary_text="$50,000 USD", salary_min=50000, salary_max=50000, salary_currency="USD"),
            _profile(),
        )
        self.assertIsNone(excl)
        self.assertIn("not compared", note)


class ScoreTests(unittest.TestCase):
    def test_good_job_passes(self):
        bd = score_job(_job(), _profile())
        self.assertIsNone(bd.excluded)
        self.assertGreaterEqual(bd.total, 25)
        self.assertIn("Project Manager", bd.reason)
        self.assertTrue(bd.reason[0].isupper())

    def test_deal_breaker(self):
        bd = score_job(_job(title="Project Manager Internship", description="unpaid internship"), _profile())
        self.assertIsNotNone(bd.excluded)
        self.assertIn("deal-breaker", bd.excluded)

    def test_wrong_title_excluded(self):
        bd = score_job(_job(title="Barista"), _profile())
        self.assertEqual(bd.excluded, "title does not match a target title")


class DedupeTests(unittest.TestCase):
    def test_url_tracking_params_collapse(self):
        a = normalize_url("https://Example.com/jobs/1?utm_source=x&gh_src=y")
        b = normalize_url("https://example.com/jobs/1/")
        self.assertEqual(a, b)

    def test_seen_list_roundtrip(self, tmp=None):
        job = _job()
        seen = {"version": 1, "items": {}}
        self.assertFalse(is_seen(job, seen))
        mark_seen(seen, job, shown_at="2026-11-11T12:00:00Z")
        self.assertTrue(is_seen(job, seen))
        # Same company+title, different URL, still seen via fingerprint.
        twin = _job(url="https://example.com/jobs/1?utm_campaign=repeat", source_id="other")
        self.assertTrue(is_seen(twin, seen))
        self.assertTrue(any(k.startswith("fp:") for k in job_keys(job)))


class HtmlTests(unittest.TestCase):
    def test_strip(self):
        self.assertEqual(strip_html("<p>Hello &amp; <b>world</b></p>"), "Hello & world")


if __name__ == "__main__":
    unittest.main()
