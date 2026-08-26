# SIMASTER Lecturer Schedule Scraper

Scrapes lecturer teaching schedules from the SIMASTER portal
(`https://simaster.ugm.ac.id/akademik/dsn_jadwal_dosen/`) by attaching to a Google
Chrome instance running on Windows from WSL2 over the Chrome DevTools Protocol
(CDP).

The target page requires a SIMASTER SSO login with an image/audio CAPTCHA. Instead
of automating that flow, this project **reuses the session cookies** from the Chrome
profile that already holds a SIMASTER login. No credentials are ever asked for.

It is organized as an installable Python package (`simaster`) with a CLI, and
supports both single-lecturer and batch scraping (from a text file of names),
plus a teaching-load audit command (`simaster analyze`) and a self-contained
HTML dashboard (`simaster dashboard`).

## Outputs

Running the scraper produces two files per lecturer:

- `jadwal_<name>_<semester>.csv` — flat rows, one per schedule entry.
- `jadwal_<name>_<semester>.json` — nested: every course with its full schedule.

The `<name>` part is the lecturer's slugified full name, e.g.
`Matin Nuhamunada, S.Si., M.Sc.` → `jadwal_matin_nuhamunada_s_si_m_sc_20261.csv`.
For the default run (semester `20261` / Gasal 2026-2027, lecturer *Matin
Nuhamunada*) this yields **15 courses / 153 schedule entries**.

## Prerequisites

- Windows with Google Chrome installed.
- WSL2 with conda (miniforge recommended).
- A Windows Chrome profile whose SIMASTER session is still valid
  (`C:\Users\<user>\AppData\Local\Google\Chrome\User Data`).

## Steps


### Clone the repository and create the environment
First, clone the repository

```bash
git clone https://github.com/matinnuhamunada/simaster_jadwal_dosen.git.
cd simaster_jadwal_dosen
```

Then, create a `.env` file in the project root with your Windows username:

```env
WIN_USER="your_windows_username"
```

This is used by `setup.sh` to locate your Chrome profile. The default is `asus` if not set.

### Close every Chrome window on Windows

The profile files (`Local State`, `Network/Cookies`) can only be copied when Chrome
is not holding them. Close **all** Chrome windows first.

### Provision the conda environment (once)

```bash
conda env create -f environment.yml
```

Creates env `simaster` (Python 3.12 + Playwright), installs the `simaster` package
(editable), and adds pytest. Playwright attaches to the existing Chrome over CDP,
so **no browser download is needed**.

> To pick up package changes after a `git pull`, re-run `conda env update -f
> environment.yml` (the editable install tracks the source automatically).

### Run the setup script

```bash
bash setup.sh
```

`setup.sh` is idempotent and does four things:

1. Copies the session profile (`Local State` + cookie DB) from
   `C:\Users\asus\AppData\Local\Google\Chrome\User Data` into a dedicated
   user-data dir `C:\Users\asus\simaster-scrape-udata`.
2. Ensures a Windows portproxy `0.0.0.0:9223 -> 127.0.0.1:9222` plus a firewall
   rule (needed because WSL2 NAT cannot reach a loopback-only port).
3. Launches Chrome detached with `--remote-debugging-port=9222` on the copied
   profile (skipped if the debug Chrome is already running).
4. Verifies CDP connectivity from WSL.

Why a copied profile? Chrome 136+ disables remote debugging for the **default**
user-data dir. The copy keeps the session cookies while giving Chrome a dedicated,
debriefable user-data dir.

### Run the scraper

Single lecturer:

```bash
conda run -n simaster simaster --lecturer "Matin Nuhamunada"
```

Batch scraping from a file (one name per line, blank lines and `#` comments
ignored):

```bash
conda run -n simaster simaster --names target.md
```

The old hardcoded entry point still works as a thin shim:

```bash
conda run -n simaster python -u scrape.py
```

If the SIMASTER session has expired, the scraper prints a message and polls for up
to `--max-login-min` minutes (default 30) while you finish the login manually in
the open Chrome window, then continues on its own.

### Clean the raw schedules

