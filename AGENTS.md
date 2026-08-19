# AGENTS.md

Guidance for AI agents and maintainers working in this repository.

## Project summary

Scraper for the SIMASTER lecturer-teaching-schedule page
(`https://simaster.ugm.ac.id/akademik/dsn_jadwal_dosen/`) that attaches to a
Google Chrome instance running on Windows over the Chrome DevTools Protocol (CDP)
from WSL2, reusing the existing SIMASTER session cookies instead of re-authenticating
through the SSO login and image/audio CAPTCHA. It filters the schedule to a lecturer
and semester, then saves CSV + JSON.

Language is Python (Playwright via `connect_over_cdp`), provisioned with conda. No
server-side scraping HTTP client: all data extraction runs against the rendered DOM
in the attached browser.

## Verified environment facts

- This project runs from WSL2, not directly on Windows.
- Windows Chrome executable is mounted at:
  `/mnt/c/Program Files/Google/Chrome/Application/chrome.exe`.
- The logged-in Chrome profile belongs to the **Windows user `asus`** (host
  `laptop-plid3q9t`), at:
  `/mnt/c/Users/asus/AppData/Local/Google/Chrome/User Data`.
  The built-in SIMASTER session cookies are `simaster-ugm_sess` and
  `simasterUGM_cookie` under `simaster.ugm.ac.id` in
  `<User Data>/Default/Network/Cookies`.
- conda (miniforge) 25.3.1 with env `simaster` (Python 3.12 + `playwright` via pip);
  provision from `environment.yml`. Playwright needs **no browser download** for
  `connect_over_cdp`.
- WSL2 uses NAT networking. The Windows host is reachable at the default gateway:
  ```bash
  ip route show default | awk '{print $3}'
  ```
  (currently `172.31.160.1`, but this can change across WSL restarts — always
  discover it, never hardcode).
- Chrome 136+ **ignores** `--remote-debugging-port` when the default user-data dir
  is used. A dedicated `--user-data-dir` is required.
- `--remote-debugging-address=0.0.0.0` does **not** make Chrome bind to all
  interfaces on this build — the port is bound to `127.0.0.1` regardless. WSL2 NAT
  therefore needs a Windows **portproxy** `0.0.0.0:9223 -> 127.0.0.1:9222` plus a
  firewall rule; `setup.sh` (idempotent) creates it.
- CDP can only attach to a Chrome that was started with the debugging flag. A normal
  running Chrome cannot be attached to.

## Reproducible command checklist

1. Close every Chrome window on Windows (so the profile files can be copied).
2. Provision the conda env once (installs the `simaster` package editable + pytest):
   ```bash
   conda env create -f environment.yml
   ```
3. Copy the session profile, ensure the portproxy/firewall rule, and launch the
   debug Chrome (skips cleanly if the debug Chrome is already running):
   ```bash
   bash setup.sh
   ```
4. Verify CDP is reachable from WSL:
   ```bash
   GW=$(ip route show default | awk '{print $3}')
   curl "http://${GW}:9223/json/version"
   ```
   A JSON document with `Browser` / `webSocketDebuggerUrl` confirms connectivity.
5. Run the scraper (single lecturer, or batch from a names file):
   ```bash
   conda run -n simaster simaster --lecturer "Matin Nuhamunada"
   conda run -n simaster simaster --names target.md
   ```
   `python -m simaster ...` and the legacy `python -u scrape.py` shim also work.
6. Aggregate teaching load (per-class share = `(own meetings / 14) * sks`):
   ```bash
   conda run -n simaster simaster analyze --dir data --semester 20261 \
       --min 12 --max 16 --names target.md --outdir results
   ```
7. Expected outputs in the repository root (per lecturer, slugified full name):
   - `jadwal_matin_nuhamunada_s_si_m_sc_20261.csv`
   - `jadwal_matin_nuhamunada_s_si_m_sc_20261.json`
   and in `results/`: `load_summary.csv`, `load_detail.csv`, `load_report.md`.

## How session reuse works (the key trick)

