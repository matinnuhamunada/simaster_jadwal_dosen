import re

from simaster.ics import (
    _escape_text,
    _event_datetimes,
    _fold_line,
    _parse_jam,
    build_events,
    render_ics,
    write_ics,
)

META = {"semester": "20261", "dosen": "Matin Nuhamunada, S.Si., M.Sc.", "dosenId": "16764"}

COURSE = {
    "no": "1",
    "rumpun": "[PRODI] S1 BIOLOGI",
    "kode": "BISB262101",
    "mata_kuliah": "Bahasa Inggris untuk Biologi",
    "kelas": "IUP",
    "sks": "2.00",
    "jml_mhs": "",
    "jadwal": [
        {
            "hari": "Jumat",
            "tanggal": "2026-08-21",
            "jam": "07:15-08:55",
            "ruang": "Ruang 1",
            "dosen": "Matin Nuhamunada, S.Si., M.Sc.",
        }
    ],
}


class TestParseJam:
    def test_valid(self):
        assert _parse_jam("07:15-08:55") == ("07:15", "08:55")

    def test_malformed(self):
        assert _parse_jam("not a time") is None
        assert _parse_jam("") is None
        assert _parse_jam(None) is None


class TestEventDatetimes:
    def test_converts_wib_to_utc(self):
        start, end = _event_datetimes("2026-08-21", "07:15-08:55")
        assert start.isoformat() == "2026-08-21T00:15:00+00:00"
        assert end.isoformat() == "2026-08-21T01:55:00+00:00"

    def test_missing_tanggal(self):
        assert _event_datetimes("", "07:15-08:55") is None

    def test_missing_jam(self):
        assert _event_datetimes("2026-08-21", "") is None

    def test_malformed_tanggal(self):
        assert _event_datetimes("21-08-2026", "07:15-08:55") is None


class TestEscapeText:
    def test_escapes_special_chars(self):
        assert _escape_text("A, B; C\\D\nE") == "A\\, B\\; C\\\\D\\nE"

    def test_none_safe(self):
        assert _escape_text(None) == ""


class TestFoldLine:
    def test_short_line_untouched(self):
        line = "SUMMARY:short"
        assert _fold_line(line) == line

    def test_long_line_is_folded(self):
        line = "DESCRIPTION:" + "x" * 100
        folded = _fold_line(line)
        assert "\r\n " in folded
        # Unfolding (CRLF + single space removed) reconstructs the original.
        assert re.sub(r"\r\n ", "", folded) == line
        for part in folded.split("\r\n"):
            assert len(part.encode("utf-8")) <= 75

    def test_does_not_split_multibyte_chars(self):
        line = "SUMMARY:" + "é" * 60  # 2 bytes each in utf-8
        folded = _fold_line(line)
        assert re.sub(r"\r\n ", "", folded) == line
        for part in folded.split("\r\n"):
            part.encode("utf-8").decode("utf-8")  # raises if a codepoint was split


class TestBuildEvents:
    def test_one_event_per_own_session(self):
        lines, n_skipped = build_events(META, [COURSE])
        assert n_skipped == 0
        assert sum(1 for l in lines if l.startswith("BEGIN:VEVENT")) == 1
        joined = "\n".join(lines)
        assert "SUMMARY:BISB262101 Bahasa Inggris untuk Biologi (IUP)" in joined
        assert "LOCATION:Ruang 1" in joined
        assert "DTSTART:20260821T001500Z" in joined
        assert "DTEND:20260821T015500Z" in joined

    def test_excludes_co_teacher_sessions(self):
        course = {
            **COURSE,
            "jadwal": [
                {**COURSE["jadwal"][0], "dosen": "Someone Else"},
            ],
        }
        lines, n_skipped = build_events(META, [course])
        assert lines == []
        assert n_skipped == 0

    def test_skips_unscheduled_entries(self):
        course = {**COURSE, "jadwal": [{**COURSE["jadwal"][0], "tanggal": "", "jam": ""}]}
        lines, n_skipped = build_events(META, [course])
        assert lines == []
        assert n_skipped == 1

    def test_stable_uid_across_calls(self):
        lines1, _ = build_events(META, [COURSE])
        lines2, _ = build_events(META, [COURSE])
        uid1 = next(l for l in lines1 if l.startswith("UID:"))
        uid2 = next(l for l in lines2 if l.startswith("UID:"))
        assert uid1 == uid2


class TestRenderIcs:
    def test_basic_structure(self):
        text, n_events, n_skipped = render_ics(META, [COURSE])
        assert text.startswith("BEGIN:VCALENDAR\r\n")
        assert text.rstrip("\r\n").endswith("END:VCALENDAR")
        assert n_events == 1
        assert n_skipped == 0
        assert "VERSION:2.0" in text

    def test_escapes_calname(self):
        meta = {**META, "dosen": 'A & B, "Quote"'}
        text, _, _ = render_ics(meta, [COURSE])
        assert 'X-WR-CALNAME:A & B\\, "Quote" 20261' in text


class TestWriteIcs:
    def test_writes_expected_filename(self, tmp_path):
        path, n_events, n_skipped = write_ics(META, [COURSE], tmp_path)
        assert path == tmp_path / "jadwal_matin_nuhamunada_s_si_m_sc_20261.ics"
        assert path.exists()
        assert n_events == 1
        assert n_skipped == 0