The raw files list every class session in each co-teacher's file, so the same
session appears once per co-teacher. `clean` aggregates all raw CSVs, deletes
those redundant sessions, and writes a deduplicated per-lecturer dataset into a
new folder — raw `data/` is never modified:

```bash
conda run -n simaster simaster clean --dir data --semester 20261 \
    --names target.md --outdir data/clean
```

Outputs:

- `data/clean/sessions.csv` — the faculty-wide unique session catalog (each
  session once, ~2820 rows vs ~9200 raw rows).
- `data/clean/jadwal_<name>_<semester>.json` — per lecturer: own sessions only
  (co-teacher sessions dropped, within-file duplicates removed), 0-meeting
  assigned classes kept, and each course annotated with `class_meetings` /
  `own_meetings`. Meta gains `own_entries` (only the lecturer's own sessions),
  `est_sks` (scheduled → `own/14*sks`, unscheduled → full `sks`),
  `est_sks_no_s3` (excludes S3 / DOKTOR BIOLOGI), `n_unscheduled`, `n_s3`.

### Analyze teaching load

Aggregate the cleaned schedules into per-lecturer teaching-load (in SKS) and
flag under-/over-loaded lecturers:

```bash
conda run -n simaster simaster analyze --dir data/clean --semester 20261 \
    --min 12 --max 16 --names target.md --outdir results
```

Credit is counted **per class** (`kode` + `kelas`): a full class has **14
meetings** per semester, and a lecturer's share of a class is
`(meetings they teach / 14) * sks`. Their total load is the sum over all their
classes.

Status is banded from the strict teaching SKS (`total_sks`), defaulting to:

| Band (teaching SKS) | Status |
| --- | --- |
| `< 6` | `WARNING` |
| `6 – 8` | `UNDERLOADED` |
| `8 – 12` | `OK` (ideal target) |
| `12 – 16` | `ABOVE` (within limit) |
| `> 16` | `OVERLOADED` |

The 12-SKS official minimum already includes research, so the ideal teaching
load is 8–12; 16 is the limit and itself covers research, community service and
supporting activities. `--warn` / `--min` / `--max` change the band edges;
lecturers in `--names` without a result are reported `NO_DATA`. Classes with a
meeting count outside the expected **8–14** range are listed as warnings (e.g.
courses with no booked meetings, which contribute 0 SKS to the strict total).

Outputs (written to `--outdir`, default `.`):

- `load_summary.csv` — lecturer, strict total SKS, estimated SKS (`est_sks`,
  unscheduled classes assumed at full credit), estimated excluding S3
  (`est_sks_no_s3`), #unscheduled classes, #S3 classes, status.
- `load_detail.csv` — one row per class (class meetings, own meetings, strict
  credit, estimated credit, S3 flag).
- `load_report.md` — grouped human-readable report with the same columns plus
  warnings for any class whose meeting count differs from 14 (e.g. courses with
  no booked meetings, which contribute 0 SKS to the strict total).

The `status` flag is banded from `total_sks` (see the table above); estimated
`est_sks` and `est_sks_no_s3` are reported alongside for comparison.

### Generate a dashboard

Build a single self-contained HTML file (no server, works offline, open
directly in a browser) summarizing the same teaching-load data as `analyze`,
with sortable/filterable tables:

```bash
conda run -n simaster simaster dashboard --dir data/clean --semester 20261 \
    --min 12 --max 16 --names target.md --outdir results
```

Takes the same `--dir` / `--semester` / `--min` / `--max` / `--warn` /
`--names` / `--outdir` options as `analyze` (see above for band definitions)
and writes `load_dashboard.html`: status-colored summary cards, a
click-to-sort/filterable lecturers table, and a filterable per-class detail
table (clicking a lecturer row filters the class table to their classes). The
file has inline CSS/JS and no external assets or network calls, so it's safe
to email or open from a USB stick.

### CLI reference

```
simaster [--lecturer NAME]... [--names FILE]... [--semester SEMESTER]
         [--outdir DIR] [--endpoint URL] [--max-login-min MIN]
         [--verbose] [--version]

simaster analyze --dir DIR --semester SEMESTER [--warn WARN] [--min MIN]
                 [--max MAX] [--names FILE] [--outdir DIR]

simaster dashboard --dir DIR --semester SEMESTER [--warn WARN] [--min MIN]
                   [--max MAX] [--names FILE] [--outdir DIR]

simaster clean --dir DIR --semester SEMESTER --names FILE [--outdir DIR]
```

| Flag | Meaning |
| ---- | ------- |
| `--lecturer NAME` | Lecturer to scrape. Repeatable. |
| `--names FILE` | Text file with one lecturer name per line. Repeatable. |
| `--semester` | Semester code (default `20261`). |
| `--outdir` | Output directory for scrape files / `clean` / `analyze` reports (default `.`, `data/clean`, `.` respectively). |
| `--endpoint` | CDP base URL, e.g. `http://172.31.160.1:9223` (default: auto-discovered WSL gateway). |
| `--max-login-min` | Minutes to wait for a manual login (default `30`). |
| `--verbose` | Print the full `list_dosen` responses. |
| `analyze --dir` | Directory holding `jadwal_*.json` results (use `data/clean/` for the clean dataset). |
| `analyze --min` | Lower edge of the ideal OK band (default `8`). |
| `analyze --max` | Overload limit (default `16`). |
| `analyze --warn` | Below this teaching SKS is a WARNING (default `6`). |
| `dashboard --dir` | Directory holding `jadwal_*.json` results (use `data/clean/` for the clean dataset). |
| `dashboard --min` | Lower edge of the ideal OK band (default `8`). |
| `dashboard --max` | Overload limit (default `16`). |
| `dashboard --warn` | Below this teaching SKS is a WARNING (default `6`). |

Provide at least one `--lecturer` or `--names`. Names are deduplicated, and all
lecturers share one Chrome session. Per-lecturer failures (e.g. an unresolvable
`dosenId`) are reported and the remaining names are still scraped; the exit code
is non-zero if any name failed.

## Running the tests

```bash
conda run -n simaster pytest
```

The test suite is fully offline (parsing, pagination, batch inputs, output
writing, CLI, and scraper orchestration against a fake page). A live-CDP test is
available behind `@pytest.mark.integration` and is skipped by default.

## Troubleshooting

| Symptom | Likely cause | Fix |
| ------- | ------------ | --- |
| `setup.sh` warns the copied cookie DB is small | Source profile still running / locked | Close all Chrome windows, re-run `setup.sh` |
| `curl` to `:9223` refused / times out | Portproxy or firewall rule missing, or WSL gateway IP changed | Re-run `bash setup.sh` (idempotent) |
| `/json/version` empty even after setup | Chrome launched without `--user-data-dir`, or opened into the old default-profile instance | Close all Chrome, re-run `setup.sh` |
| Scraper says "waiting for login..." forever | Session expired server-side | Log in manually in the debug Chrome window, or refresh the profile copy |
| `0 rows` in output / `could not resolve dosenId` | `dosenId` could not be resolved (`list_dosen` response changed) | Re-run with `--verbose`, inspect the printed `list_dosen` body, and update the parsing in `src/simaster/parse.py` |

## Security note

`0.0.0.0:9223` exposes the debugging endpoint to the local network. Fine for
personal use; close the debug Chrome when done.

## Internals

- **Filter** — the scraper resolves the lecturer id from
  `.../dsn_jadwal_dosen/list_dosen?term=<name>` (response:
  `[{"dosenId","dosenNama"}]`), fills the hidden `dosenId` + `sesi` + `dosen` with
  the server's canonical name, and POSTs to `view_jadwal_mengajar`.
- **Extraction** — course rows are 8-cell rows; each course's schedule entries
  follow as 4-cell sibling `<tr>` rows (`[seq, waktu, ruang, dosen]`), including
  hidden `closeData` rows. The browser-side JS reads every row into raw cell
  arrays; the record/date parsing lives in pure Python (`src/simaster/parse.py`)
  for testability. Dates (`Day DD-MM-YYYY HH:MM-HH:MM`) are normalized to ISO.
- **Pagination** — `view_jadwal_mengajar/{offset}/1`, offset = `(page-1)*10`; the
  filter persists server-side in session state so GET navigation works.