- `setup.sh` copies only the session-bearing profile files from the real profile to
  a dedicated dir `C:\Users\asus\simaster-scrape-udata`: `Local State` (contains the
  cookie-encryption key) and `Default/Network/Cookies` (the simaster session cookies),
  plus `Preferences`/`Secure Preferences`.
- Chrome is then launched with `--user-data-dir=<dedicated dir>`. Because Chrome 136+
  requires a non-default user-data-dir for remote debugging, and because the copied
  `Local State` + cookie DB are intact, the debug Chrome starts logged in.
- If the session is expired, the schedule page redirects to SSO/CAPTCHA — the scraper
  detects this and keeps polling with a "finish login" message while the window stays
  on the login screen. A fresh session requires a manual login in the debug Chrome OR
  re-copying a profile that holds a fresh session.

## Auth / CAPTCHA

- The scraper opens the schedule URL and waits until the schedule form renders
  (`input[name="dosen"]`). If redirected to `cas/login`, `captchasound`, `signin`, or
  `masuk`, it prints a message and polls for up to 30 minutes.
- Normally no manual login is needed thanks to the copied session cookies.

## Package layout

- `src/simaster/scraper.py` — `Scraper` class (one CDP session reused across
  lecturers) + the browser-side JS strings (`EXTRACT_JS`, `PAGINATION_JS`,
  `RESOLVE_JS`, `SUBMIT_JS`).
- `src/simaster/parse.py` — pure parsing (dates, table rows, dosenId matching,
  slugify); the record/date logic lives here, not in JS, for testability.
- `src/simaster/batch.py` — reads the names file (one name per line; blank/`#`
  lines ignored; titles preserved).
- `src/simaster/output.py` — writes `jadwal_<slug>_<semester>.json/.csv`.
- `src/simaster/cli.py` — argparse CLI; `run_all()` accepts an injectable
  scraper factory for offline tests.
- `scrape.py` — legacy shim that calls the CLI with the old hardcoded defaults.
- `tests/` — offline unit tests (`pytest`); live-CDP tests behind
  `@pytest.mark.integration` (skipped by default).
- Batch names from `target.md` include academic titles (e.g.
  `Luthfi Nurhidayat, S.Si., M.Sc.`); the `dosen` form field and filenames use
  the server's canonical `dosenNama`, and the filename slug is the full name
  (`jadwal_luthfi_nurhidayat_s_si_m_sc_20261.*`).

## Gotchas

- Binding to `0.0.0.0:9223` via portproxy exposes CDP to the local network. Acceptable
  for local use; close the debug Chrome when done.
- `setup.sh` skips the profile copy when the debug Chrome is already running (the
  cookie DB is locked). To refresh the session, close the debug Chrome, then re-run
  `setup.sh`.
- The lecturer autocomplete endpoint `.../dsn_jadwal_dosen/list_dosen?term=<name>`
  returns `[{"dosenId":"...","dosenNama":"..."}]`; `dosenId` must accompany `dosen`.
  (`Matin Nuhamunada` → `16764`.)
- Filter submission is a full-page POST (`view_jadwal_mengajar`); the scraper waits
  for the navigation and then a `ul.pagination` element before extracting.
- Result tables paginate as `view_jadwal_mengajar/{offset}/1`, offset = `(page-1)*10`
  (e.g. `/10/1` is page 2). The filter (sesi/dosenId) persists server-side in session
  state, so GET navigation to later offsets works.
- Result DOM: the course table has 8-cell rows (No, Rumpun, Jadwal Harian, Kode, Mata
  Kuliah, Kelas, SKS, Jml Mhs); each course's schedule entries follow immediately as
  sibling `<tr>` rows with 4 cells (`[seq, waktu, ruang, dosen]`), including rows
  hidden with class `closeData` — read all rows, not just visible ones.
- Schedule `waktu` format is `Day DD-MM-YYYY HH:MM-HH:MM`; normalize the date to ISO
  (`YYYY-MM-DD`) in output.
- `conda run` does not forward stdin to `python`; pass code via `-c` or a script file.

## Teaching-load audit (done, semester 20261)

