"""Scrape SIMASTER lecturer schedules through a CDP-attached Chrome.

The scraper attaches to a Chrome instance that was launched with
``--remote-debugging-port`` (see ``setup.sh``), reusing its SIMASTER session
cookies. All data extraction runs against the rendered DOM.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import datetime

from playwright.sync_api import Page, sync_playwright

from .parse import (
    canonical_name,
    current_offset,
    find_dosen,
    parse_schedule_waktu,
    parse_table_rows,
)

SEMESTER = "20261"
BASE = "https://simaster.ugm.ac.id/akademik/dsn_jadwal_dosen"
MAX_LOGIN_MIN = 30
LOGIN_MARKERS = ["cas/login", "captchasound", "signin", "masuk"]

# Read every tbody row's cells as raw text; Python-side logic builds records.
EXTRACT_JS = r"""() => {
  const t = document.querySelector('table.table.table-striped.table-bordered.table-hover');
  if (!t) return {rows: [], total: null};
  const pageInfo = document.body.innerText.match(/Tampil\s+\d+\s+sampai\s+\d+\s+dari\s+(\d+)/i);
  const rows = [];
  for (const r of t.querySelectorAll('tbody > tr')) {
    rows.push(Array.from(r.querySelectorAll(':scope > td')).map(c => c.textContent.trim()));
  }
  return {rows: rows, total: pageInfo ? parseInt(pageInfo[1], 10) : null};
}"""

# Just hrefs; offsets are parsed in Python for testability.
PAGINATION_JS = r"""() => Array.from(document.querySelectorAll('ul.pagination a[href]'))
  .map(a => (a.getAttribute('href') || '').trim())
  .filter(h => /view_jadwal_mengajar\//.test(h))"""

RESOLVE_JS = """
async (term) => {
  const r = await fetch('/akademik/dsn_jadwal_dosen/list_dosen?term=' + encodeURIComponent(term), {
    headers: {'X-Requested-With': 'XMLHttpRequest'}
  });
  return {status: r.status, text: await r.text()};
}
"""

SUBMIT_JS = """
(args) => {
  const form = document.querySelector('form[action*="view_jadwal_mengajar"]');
  const sesi = form.querySelector('[name="sesi"]');
  const dos = form.querySelector('[name="dosen"]');
  const did = form.querySelector('[name="dosenId"]');
  if (sesi) sesi.value = args.sesi;
  if (did) did.value = args.dosenId;
  if (dos) dos.value = args.dosen;
  form.submit();
}
"""


def windows_host() -> str:
    """Discover the WSL2 default gateway (the Windows host)."""
    out = subprocess.run(
        ["ip", "route", "show", "default"], capture_output=True, text=True
    ).stdout
    m = re.search(r"default via (\S+)", out)
    if not m:
        raise RuntimeError("Cannot discover Windows host gateway IP")
    return m.group(1)


def default_endpoint() -> str:
    return f"http://{windows_host()}:9223"


class Scraper:
    """Connects to a debug Chrome once and reuses the session across lecturers."""

    def __init__(
        self,
        endpoint: str | None = None,
        base: str = BASE,
        semester: str = SEMESTER,
        max_login_min: int = MAX_LOGIN_MIN,
        verbose: bool = False,
        poll_seconds: float = 5.0,
    ):
        self.endpoint = endpoint or default_endpoint()
        self.base = base.rstrip("/")
        self.semester = semester
        self.max_login_min = max_login_min
        self.verbose = verbose
        self.poll_seconds = poll_seconds
        self._playwright = None
        self._browser = None
        self.page: Page | None = None

    def __enter__(self) -> "Scraper":
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.connect_over_cdp(self.endpoint)
        ctx = self._browser.contexts[0]
        self.page = ctx.new_page()
        return self

    def __exit__(self, *exc):
        try:
            if self.page is not None:
                self.page.close()
        finally:
            if self._browser is not None:
                self._browser.close()
            if self._playwright is not None:
                self._playwright.stop()

    # -- page plumbing ---------------------------------------------------

    def wait_for_auth(self, page: Page):
        """Wait until the schedule form renders, polling for a manual login."""
        deadline = time.time() + self.max_login_min * 60
        while time.time() < deadline:
            url = page.url
            has_dosen = page.locator('input[name="dosen"]').count() > 0
            is_login = any(m in url for m in LOGIN_MARKERS)
            if has_dosen and not is_login:
                print("[scrape] authenticated, schedule form present.")
                return
            print(
                "[scrape] waiting for login... if automated, finish login in the Chrome window now. "
                f"(url={url})"
            )
            time.sleep(self.poll_seconds)
        raise RuntimeError("Timed out waiting for SIMASTER authentication.")

    def resolve_dosen(self, page: Page, lecturer: str) -> tuple[str, str]:
        """Resolve dosenId + canonical name via the list_dosen autocomplete."""
        term = lecturer.split(" ")[0]
        print(f"[scrape] resolving dosenId via list_dosen?term={term}")
        raw = page.evaluate(RESOLVE_JS, term)
        body = raw["text"] if self.verbose else raw["text"][:300]
        print(f"[scrape] list_dosen status={raw['status']} body={body}")
        data = (
            json.loads(raw["text"]) if raw["status"] == 200 and raw["text"].strip() else []
        )
        dosen_id = find_dosen(data, lecturer)
        if not dosen_id:
            raise LookupError(f"could not resolve dosenId for '{lecturer}'")
        name = canonical_name(data, lecturer) or lecturer
        print(f"[scrape] dosenId={dosen_id} canonical='{name}'")
        return dosen_id, name

    def submit_filter(self, page: Page, dosen_id: str, lecturer: str):
        """Fill the hidden form and POST to view_jadwal_mengajar."""
        with page.expect_navigation(timeout=60000, wait_until="domcontentloaded"):
            page.evaluate(
                SUBMIT_JS,
                {"sesi": self.semester, "dosenId": dosen_id, "dosen": lecturer},
            )
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_selector("ul.pagination", timeout=30000)
        time.sleep(1)

    # -- scraping --------------------------------------------------------

    def scrape(self, lecturer: str) -> dict:
        """Scrape one lecturer. Returns ``{meta, courses, total}``."""
        page = self.page
        assert page is not None
        page.goto(f"{self.base}/", wait_until="domcontentloaded", timeout=60000)
        self.wait_for_auth(page)
        dosen_id, canonical = self.resolve_dosen(page, lecturer)
        self.submit_filter(page, dosen_id, canonical)

        courses: list[dict] = []
        total: int | None = None
        while True:
            res = page.evaluate(EXTRACT_JS)
            rows = res["rows"]
            if res["total"] is not None:
                total = res["total"]
            courses.extend(parse_table_rows(rows))
            cur = current_offset(page.url)
            print(
                f"[scrape] page offset {cur}: {len(rows)} course rows "
                f"(total entries so far: {sum(len(c['jadwal']) for c in courses)})"
            )

            hrefs = page.evaluate(PAGINATION_JS)
            offsets = sorted({current_offset(h) for h in hrefs if current_offset(h) > 0})
            next_off = next((o for o in offsets if o > cur), None)
            if next_off is None:
                break
            href = next(h for h in hrefs if current_offset(h) == next_off)
            page.goto(href, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector("ul.pagination", timeout=30000)
            time.sleep(1)

        for c in courses:
            for e in c["jadwal"]:
                e.update(parse_schedule_waktu(e["waktu"]))
                e.pop("waktu", None)

        return {
            "lecturer": lecturer,
            "canonical": canonical,
            "dosenId": dosen_id,
            "courses": courses,
            "total": total,
        }

    def scrape_many(self, lecturers: list[str]) -> list[dict]:
        """Scrape a list of lecturers, continuing past individual failures."""
        results: list[dict] = []
        for lecturer in lecturers:
            try:
                results.append(self.scrape(lecturer))
            except (LookupError, RuntimeError) as exc:
                print(f"[scrape] ERROR for '{lecturer}': {exc}")
                results.append({"lecturer": lecturer, "error": str(exc), "courses": []})
        return results


def build_meta(result: dict, semester: str) -> dict:
    """Summary metadata for one lecturer result."""
    courses = result["courses"]
    return {
        "semester": semester,
        "dosen": result.get("canonical", result["lecturer"]),
        "dosenId": result.get("dosenId"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_courses": len(courses),
        "total_entries": sum(len(c["jadwal"]) for c in courses),
        "reported_total": result.get("total"),
    }
