import json
from contextlib import nullcontext

import pytest

from simaster.scraper import (
    EXTRACT_JS,
    PAGINATION_JS,
    RESOLVE_JS,
    SUBMIT_JS,
    Scraper,
)

BASE = "https://simaster.ugm.ac.id/akademik/dsn_jadwal_dosen"
RESULT_URL = f"{BASE}/view_jadwal_mengajar"
RESULT_URL_10 = f"{BASE}/view_jadwal_mengajar/10/1"

PAYLOAD = [
    {"dosenId": "16764", "dosenNama": "Matin Nuhamunada, S.Si., M.Sc."},
]

COURSE_A = [
    ["1", "[PRODI] S1 BIOLOGI", "h", "BISB262101", "Bahasa Inggris", "IUP", "2.00", ""],
    ["1", "Jumat 21-08-2026 07:15-08:55", "Ruang 1", "Matin Nuhamunada, S.Si., M.Sc."],
]
COURSE_B = [
    ["2", "[PRODI] S1 BIOLOGI", "h", "BISB262102", "Genetika", "A", "3.00", "40"],
    ["1", "Senin 02-09-2026 10:00-11:40", "Ruang 2", "Matin Nuhamunada, S.Si., M.Sc."],
]


class FakeLocator:
    def __init__(self, count):
        self._count = count

    def count(self):
        return self._count


class FakePage:
    def __init__(self, pages=None, resolve_payload=None, login=False, selector_error=None):
        self.pages = pages or {}
        self.resolve_payload = resolve_payload or []
        self.login = login
        self.selector_error = selector_error
        self.url = ""
        self.submit_args = None

    def _payload_for(self, term):
        if isinstance(self.resolve_payload, dict):
            return self.resolve_payload.get(term, [])
        return self.resolve_payload

    def goto(self, url, **kw):
        self.url = url

    def evaluate(self, js, arg=None):
        if js is EXTRACT_JS:
            info = self.pages.get(self.url, {"rows": [], "hrefs": [], "total": None})
            return {"rows": info["rows"], "total": info["total"]}
        if js is PAGINATION_JS:
            return self.pages.get(self.url, {}).get("hrefs", [])
        if js is RESOLVE_JS:
            return {"status": 200, "text": json.dumps(self._payload_for(arg))}
        if js is SUBMIT_JS:
            self.submit_args = arg
            self.url = RESULT_URL
            return None
        raise AssertionError(f"unexpected evaluate: {str(js)[:40]!r}")

    def expect_navigation(self, *a, **kw):
        return nullcontext()

    def wait_for_load_state(self, *a, **kw):
        return None

    def wait_for_selector(self, sel, **kw):
        if self.selector_error and sel in self.selector_error:
            raise TimeoutError(f"wait_for_selector timeout: {sel}")
        return None

    def locator(self, sel):
        return FakeLocator(0 if self.login else 1)


def make_scraper(page, **kw):
    sc = Scraper(endpoint="http://fake:9223", base=BASE, **kw)
    sc.page = page
    return sc


def test_wait_for_auth_times_out(capsys):
    page = FakePage(login=True)
    sc = make_scraper(page, max_login_min=0, poll_seconds=0.001)
    with pytest.raises(RuntimeError, match="Timed out"):
        sc.wait_for_auth(page)


def test_wait_for_auth_passes_when_authenticated():
    page = FakePage()
    sc = make_scraper(page)
    sc.wait_for_auth(page)


def test_scrape_paginates_and_uses_canonical_name():
    pages = {
        RESULT_URL: {"rows": COURSE_A, "hrefs": [RESULT_URL_10], "total": 2},
        RESULT_URL_10: {"rows": COURSE_B, "hrefs": [RESULT_URL_10], "total": 2},
    }
    page = FakePage(pages=pages, resolve_payload=PAYLOAD)
    sc = make_scraper(page)
    result = sc.scrape("Matin Nuhamunada")

    assert result["dosenId"] == "16764"
    assert result["canonical"] == "Matin Nuhamunada, S.Si., M.Sc."
    assert page.submit_args["dosen"] == "Matin Nuhamunada, S.Si., M.Sc."
    assert page.submit_args["sesi"] == "20261"
    assert page.submit_args["dosenId"] == "16764"
    assert result["total"] == 2
    assert len(result["courses"]) == 2
    course = result["courses"][0]
    assert course["kode"] == "BISB262101"
    assert course["jadwal"][0] == {
        "ruang": "Ruang 1",
        "dosen": "Matin Nuhamunada, S.Si., M.Sc.",
        "hari": "Jumat",
        "tanggal": "2026-08-21",
        "jam": "07:15-08:55",
    }


def test_scrape_single_page_no_pagination():
    pages = {
        RESULT_URL: {"rows": COURSE_A, "hrefs": [], "total": None},
    }
    page = FakePage(pages=pages, resolve_payload=PAYLOAD)
    sc = make_scraper(page)
    result = sc.scrape("Matin Nuhamunada")
    assert len(result["courses"]) == 1
    assert result["total"] is None


def test_submit_filter_tolerates_missing_result_table():
    pages = {
        RESULT_URL: {"rows": [], "hrefs": [], "total": None},
    }
    page = FakePage(
        pages=pages,
        resolve_payload=PAYLOAD,
        selector_error="table.table.table-striped.table-bordered.table-hover, ul.pagination",
    )
    sc = make_scraper(page)
    result = sc.scrape("Matin Nuhamunada")
    assert result["courses"] == []


def test_scrape_unresolvable_raises_lookup_error():
    page = FakePage(resolve_payload=[{"dosenId": "999", "dosenNama": "Someone Else"}])
    sc = make_scraper(page)
    with pytest.raises(LookupError, match="could not resolve dosenId"):
        sc.scrape("Matin Nuhamunada")


def test_resolve_falls_back_to_stripped_title_term():
    payloads = {
        "Dr.Utaminingsih": [],
        "Utaminingsih": [{"dosenId": "13126", "dosenNama": "Dr. Utaminingsih, S.Si., M.Sc."}],
    }
    page = FakePage(resolve_payload=payloads)
    sc = make_scraper(page)
    assert sc.resolve_dosen(page, "Dr.Utaminingsih S.Si., M.Sc.") == (
        "13126",
        "Dr. Utaminingsih, S.Si., M.Sc.",
    )


def test_resolve_uses_given_name_not_broad_title_term():
    payloads = {
        "Dr.": [{"dosenId": "5995", "dosenNama": "Dr. Ardaning Nuriliani, S.Si., M.Kes."}],
        "Dila Hening": [
            {"dosenId": "16011", "dosenNama": "Dila Hening Windyaraini, S.Si., M.Sc."}
        ],
        "Dila": [
            {"dosenId": "16011", "dosenNama": "Dila Hening Windyaraini, S.Si., M.Sc."}
        ],
    }
    page = FakePage(resolve_payload=payloads)
    sc = make_scraper(page)
    assert sc.resolve_dosen(page, "Dr. Dila Hening Windyarini, S.Si., M.Sc.") == (
        "16011",
        "Dila Hening Windyaraini, S.Si., M.Sc.",
    )


def test_scrape_many_continues_past_failure(capsys):
    page = FakePage(resolve_payload=PAYLOAD)
    sc = make_scraper(page)
    results = sc.scrape_many(["Matin Nuhamunada", "Nobody Here"])
    assert len(results) == 2
    assert "error" not in results[0]
    assert results[1]["error"] and results[1]["courses"] == []