Context / rules confirmed with the user:
- `target.md` now holds all ~68 lecturer names scraped from
  https://biologi.ugm.ac.id/tenaga-pendidik/ (grouped by lab as `#` comments).
- The academic titles on that page are **not synchronized** with SIMASTER
  (e.g. page `Dr. Luthfi Nurhidayat, S.Si., M.Sc.` vs SIMASTER
  `Luthfi Nurhidayat, S.Si., M.Sc.`; page `Ganies Riza A., ...` vs
  `Ganies Riza Aristya, ...`). **Always resolve to the SIMASTER canonical
  `dosenId`/`dosenNama`**; never trust the page titles verbatim.
- `Ridwan Wicaksono, S.T., M.Eng., Ph.D.` was dropped from the old list — no
  longer listed on the tenaga-pendidik page.

Formula (confirmed):
- Credit is counted **per class** (key = `kode` + `kelas`).
- A class should have **14 meetings** per semester.
- Per-lecturer share of a class = `(meetings taught by that lecturer in the
  class / 14) * sks`. Total load = sum over classes.
- Flags: `UNDERLOADED < 12 SKS`, `OVERLOADED > 16 SKS` (min 12 / max 16
  confirmed), otherwise `OK`; `NO_DATA` when no scrape result exists.

Implemented:
- Phase 2 — name resolution (`src/simaster/parse.py`):
  - `best_match(data, lecturer)` — exact-substring fast path, then fuzzy
    `difflib.SequenceMatcher` (threshold `FUZZY_THRESHOLD = 0.6`).
  - `term_candidates(lecturer)` — **skips leading academic titles** when
    choosing the `list_dosen` autocomplete term. A bare `Dr.`/`Prof.` term can
    return thousands of candidates that exclude the target (whose SIMASTER name
    often drops the title) and fuzzy-match a wrong title-holder. It tries
    `"Given Next"` then `"Given"`, with a title-stripped fallback for glued
    forms like `Dr.Utaminingsih`. This fixed 4 mis-resolutions in the 20261 run
    (Dila Hening→Ardaning, Nur Indah→Arima, Luthfi→Shidiq, Atikah→Fikri).
  - `find_dosen`/`canonical_name`/`Scraper.resolve_dosen` share it.
- Phase 3 — `src/simaster/load.py`:
  - `compute_lecturer_load(courses, dosen)` — per class: `class_meetings`,
    `own_meetings` (folded match against `meta.dosen`), `own_credit`.
  - `aggregate_loads(directory, semester, min, max, names)` — reads all
    `jadwal_*_<semester>.json`, dedupes by `dosen`, flags classes with
    meetings != 14, reports `NO_DATA` for expected names without files.
  - CLI subcommand `simaster analyze`; scrape flags unchanged.
  - Outputs: `load_summary.csv`, `load_detail.csv`, `load_report.md`.
- Phase 4 — executed (live CDP):
  1. `conda run -n simaster pytest` (80 offline tests green).
  2. `simaster --names target.md --outdir data --semester 20261` — 63 of 68
     lecturers written; 5 have no courses in SIMASTER for 20261 (legitimate
     `NO_DATA`): Akbar Reza, Dr. Mirza Hanif Al Falah, Rendi Mahadi, Annas
     Rabbani, Novita Yustinadiar.
  3. `simaster analyze --dir data --semester 20261 --min 12 --max 16 --names target.md --outdir results`
  4. Findings below; README + AGENTS.md updated.

20261 findings (from `results/load_report.md`): 55 `UNDERLOADED`, 7 `OK`
(12.79–16.00 SKS), 1 `OVERLOADED` (Dr. Rury Eprilurahman, 18.21), 5 `NO_DATA`.
The low totals are driven by real SIMASTER data: ~570 of 1203 classes have **no
booked meetings** (verified in the rendered DOM — course rows with an empty
"Jadwal Harian" cell, e.g. thesis/practicum courses), contributing 0 SKS, and
many scheduled classes have fewer than the 14-meeting baseline (784 warnings).
Offline verification: `python -m simaster`/`pytest` don't need the browser.