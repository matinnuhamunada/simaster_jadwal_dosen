"""Self-contained static HTML dashboard for SIMASTER teaching-load reports.

Like ``load.build_report``, this hand-builds the output with plain string
formatting (no templating engine, no new dependency) so it can run fully
offline: a single ``.html`` file with inline CSS/JS and no external assets.
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

from .load import OK_HIGH_SKS, PROGRAM_LEVELS, WARN_SKS

DASHBOARD_FILENAME = "load_dashboard.html"

STATUS_ORDER = ["OVERLOADED", "ABOVE", "OK", "UNDERLOADED", "WARNING", "NO_DATA"]

STATUS_COLORS = {
    "OVERLOADED": "#c0392b",
    "ABOVE": "#d68910",
    "OK": "#1e8449",
    "UNDERLOADED": "#b7950b",
    "WARNING": "#e74c3c",
    "NO_DATA": "#607d8b",
}

LEVEL_COLORS = {
    "S1": "#2874a6",
    "S2": "#6c3483",
    "S3": "#117864",
    "PROFESI": "#935116",
    "OTHER": "#616a6b",
}

LECTURER_COLUMNS = [
    ("dosen", "Lecturer"),
    ("total_sks", "Total SKS"),
    ("est_sks", "Est. SKS"),
    ("est_sks_no_s3", "Est. (no S3)"),
    ("n_classes", "#Classes"),
    ("n_courses", "#Courses"),
    ("n_unscheduled", "#Unsched."),
    ("n_s3", "#S3"),
    ("status", "Status"),
]

CLASS_COLUMNS = [
    ("dosen", "Lecturer"),
    ("kode", "Kode"),
    ("mata_kuliah", "Mata Kuliah"),
    ("rumpun", "Rumpun/Prodi"),
    ("level", "Level"),
    ("kelas", "Kelas"),
    ("sks", "SKS"),
    ("class_meetings", "Meetings"),
    ("own_meetings", "Own"),
    ("own_credit", "Credit"),
    ("est_credit", "Est."),
    ("is_s3", "S3"),
]


def _e(v) -> str:
    return html.escape(str(v), quote=True)


def _json_for_script(data) -> str:
    return json.dumps(data).replace("</", "<\\/")


def _status_css() -> str:
    return "\n".join(
        f".status-{status} {{ --status-color: {color}; }}"
        for status, color in STATUS_COLORS.items()
    )


def _level_css() -> str:
    return "\n".join(
        f".level-{level} {{ --level-color: {color}; }}"
        for level, color in LEVEL_COLORS.items()
    )


def _level_cards(result: dict) -> str:
    counts = {level: 0 for level in PROGRAM_LEVELS}
    for row in result["classes"]:
        counts[row["level"]] = counts.get(row["level"], 0) + 1
    cards = []
    for level in PROGRAM_LEVELS:
        cards.append(
            f'<div class="card level-{level}" '
            f'onclick="classFilterInput.value=\'{level}\';classTable.render();">'
            f'<div class="card-count">{counts[level]}</div>'
            f'<div class="card-label">{_e(level)}</div></div>'
        )
    return "\n".join(cards)


def _stat_cards(result: dict) -> str:
    counts = {status: 0 for status in STATUS_ORDER}
    for row in result["lecturers"]:
        counts[row["status"]] = counts.get(row["status"], 0) + 1

    cards = [
        f'<div class="card" data-status="" onclick="filterInput.value=\'\';renderLecturers();">'
        f'<div class="card-count">{len(result["lecturers"])}</div>'
        f'<div class="card-label">Total lecturers</div></div>',
        f'<div class="card" data-status="" onclick="document.getElementById(\'warnings\').scrollIntoView();">'
        f'<div class="card-count">{len(result["warnings"])}</div>'
        f'<div class="card-label">Warnings</div></div>',
    ]
    for status in STATUS_ORDER:
        cards.append(
            f'<div class="card status-{status}" '
            f'onclick="filterInput.value=\'{status}\';renderLecturers();">'
            f'<div class="card-count">{counts[status]}</div>'
            f'<div class="card-label">{_e(status)}</div></div>'
        )
    return "\n".join(cards)


def _warnings_html(warnings: list[str]) -> str:
    if not warnings:
        return "<li><em>none</em></li>"
    return "\n".join(f"<li>{_e(w)}</li>" for w in warnings)


def render_dashboard(result: dict) -> str:
    """Render the full aggregate_loads() result into one HTML document."""
    semester = _e(result.get("semester", ""))
    warn = result.get("warn_sks", WARN_SKS)
    ok_min = result.get("min_sks", 8.0)
    ok_high = result.get("ok_high", OK_HIGH_SKS)
    max_sks = result.get("max_sks", 16.0)
    generated = datetime.now().isoformat(timespec="seconds")

    lecturer_cols_json = _json_for_script([key for key, _ in LECTURER_COLUMNS])
    class_cols_json = _json_for_script([key for key, _ in CLASS_COLUMNS])
    lecturers_json = _json_for_script(result["lecturers"])
    classes_json = _json_for_script(result["classes"])

    lecturer_headers = "\n".join(
        f'<th data-key="{key}">{_e(label)}</th>' for key, label in LECTURER_COLUMNS
    )
    class_headers = "\n".join(
        f'<th data-key="{key}">{_e(label)}</th>' for key, label in CLASS_COLUMNS
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>SIMASTER Teaching Load Dashboard - {semester}</title>
<style>
:root {{
  --bg: #f5f6f8;
  --panel: #ffffff;
  --text: #1c2226;
  --muted: #5b6570;
  --border: #dfe3e7;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  padding: 1.5rem;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
}}
.container {{ max-width: 1200px; margin: 0 auto; }}
header h1 {{ margin: 0 0 0.25rem; }}
header .meta {{ color: var(--muted); margin: 0 0 1.5rem; }}
.stat-cards {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 0.75rem;
  margin-bottom: 1.5rem;
}}
.card {{
  background: var(--panel);
  border: 1px solid var(--border);
  border-left: 4px solid var(--muted);
  border-radius: 6px;
  padding: 0.75rem 1rem;
  cursor: pointer;
}}
.card.status-OVERLOADED, .card.status-ABOVE, .card.status-OK,
.card.status-UNDERLOADED, .card.status-WARNING, .card.status-NO_DATA {{
  border-left-color: var(--status-color);
}}
.card.level-S1, .card.level-S2, .card.level-S3,
.card.level-PROFESI, .card.level-OTHER {{
  border-left-color: var(--level-color);
}}
.card-count {{ font-size: 1.6rem; font-weight: 700; }}
.card-label {{ color: var(--muted); font-size: 0.85rem; }}
section {{
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 1rem 1.25rem;
  margin-bottom: 1.5rem;
  overflow-x: auto;
}}
section h2 {{ margin-top: 0; }}
input[type="search"] {{
  width: 100%;
  max-width: 320px;
  padding: 0.4rem 0.6rem;
  border: 1px solid var(--border);
  border-radius: 4px;
  font-size: 0.95rem;
  margin-bottom: 0.75rem;
}}
.filter-count {{ color: var(--muted); font-size: 0.85rem; margin-left: 0.5rem; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.9rem; }}
thead th {{
  position: sticky;
  top: 0;
  background: var(--panel);
  text-align: left;
  border-bottom: 2px solid var(--border);
  padding: 0.4rem 0.6rem;
  cursor: pointer;
  white-space: nowrap;
}}
tbody td {{ padding: 0.35rem 0.6rem; border-bottom: 1px solid var(--border); }}
tbody tr:nth-child(even) {{ background: rgba(0,0,0,0.02); }}
tbody tr.lecturer-row {{ cursor: pointer; }}
tbody tr[class*="status-"] td:first-child {{ border-left: 3px solid var(--status-color); }}
tbody tr[class*="level-"] td:first-child {{ border-left: 3px solid var(--level-color); }}
{_status_css()}
{_level_css()}
.badge {{
  display: inline-block;
  padding: 0.1rem 0.5rem;
  border-radius: 10px;
  font-size: 0.8rem;
  color: #fff;
  background: var(--status-color);
}}
.badge.level-S1, .badge.level-S2, .badge.level-S3,
.badge.level-PROFESI, .badge.level-OTHER {{
  background: var(--level-color);
}}
#warnings-list {{ margin: 0; padding-left: 1.25rem; }}
</style>
</head>
<body>
<div class="container">
<header>
  <h1>Teaching Load Dashboard</h1>
  <p class="meta">Semester {semester} &middot; generated {generated} &middot;
    bands: WARNING &lt; {warn:g}, UNDERLOADED {warn:g}-{ok_min:g},
    OK {ok_min:g}-{ok_high:g}, ABOVE {ok_high:g}-{max_sks:g},
    OVERLOADED &gt; {max_sks:g}</p>
</header>

<section class="stat-cards">
{_stat_cards(result)}
</section>

<section id="lecturers">
  <h2>Lecturers</h2>
  <input id="filter" type="search" placeholder="Filter by lecturer or status...">
  <span id="filter-count" class="filter-count"></span>
  <table id="lecturer-table">
    <thead><tr>
{lecturer_headers}
    </tr></thead>
    <tbody></tbody>
  </table>
</section>

<section id="levels">
  <h2>By program level</h2>
  <div class="stat-cards">
{_level_cards(result)}
  </div>
</section>

<section id="warnings">
  <h2>Warnings ({len(result["warnings"])})</h2>
  <ul id="warnings-list">
{_warnings_html(result["warnings"])}
  </ul>
</section>

<section id="classes">
  <h2>Per-class detail</h2>
  <input id="class-filter" type="search" placeholder="Filter classes (lecturer, kode, rumpun, level...)">
  <span id="class-filter-count" class="filter-count"></span>
  <table id="class-table">
    <thead><tr>
{class_headers}
    </tr></thead>
    <tbody></tbody>
  </table>
</section>
</div>

<script>
const LECTURERS = {lecturers_json};
const CLASSES = {classes_json};
const LECTURER_COLUMNS = {lecturer_cols_json};
const CLASS_COLUMNS = {class_cols_json};

const filterInput = document.getElementById("filter");
const classFilterInput = document.getElementById("class-filter");

function makeTable(opts) {{
  const {{ data, columns, tbody, filterInput, countEl, defaultKey, rowClass, onRowClick }} = opts;
  const state = {{ key: defaultKey, dir: -1 }};

  function matches(row, q) {{
    if (!q) return true;
    q = q.toLowerCase();
    return columns.some(k => String(row[k]).toLowerCase().includes(q));
  }}

  function render() {{
    const q = filterInput.value.trim();
    let rows = data.filter(r => matches(r, q));
    rows.sort((a, b) => {{
      const av = a[state.key], bv = b[state.key];
      let cmp;
      if (typeof av === "number" && typeof bv === "number") {{
        cmp = av - bv;
      }} else {{
        cmp = String(av).localeCompare(String(bv));
      }}
      return cmp * state.dir;
    }});
    tbody.textContent = "";
    for (const r of rows) {{
      const tr = document.createElement("tr");
      if (rowClass) tr.className = rowClass(r);
      if (onRowClick) tr.addEventListener("click", () => onRowClick(r));
      for (const key of columns) {{
        const td = document.createElement("td");
        if (key === "status" || key === "level") {{
          const span = document.createElement("span");
          span.className = "badge " + key + "-" + r[key];
          span.textContent = r[key];
          td.appendChild(span);
        }} else {{
          td.textContent = r[key];
        }}
        tr.appendChild(td);
      }}
      tbody.appendChild(tr);
    }}
    if (countEl) countEl.textContent = rows.length + " / " + data.length;
  }}

  return {{ state, render }};
}}

const lecturerTable = makeTable({{
  data: LECTURERS,
  columns: LECTURER_COLUMNS,
  tbody: document.querySelector("#lecturer-table tbody"),
  filterInput: filterInput,
  countEl: document.getElementById("filter-count"),
  defaultKey: "total_sks",
  rowClass: r => "status-" + r.status + " lecturer-row",
  onRowClick: r => {{ classFilterInput.value = r.dosen; classTable.render(); }},
}});

const classTable = makeTable({{
  data: CLASSES,
  columns: CLASS_COLUMNS,
  tbody: document.querySelector("#class-table tbody"),
  filterInput: classFilterInput,
  countEl: document.getElementById("class-filter-count"),
  defaultKey: "dosen",
  rowClass: r => "level-" + r.level,
}});

function wireSort(tableId, table) {{
  document.querySelectorAll("#" + tableId + " th[data-key]").forEach(th => {{
    th.addEventListener("click", () => {{
      const key = th.dataset.key;
      table.state.dir = (table.state.key === key) ? -table.state.dir : 1;
      table.state.key = key;
      table.render();
    }});
  }});
}}

wireSort("lecturer-table", lecturerTable);
wireSort("class-table", classTable);
filterInput.addEventListener("input", () => lecturerTable.render());
classFilterInput.addEventListener("input", () => classTable.render());

lecturerTable.render();
classTable.render();
</script>
</body>
</html>
"""


def write_dashboard(result: dict, outdir=".") -> Path:
    """Write the dashboard HTML to ``outdir/load_dashboard.html``."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / DASHBOARD_FILENAME
    path.write_text(render_dashboard(result), encoding="utf-8")
    return path
