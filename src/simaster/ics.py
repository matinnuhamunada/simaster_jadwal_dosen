"""Export a lecturer's schedule as an RFC 5545 .ics calendar file.

Like ``dashboard.py``, this hand-builds the output with plain string
formatting (no new dependency). Asia/Jakarta (WIB) has no DST, so event
times are converted to UTC with a fixed ``-7h`` offset and emitted with a
``Z`` suffix, which sidesteps the need for a ``VTIMEZONE`` block.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .load import _matches
from .parse import slugify

WIB_OFFSET = timedelta(hours=7)
JAM_RE = re.compile(r"^(\d{2}:\d{2})-(\d{2}:\d{2})$")
_ESCAPE_RE = re.compile(r"([\\;,])")


def _parse_jam(jam: str) -> tuple[str, str] | None:
    """``'07:15-08:55'`` -> ``('07:15', '08:55')``, or ``None`` if malformed."""
    m = JAM_RE.match((jam or "").strip())
    return (m.group(1), m.group(2)) if m else None


def _event_datetimes(tanggal: str, jam: str) -> tuple[datetime, datetime] | None:
    """WIB ``tanggal``/``jam`` -> ``(start, end)`` UTC datetimes, or ``None``."""
    times = _parse_jam(jam)
    if not tanggal or not times:
        return None
    start_s, end_s = times
    try:
        date = datetime.strptime(tanggal, "%Y-%m-%d")
        start = datetime.strptime(start_s, "%H:%M")
        end = datetime.strptime(end_s, "%H:%M")
    except ValueError:
        return None
    start_dt = date.replace(hour=start.hour, minute=start.minute) - WIB_OFFSET
    end_dt = date.replace(hour=end.hour, minute=end.minute) - WIB_OFFSET
    return start_dt.replace(tzinfo=timezone.utc), end_dt.replace(tzinfo=timezone.utc)


def _escape_text(s: str) -> str:
    """RFC 5545 §3.3.11 text escaping: ``\\``, ``;``, ``,``, then newlines."""
    return _ESCAPE_RE.sub(r"\\\1", s or "").replace("\n", "\\n")


def _fold_line(line: str) -> str:
    """Fold a content line at 75 octets with a ``\\r\\n `` continuation.

    Splits on characters, never mid-codepoint, since RFC 5545 §3.1 counts
    octets and a naive byte-slice could sever a multi-byte UTF-8 character.
    """
    limit = 75
    parts: list[str] = []
    cur = ""
    cur_len = 0
    for ch in line:
        ch_len = len(ch.encode("utf-8"))
        effective_limit = limit if not parts else limit - 1  # continuation lines start with a space
        if cur_len + ch_len > effective_limit:
            parts.append(cur)
            cur, cur_len = ch, ch_len
        else:
            cur += ch
            cur_len += ch_len
    parts.append(cur)
    return "\r\n ".join(parts)


def _dt_stamp(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def build_events(meta: dict, courses: list[dict]) -> tuple[list[str], int]:
    """Build folded ``VEVENT`` blocks for a lecturer's own sessions.

    Filters ``jadwal`` entries to the lecturer's own sessions via
    ``load._matches`` so this works whether pointed at raw (co-teacher
    entries mixed in) or clean (already own-only) schedule data. Returns
    ``(lines, n_skipped)`` where ``n_skipped`` counts entries with missing or
    unparseable date/time.
    """
    dosen = meta.get("dosen") or ""
    now = _dt_stamp(datetime.now(timezone.utc))
    lines: list[str] = []
    n_skipped = 0
    for course in courses:
        kode = course.get("kode", "")
        mata_kuliah = course.get("mata_kuliah", "")
        kelas = course.get("kelas", "")
        rumpun = course.get("rumpun", "")
        sks = course.get("sks", "")
        for entry in course.get("jadwal") or []:
            if not _matches(entry.get("dosen", ""), dosen):
                continue
            dts = _event_datetimes(entry.get("tanggal", ""), entry.get("jam", ""))
            if dts is None:
                n_skipped += 1
                continue
            start, end = dts
            uid = (
                f"{slugify(dosen)}-{slugify(kode)}-{slugify(kelas)}-"
                f"{entry['tanggal']}-{start.strftime('%H%M')}@simaster-jadwal-dosen"
            )
            description = _escape_text(
                f"{rumpun}\nSKS: {sks}\nDosen: {dosen}"
            )
            lines.append("BEGIN:VEVENT")
            lines.append(f"UID:{uid}")
            lines.append(f"DTSTAMP:{now}")
            lines.append(f"DTSTART:{_dt_stamp(start)}")
            lines.append(f"DTEND:{_dt_stamp(end)}")
            lines.append(f"SUMMARY:{_escape_text(f'{kode} {mata_kuliah} ({kelas})')}")
            lines.append(f"LOCATION:{_escape_text(entry.get('ruang', ''))}")
            lines.append(f"DESCRIPTION:{description}")
            lines.append("END:VEVENT")
    return [_fold_line(l) for l in lines], n_skipped


def render_ics(meta: dict, courses: list[dict]) -> tuple[str, int, int]:
    """Build a full ``.ics`` calendar text for one lecturer.

    Returns ``(text, n_events, n_skipped)``.
    """
    dosen = meta.get("dosen") or ""
    semester = meta.get("semester") or ""
    events, n_skipped = build_events(meta, courses)
    n_events = sum(1 for l in events if l.startswith("BEGIN:VEVENT"))
    header = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//simaster-jadwal-dosen//ics//ID",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        _fold_line(f"X-WR-CALNAME:{_escape_text(f'{dosen} {semester}'.strip())}"),
    ]
    footer = ["END:VCALENDAR"]
    text = "\r\n".join(header + events + footer) + "\r\n"
    return text, n_events, n_skipped


def write_ics(meta: dict, courses: list[dict], outdir: str | Path = ".") -> tuple[Path, int, int]:
    """Write ``jadwal_<slug>_<semester>.ics``; return ``(path, n_events, n_skipped)``."""
    text, n_events, n_skipped = render_ics(meta, courses)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    stem = f"jadwal_{slugify(meta.get('dosen') or '')}_{meta.get('semester') or ''}"
    path = outdir / f"{stem}.ics"
    path.write_text(text, encoding="utf-8")
    return path, n_events, n_skipped
