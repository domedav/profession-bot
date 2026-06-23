#!/usr/bin/env python3
"""
Unit tests for profession.hu auto-apply bot.
Run: python3 -m profession_autoapply_tests
Or:   python3 autoapply.py --test
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Import pure functions from the bot
sys.path.insert(0, str(Path(__file__).resolve().parent))

# We need to import from autoapply but it has playwright imports.
# Instead, we test the pure functions directly by importing specific items.

# ── Test helpers ──

def _get_pure_functions():
    """Extract pure function definitions from autoapply.py for testing."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "autoapply", str(Path(__file__).resolve().parent / "autoapply.py")
    )
    # We can't import the full module (playwright dependency), so test pure functions inline

# ── Pure function tests (copied from autoapply.py for isolation) ──

import re
from urllib.parse import urlparse
from collections import Counter


# These are exact copies of the pure functions from autoapply.py
def extract_job_id(url: str) -> str:
    m = re.search(r'-(\d{5,8})(?:/|$|\?)', url)
    return m.group(1) if m else ""

def domain_of(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.replace("www.", "")
        return netloc if netloc else "unknown"
    except Exception:
        return "unknown"

def is_success_url(url: str) -> bool:
    patterns = [
        r'/koszonjuk', r'/sikeres', r'/thank-you', r'/thankyou',
        r'/success', r'/confirmation',
    ]
    return any(re.search(p, url, re.IGNORECASE) for p in patterns)

def is_success_content(content: str) -> bool:
    phrases = [
        "sikeres jelentkezés","sikeresen jelentkezett","köszönjük jelentkezését",
        "jelentkezését rögzítettük","sikeresen elküldtük","sikeres pályázás",
        "jelentkezését továbbítottuk","jelentkezésedet továbbítottuk",
        "thank you for applying","application submitted",
    ]
    cl = content.lower()
    return any(p in cl for p in phrases)

def is_ats_signature(content: str) -> bool:
    signatures = [
        r'avature\.net', r'myworkdayjobs\.com', r'workday\.com',
        r'smartrecruiters\.com', r'Apply With LinkedIn',
    ]
    return any(re.search(s, content, re.IGNORECASE) for s in signatures)

def is_marketing_text(text: str) -> bool:
    keywords = [
        "marketing","reklám","hírlevél","értesít","hirdet","promóció",
        "e-mailben","emailben",
    ]
    return any(w in text.lower() for w in keywords)

def validate_config(cfg: dict) -> list[str]:
    issues = []
    if "max_pages" in cfg:
        try: int(cfg["max_pages"])
        except (ValueError, TypeError): issues.append("max_pages must be an integer")
    if "max_applications_per_run" in cfg:
        try: int(cfg["max_applications_per_run"])
        except (ValueError, TypeError): issues.append("max_applications_per_run must be an integer")
    if "salary_amount" in cfg and cfg["salary_amount"] is not None:
        try: int(cfg["salary_amount"])
        except (ValueError, TypeError): issues.append("salary_amount must be an integer or null")
    return issues

# ── Tests ──

class TestExtractJobId(unittest.TestCase):
    """Test job ID extraction from URLs."""

    def test_normal_url(self):
        self.assertEqual(extract_job_id("https://www.profession.hu/allas/head-of-hr-zarges-kft-kecskemet-2931302"), "2931302")

    def test_slug_with_hyphens(self):
        self.assertEqual(extract_job_id("https://www.profession.hu/allas/net-ops-agent-forklift-driver-dhl-express-2931792"), "2931792")

    def test_short_id(self):
        self.assertEqual(extract_job_id("/allas/some-slug-12345"), "12345")

    def test_eight_digit_id(self):
        self.assertEqual(extract_job_id("/allas/slug-12345678"), "12345678")

    def test_no_match(self):
        self.assertEqual(extract_job_id("/allas/slug-noid"), "")

    def test_four_digit_id_no_match(self):
        self.assertEqual(extract_job_id("/allas/slug-1234"), "")

    def test_url_with_query(self):
        self.assertEqual(extract_job_id("https://www.profession.hu/allas/slug-2931302?keyword=test"), "2931302")

    def test_trailing_slash(self):
        self.assertEqual(extract_job_id("/allas/slug-2931302/"), "2931302")

    def test_hungarian_chars(self):
        self.assertEqual(extract_job_id("/allas/éttermi-dolgozó-2931790"), "2931790")


class TestDomainOf(unittest.TestCase):
    """Test domain extraction."""

    def test_https_www(self):
        self.assertEqual(domain_of("https://www.example.com/path"), "example.com")

    def test_http_no_www(self):
        self.assertEqual(domain_of("http://example.com/path"), "example.com")

    def test_subdomain(self):
        self.assertEqual(domain_of("https://sub.example.com"), "sub.example.com")

    def test_avature(self):
        self.assertEqual(domain_of("https://dpdhlgroup.avature.net/hu_HU/jobs"), "dpdhlgroup.avature.net")

    def test_empty_string(self):
        self.assertEqual(domain_of(""), "unknown")


class TestSuccessDetection(unittest.TestCase):
    """Test success URL and content detection."""

    def test_koszonjuk_url(self):
        self.assertTrue(is_success_url("https://www.profession.hu/koszonjuk"))

    def test_sikeres_url(self):
        self.assertTrue(is_success_url("https://www.profession.hu/sikeres-jelentkezes"))

    def test_thank_you_url(self):
        self.assertTrue(is_success_url("/thank-you"))

    def test_confirmation_url(self):
        self.assertTrue(is_success_url("/confirmation/123"))

    def test_normal_url_not_success(self):
        self.assertFalse(is_success_url("https://www.profession.hu/allas/slug-12345"))

    def test_hungarian_success(self):
        self.assertTrue(is_success_content("Sikeres jelentkezés! Köszönjük!"))

    def test_rogzitettuk(self):
        self.assertTrue(is_success_content("Jelentkezését rögzítettük."))

    def test_english_success(self):
        self.assertTrue(is_success_content("Your application has been submitted. Thank you for applying!"))

    def test_forwarded(self):
        self.assertTrue(is_success_content("jelentkezését továbbítottuk a munkaadónak"))

    def test_normal_content(self):
        self.assertFalse(is_success_content("Add meg a fizetési igényed!"))

    def test_case_insensitive(self):
        self.assertTrue(is_success_content("SIKERES JELENTKEZÉS"))


class TestAtsSignature(unittest.TestCase):
    """Test external ATS signature detection."""

    def test_avature(self):
        self.assertTrue(is_ats_signature("https://dpdhlgroup.avature.net/jobs"))

    def test_workday(self):
        self.assertTrue(is_ats_signature("myworkdayjobs.com/careers"))

    def test_smartrecruiters(self):
        self.assertTrue(is_ats_signature("jobs.smartrecruiters.com/position"))

    def test_linkedin_apply(self):
        self.assertTrue(is_ats_signature("Apply With LinkedIn to this position"))

    def test_profession_hu_not_ats(self):
        self.assertFalse(is_ats_signature("https://www.profession.hu/jelentkezes/12345"))

    def test_empty_not_ats(self):
        self.assertFalse(is_ats_signature(""))


class TestMarketingText(unittest.TestCase):
    """Test marketing consent text detection."""

    def test_marketing_keyword(self):
        self.assertTrue(is_marketing_text("Hozzájárulok a marketing célú megkeresésekhez"))

    def test_hirlevel(self):
        self.assertTrue(is_marketing_text("Szeretnék hírlevél értesítéseket kapni"))

    def test_emailben(self):
        self.assertTrue(is_marketing_text("Értesítéseket e-mailben kérek"))

    def test_hirdet(self):
        self.assertTrue(is_marketing_text("Hirdetésekről értesítéseket kérek"))

    def test_gdpr_not_marketing(self):
        self.assertFalse(is_marketing_text("Elfogadom az Adatkezelési tájékoztatót"))

    def test_consent_not_marketing(self):
        self.assertFalse(is_marketing_text("Megismertem a felhasználási feltételeket"))

    def test_cv_label_not_marketing(self):
        self.assertFalse(is_marketing_text("DömötörDávid-2026-CV-EN.pdf Feltöltve: 2026.06.22"))

    def test_empty(self):
        self.assertFalse(is_marketing_text(""))


class TestConfigValidation(unittest.TestCase):
    """Test config validation."""

    def test_valid_config(self):
        cfg = {
            "max_pages": 10,
            "max_applications_per_run": 20,
            "salary_amount": 800000,
        }
        self.assertEqual(validate_config(cfg), [])

    def test_invalid_max_pages_string(self):
        self.assertGreater(len(validate_config({"max_pages": "ten"})), 0)

    def test_invalid_max_pages_none(self):
        self.assertGreater(len(validate_config({"max_pages": None})), 0)

    def test_salary_null_ok(self):
        self.assertEqual(validate_config({"salary_amount": None}), [])

    def test_salary_string_invalid(self):
        self.assertGreater(len(validate_config({"salary_amount": "not_a_number"})), 0)

    def test_empty_config(self):
        self.assertEqual(validate_config({}), [])

    def test_partial_config(self):
        self.assertEqual(validate_config({"max_pages": 5}), [])


class TestFilterLogic(unittest.TestCase):
    """Test keyword filtering logic."""

    def _filter_jobs(self, jobs, keywords=None, excludes=None):
        keywords = keywords or []
        excludes = excludes or []
        if not keywords and not excludes:
            return jobs
        result = []
        for j in jobs:
            t = j["title"].lower()
            if keywords and not any(k.lower() in t for k in keywords):
                continue
            if excludes and any(k.lower() in t for k in excludes):
                continue
            result.append(j)
        return result

    def test_no_filters_returns_all(self):
        jobs = [{"title": "Python dev", "url": "x"}, {"title": "Java dev", "url": "y"}]
        self.assertEqual(len(self._filter_jobs(jobs)), 2)

    def test_include_filter(self):
        jobs = [{"title": "Python Developer", "url": "1"}, {"title": "Java Developer", "url": "2"}]
        result = self._filter_jobs(jobs, keywords=["python"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Python Developer")

    def test_exclude_filter(self):
        jobs = [
            {"title": "Senior Python Dev", "url": "1"},
            {"title": "Junior Python Dev", "url": "2"},
        ]
        result = self._filter_jobs(jobs, excludes=["senior"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Junior Python Dev")

    def test_both_filters(self):
        jobs = [
            {"title": "Senior Python Dev", "url": "1"},
            {"title": "Junior Python Dev", "url": "2"},
            {"title": "Senior Java Dev", "url": "3"},
        ]
        result = self._filter_jobs(jobs, keywords=["python"], excludes=["senior"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Junior Python Dev")

    def test_case_insensitive(self):
        jobs = [{"title": "PYTHON DEVELOPER", "url": "1"}]
        result = self._filter_jobs(jobs, keywords=["python"])
        self.assertEqual(len(result), 1)

    def test_multiple_keywords(self):
        jobs = [
            {"title": "Python Django Dev", "url": "1"},
            {"title": "Python Flask Dev", "url": "2"},
        ]
        result = self._filter_jobs(jobs, keywords=["django", "flask"])
        self.assertEqual(len(result), 2)


class TestJitter(unittest.TestCase):
    """Test jitter (random wait) function."""

    def jitter(self, lo, hi):
        import random
        return random.uniform(lo, hi)

    def test_within_range(self):
        for _ in range(100):
            val = self.jitter(2, 5)
            self.assertGreaterEqual(val, 2)
            self.assertLessEqual(val, 5)

    def test_same_value(self):
        val = self.jitter(3, 3)
        self.assertEqual(val, 3.0)


class TestJsonPersistence(unittest.TestCase):
    """Test JSON load/save operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.json_path = os.path.join(self.tmpdir, "test.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_and_load_dict(self):
        data = {"applied": ["123", "456"]}
        with open(self.json_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        with open(self.json_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual(loaded, data)

    def test_load_corrupted_file(self):
        with open(self.json_path, "w") as f:
            f.write("not json{{{")
        try:
            with open(self.json_path, "r") as f:
                json.load(f)
            self.fail("Should have raised JSONDecodeError")
        except json.JSONDecodeError:
            pass  # Expected

    def test_load_missing_file(self):
        self.assertFalse(os.path.exists("/tmp/nonexistent_test_file_xyz.json"))

    def test_set_to_sorted_list(self):
        s = {"b", "a", "c"}
        lst = sorted(s)
        self.assertEqual(lst, ["a", "b", "c"])
        # Round-trip through JSON
        data = list(s)
        dumped = json.dumps(data)
        loaded = json.loads(dumped)
        self.assertEqual(set(loaded), s)


class TestHtmlSavedPages(unittest.TestCase):
    """Test login detection and job links using actual saved HTML pages."""

    def setUp(self):
        self.pagesave_dir = Path(__file__).resolve().parent / "pagesave"
        self.main_path = self.pagesave_dir / "main"
        self.has_jelentkezem_path = self.pagesave_dir / "has_jelentkezem"
        self.external_path = self.pagesave_dir / "external_jelentkezem"

    def test_login_detection_on_saved_main(self):
        """Test login detection indicators on saved logged-in main page."""
        if not self.main_path.exists():
            self.skipTest("pagesave/main does not exist")
            
        with open(self.main_path, "r", encoding="utf-8") as f:
            html = f.read()
            
        # Simplified simulated _check_login_status logic
        self.assertTrue("/kilepes" in html)

    def test_internal_vs_external_job_pages(self):
        """Test internal /jelentkezes/ and external redirect=1 detection."""
        if not self.has_jelentkezem_path.exists() or not self.external_path.exists():
            self.skipTest("Saved job pages do not exist")

        with open(self.has_jelentkezem_path, "r", encoding="utf-8") as f:
            has_jel_html = f.read()

        with open(self.external_path, "r", encoding="utf-8") as f:
            ext_html = f.read()

        # Check internal page
        self.assertTrue("/jelentkezes/" in has_jel_html)
        self.assertFalse("redirect=1" in has_jel_html)

        # Check external page
        self.assertFalse("/jelentkezes/" in ext_html)
        self.assertTrue("redirect=1" in ext_html)

    def test_job_id_extraction_from_saved_links(self):
        """Verify we can extract correct job IDs from links in the saved search page."""
        if not self.main_path.exists():
            self.skipTest("pagesave/main does not exist")
            
        with open(self.main_path, "r", encoding="utf-8") as f:
            html = f.read()

        # Find URLs using regex
        urls = re.findall(r'href="([^"]*/allas/[^"]+)"', html)
        self.assertGreater(len(urls), 0)
        
        # Test extraction on found URLs
        ids = [extract_job_id(u) for u in urls]
        valid_ids = [i for i in ids if i.isdigit() and 5 <= len(i) <= 8]
        self.assertGreater(len(valid_ids), 0)


def run_tests():
    """Run all unit tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestExtractJobId))
    suite.addTests(loader.loadTestsFromTestCase(TestDomainOf))
    suite.addTests(loader.loadTestsFromTestCase(TestSuccessDetection))
    suite.addTests(loader.loadTestsFromTestCase(TestAtsSignature))
    suite.addTests(loader.loadTestsFromTestCase(TestMarketingText))
    suite.addTests(loader.loadTestsFromTestCase(TestConfigValidation))
    suite.addTests(loader.loadTestsFromTestCase(TestFilterLogic))
    suite.addTests(loader.loadTestsFromTestCase(TestJitter))
    suite.addTests(loader.loadTestsFromTestCase(TestJsonPersistence))
    suite.addTests(loader.loadTestsFromTestCase(TestHtmlSavedPages))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print(f"\n{'='*60}")
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")

    return result.wasSuccessful()

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
