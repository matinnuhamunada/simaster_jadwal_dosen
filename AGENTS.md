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
6. Expected outputs in the repository root (per lecturer, slugified full name):
   - `jadwal_matin_nuhamunada_s_si_m_sc_20261.csv`
   - `jadwal_matin_nuhamunada_s_si_m_sc_20261.json`

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