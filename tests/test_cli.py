import json

import pytest

from simaster.cli import _dedupe, main, parse_args, run_all
from simaster.output import write_outputs
from simaster.scraper import build_meta


class TestParseArgs:
    def test_defaults(self):
        args = parse_args(["--lecturer", "Matin Nuhamunada"])
        assert args.semester == "20261"
        assert args.outdir == "."
        assert args.endpoint is None
        assert args.max_login_min == 30
        assert args.verbose is False
        assert args.lecturer == ["Matin Nuhamunada"]
        assert args.names == []
        assert args.from_scratch is False

    def test_repeatable_lecturer(self):
        args = parse_args(["--lecturer", "A", "--lecturer", "B"])
        assert args.lecturer == ["A", "B"]

    def test_names_files(self):
        args = parse_args(["--names", "one.txt", "--names", "two.txt"])
        assert args.names == ["one.txt", "two.txt"]

    def test_options(self):
        args = parse_args(
            [
                "--lecturer",
                "A",
                "--semester",
                "20251",
                "--outdir",
                "data",
                "--endpoint",
                "http://10.0.0.1:9223",
                "--max-login-min",
                "5",
                "--verbose",
            ]
        )
        assert args.semester == "20251"
        assert args.outdir == "data"
        assert args.endpoint == "http://10.0.0.1:9223"
        assert args.max_login_min == 5
        assert args.verbose is True

    def test_from_scratch_flag(self):
        args = parse_args(["--lecturer", "A", "--from-scratch"])
        assert args.from_scratch is True

    def test_version(self, capsys):
        with pytest.raises(SystemExit) as e:
            parse_args(["--version"])
        assert e.value.code == 0
        assert "simaster" in capsys.readouterr().out


class TestMain:
    def test_no_input_returns_2(self, capsys):
        assert main([]) == 2
        assert "at least one" in capsys.readouterr().err

    def test_dedupe_preserves_order(self):
        assert _dedupe(["a", "b", "a", "c"]) == ["a", "b", "c"]


class TestAnalyzeArgs:
    def test_analyze_dispatch(self):
        args = parse_args(["analyze"])
        assert args.analyze is True
        assert args.dir == "data"
        assert args.semester == "20261"
        assert args.min_sks == 8.0
        assert args.max_sks == 16.0
        assert args.warn_sks == 6.0
        assert args.names is None
        assert args.outdir == "."

    def test_analyze_options(self):
        args = parse_args(
            ["analyze", "--dir", "results", "--semester", "20251", "--min", "9", "--max", "14", "--warn", "5"]
        )
        assert args.dir == "results"
        assert args.semester == "20251"
        assert args.min_sks == 9.0
        assert args.max_sks == 14.0
        assert args.warn_sks == 5.0

    def test_scrape_not_analyze(self):
        args = parse_args(["--lecturer", "A"])
        assert args.analyze is False


class TestDashboardArgs:
    def test_dashboard_dispatch(self):
        args = parse_args(["dashboard"])
        assert args.dashboard is True
        assert args.dir == "data"
        assert args.semester == "20261"
        assert args.min_sks == 8.0
        assert args.max_sks == 16.0
        assert args.warn_sks == 6.0
        assert args.names is None
        assert args.outdir == "."

    def test_dashboard_options(self):
        args = parse_args(
            [
                "dashboard",
                "--dir",
                "results",
                "--semester",
                "20251",
                "--min",
                "9",
                "--max",
                "14",
                "--warn",
                "5",
                "--outdir",
                "out",
            ]
        )
        assert args.dir == "results"
        assert args.semester == "20251"
        assert args.min_sks == 9.0
        assert args.max_sks == 14.0
        assert args.warn_sks == 5.0
        assert args.outdir == "out"

    def test_scrape_not_dashboard(self):
        args = parse_args(["--lecturer", "A"])
        assert getattr(args, "dashboard", False) is False


class TestCleanArgs:
    def test_clean_dispatch(self):
        args = parse_args(["clean"])
        assert args.clean is True
        assert args.dir == "data"
        assert args.semester == "20261"
        assert args.names is None
        assert args.outdir == "data/clean"

    def test_clean_options(self):
        args = parse_args(
            ["clean", "--dir", "data", "--semester", "20251", "--names", "target.md", "--outdir", "x"]
        )
        assert args.dir == "data"
        assert args.semester == "20251"
        assert args.names == "target.md"
        assert args.outdir == "x"

    def test_clean_not_scrape(self):
        args = parse_args(["clean"])
        assert getattr(args, "analyze", False) is False


class TestIcsArgs:
    def test_ics_dispatch(self):
        args = parse_args(["ics", "--lecturer", "A"])
        assert args.ics is True
        assert args.dir == "data"
        assert args.semester == "20261"
        assert args.outdir == "."
        assert args.lecturer == ["A"]
        assert args.names == []

    def test_ics_options(self):
        args = parse_args(
            [
                "ics",
                "--lecturer",
                "A",
                "--names",
                "target.md",
                "--dir",
                "data/clean",
                "--semester",
                "20251",
                "--outdir",
                "out",
            ]
        )
        assert args.dir == "data/clean"
        assert args.semester == "20251"
        assert args.outdir == "out"
        assert args.names == ["target.md"]

    def test_scrape_not_ics(self):
        args = parse_args(["--lecturer", "A"])
        assert getattr(args, "ics", False) is False


class TestMainAnalyze:
    def test_runs_analyze_offline(self, tmp_path, capsys):
        course = {
            "kode": "K1",
            "mata_kuliah": "Genetika",
            "kelas": "A",
            "sks": "2.00",
            "jadwal": [{"dosen": "Matin Nuhamunada, S.Si., M.Sc."}] * 14,
        }
        (tmp_path / "jadwal_matin_nuhamunada_s_si_m_sc_20261.json").write_text(
            json.dumps(
                {
                    "meta": {
                        "semester": "20261",
                        "dosen": "Matin Nuhamunada, S.Si., M.Sc.",
                        "dosenId": "16764",
                    },
                    "courses": [course],
                }
            ),
            encoding="utf-8",
        )
        out = tmp_path / "out"
        rc = main(["analyze", "--dir", str(tmp_path), "--semester", "20261", "--outdir", str(out)])
        assert rc == 0
        assert (out / "load_summary.csv").exists()
        assert "wrote" in capsys.readouterr().out


class TestMainDashboard:
    def test_runs_dashboard_offline(self, tmp_path, capsys):
        course = {
            "kode": "K1",
            "mata_kuliah": "Genetika",
            "kelas": "A",
            "sks": "2.00",
            "jadwal": [{"dosen": "Matin Nuhamunada, S.Si., M.Sc."}] * 14,
        }
        (tmp_path / "jadwal_matin_nuhamunada_s_si_m_sc_20261.json").write_text(
            json.dumps(
                {
                    "meta": {
                        "semester": "20261",
                        "dosen": "Matin Nuhamunada, S.Si., M.Sc.",
                        "dosenId": "16764",
                    },
                    "courses": [course],
                }
            ),
            encoding="utf-8",
        )
        out = tmp_path / "out"
        rc = main(["dashboard", "--dir", str(tmp_path), "--semester", "20261", "--outdir", str(out)])
        assert rc == 0
        html_path = out / "load_dashboard.html"
        assert html_path.exists()
        content = html_path.read_text(encoding="utf-8")
        assert "<!doctype html>" in content.lower()
        assert "Matin Nuhamunada" in content
        assert "wrote" in capsys.readouterr().out


class TestMainIcs:
    def test_fuzzy_matches_name_with_missing_middle_title(self, tmp_path, capsys):
        (tmp_path / "jadwal_a_20261.json").write_text(
            json.dumps(
                {
                    "meta": {"semester": "20261", "dosen": "Budi Santoso, S.Si., M.Sc."},
                    "courses": [],
                }
            ),
            encoding="utf-8",
        )
        out = tmp_path / "out"
        rc = main(
            [
                "ics",
                "--lecturer",
                "Budi Santoso, M.Sc.",
                "--dir",
                str(tmp_path),
                "--semester",
                "20261",
                "--outdir",
                str(out),
            ]
        )
        assert rc == 0
        assert (out / "jadwal_budi_santoso_s_si_m_sc_20261.ics").exists()
        assert "matched 'Budi Santoso, S.Si., M.Sc.'" in capsys.readouterr().out

    def test_unrelated_name_stays_a_failure_with_hint(self, tmp_path, capsys):
        (tmp_path / "jadwal_a_20261.json").write_text(
            json.dumps(
                {
                    "meta": {"semester": "20261", "dosen": "Budi Santoso, S.Si., M.Sc."},
                    "courses": [],
                }
            ),
            encoding="utf-8",
        )
        rc = main(
            ["ics", "--lecturer", "Completely Different Person", "--dir", str(tmp_path)]
        )
        assert rc == 1
        err = capsys.readouterr().err
        assert "ERROR" in err
        assert "closest on file" in err

    def test_runs_ics_offline(self, tmp_path, capsys):
        course = {
            "kode": "K1",
            "mata_kuliah": "Genetika",
            "kelas": "A",
            "sks": "2.00",
            "rumpun": "[PRODI] S1 BIOLOGI",
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
        (tmp_path / "jadwal_matin_nuhamunada_s_si_m_sc_20261.json").write_text(
            json.dumps(
                {
                    "meta": {
                        "semester": "20261",
                        "dosen": "Matin Nuhamunada, S.Si., M.Sc.",
                        "dosenId": "16764",
                    },
                    "courses": [course],
                }
            ),
            encoding="utf-8",
        )
        out = tmp_path / "out"
        rc = main(
            [
                "ics",
                "--lecturer",
                "Matin Nuhamunada, S.Si., M.Sc.",
                "--dir",
                str(tmp_path),
                "--semester",
                "20261",
                "--outdir",
                str(out),
            ]
        )
        assert rc == 0
        ics_path = out / "jadwal_matin_nuhamunada_s_si_m_sc_20261.ics"
        assert ics_path.exists()
        content = ics_path.read_text(encoding="utf-8")
        assert "BEGIN:VCALENDAR" in content
        assert "SUMMARY:K1 Genetika (A)" in content
        assert "1 events" in capsys.readouterr().out

    def test_missing_schedule_file_is_a_failure(self, tmp_path, capsys):
        (tmp_path / "jadwal_someone_else_20261.json").write_text(
            json.dumps(
                {
                    "meta": {"semester": "20261", "dosen": "Someone Else, M.Sc."},
                    "courses": [],
                }
            ),
            encoding="utf-8",
        )
        rc = main(
            ["ics", "--lecturer", "Nobody", "--dir", str(tmp_path), "--outdir", str(tmp_path)]
        )
        assert rc == 1
        assert "ERROR" in capsys.readouterr().err

    def test_no_files_found_returns_2(self, tmp_path, capsys):
        rc = main(["ics", "--dir", str(tmp_path), "--outdir", str(tmp_path)])
        assert rc == 2
        assert "no jadwal_" in capsys.readouterr().err

    def test_no_filter_exports_everyone_in_dir(self, tmp_path, capsys):
        for slug, dosen in [
            ("a", "Lecturer A, M.Sc."),
            ("b", "Lecturer B, Ph.D."),
        ]:
            (tmp_path / f"jadwal_{slug}_20261.json").write_text(
                json.dumps(
                    {"meta": {"semester": "20261", "dosen": dosen}, "courses": []}
                ),
                encoding="utf-8",
            )
        out = tmp_path / "out"
        rc = main(["ics", "--dir", str(tmp_path), "--semester", "20261", "--outdir", str(out)])
        assert rc == 0
        assert (out / "jadwal_lecturer_a_m_sc_20261.ics").exists()
        assert (out / "jadwal_lecturer_b_ph_d_20261.ics").exists()
        assert capsys.readouterr().out.count("[ics] wrote") == 2


class FakeScraper:
    def __init__(self, **kwargs):
        self.endpoint = kwargs.get("endpoint") or "http://fake:9223"
        self.results = list(kwargs.pop("results", []))
        self.kwargs = kwargs
        self.names: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def scrape(self, name):
        self.names.append(name)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def ok_result():
    return {
        "lecturer": "Matin Nuhamunada",
        "canonical": "Matin Nuhamunada, S.Si., M.Sc.",
        "dosenId": "16764",
        "courses": [
            {
                "kode": "BISB262101",
                "mata_kuliah": "Bahasa Inggris untuk Biologi",
                "kelas": "IUP",
                "sks": "2.00",
                "jml_mhs": "",
                "rumpun": "[PRODI] S1 BIOLOGI",
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
        ],
        "total": 1,
    }


def test_run_all_writes_outputs(tmp_path, ok_result):
    written, failures = run_all(
        ["Matin Nuhamunada"],
        semester="20261",
        outdir=str(tmp_path),
        endpoint="http://fake:9223",
        max_login_min=30,
        verbose=False,
        scraper_factory=lambda **kw: FakeScraper(results=[ok_result], **kw),
    )
    assert failures == 0
    assert len(written) == 1
    (tmp_path / "jadwal_matin_nuhamunada_20261.json").exists()
    (tmp_path / "jadwal_matin_nuhamunada_20261.csv").exists()


def test_run_all_counts_failures(tmp_path, ok_result):
    failed = {"lecturer": "Nobody", "error": "could not resolve dosenId", "courses": []}
    written, failures = run_all(
        ["Matin", "Nobody"],
        semester="20261",
        outdir=str(tmp_path),
        endpoint=None,
        max_login_min=30,
        verbose=False,
        scraper_factory=lambda **kw: FakeScraper(results=[ok_result, failed], **kw),
    )
    assert failures == 1
    assert len(written) == 1


def test_run_all_no_courses_counts_failure(tmp_path):
    empty = {"lecturer": "Matin", "canonical": "Matin", "dosenId": "1", "courses": [], "total": 0}
    written, failures = run_all(
        ["Matin"],
        semester="20261",
        outdir=str(tmp_path),
        endpoint=None,
        max_login_min=30,
        verbose=False,
        scraper_factory=lambda **kw: FakeScraper(results=[empty], **kw),
    )
    assert failures == 1
    assert written == []


class TestRunAllResume:
    def test_skips_lecturer_with_verified_output(self, tmp_path, ok_result, capsys):
        write_outputs(
            "Matin Nuhamunada",
            "20261",
            build_meta(ok_result, "20261"),
            ok_result["courses"],
            tmp_path,
        )
        scraper = FakeScraper(results=[])
        written, failures = run_all(
            ["Matin Nuhamunada"],
            semester="20261",
            outdir=str(tmp_path),
            endpoint=None,
            max_login_min=30,
            verbose=False,
            scraper_factory=lambda **kw: scraper,
        )
        assert failures == 0
        assert written == []
        assert scraper.names == []  # never scraped: skipped as already-verified
        assert "skip" in capsys.readouterr().out

    def test_rescrapes_missing_and_leaves_verified_alone(self, tmp_path, ok_result):
        write_outputs(
            "Matin Nuhamunada",
            "20261",
            build_meta(ok_result, "20261"),
            ok_result["courses"],
            tmp_path,
        )
        second = {**ok_result, "lecturer": "Second Person", "canonical": "Second Person"}
        scraper = FakeScraper(results=[second])
        written, failures = run_all(
            ["Matin Nuhamunada", "Second Person"],
            semester="20261",
            outdir=str(tmp_path),
            endpoint=None,
            max_login_min=30,
            verbose=False,
            scraper_factory=lambda **kw: scraper,
        )
        assert failures == 0
        assert len(written) == 1
        assert scraper.names == ["Second Person"]

    def test_from_scratch_rescrapes_everything(self, tmp_path, ok_result):
        write_outputs(
            "Matin Nuhamunada",
            "20261",
            build_meta(ok_result, "20261"),
            ok_result["courses"],
            tmp_path,
        )
        scraper = FakeScraper(results=[ok_result])
        written, failures = run_all(
            ["Matin Nuhamunada"],
            semester="20261",
            outdir=str(tmp_path),
            endpoint=None,
            max_login_min=30,
            verbose=False,
            from_scratch=True,
            scraper_factory=lambda **kw: scraper,
        )
        assert failures == 0
        assert len(written) == 1
        assert scraper.names == ["Matin Nuhamunada"]

    def test_corrupt_output_is_rescraped(self, tmp_path, ok_result):
        json_path, csv_path = write_outputs(
            "Matin Nuhamunada",
            "20261",
            build_meta(ok_result, "20261"),
            ok_result["courses"],
            tmp_path,
        )
        # Truncate to simulate a run cut off mid-write.
        json_path.write_text('{"meta": {"semester": "20261"', encoding="utf-8")
        scraper = FakeScraper(results=[ok_result])
        written, failures = run_all(
            ["Matin Nuhamunada"],
            semester="20261",
            outdir=str(tmp_path),
            endpoint=None,
            max_login_min=30,
            verbose=False,
            scraper_factory=lambda **kw: scraper,
        )
        assert failures == 0
        assert scraper.names == ["Matin Nuhamunada"]

    def test_fatal_error_stops_batch_but_keeps_progress(self, tmp_path, ok_result):
        second = {**ok_result, "lecturer": "Second Person", "canonical": "Second Person"}
        scraper = FakeScraper(results=[ok_result, ConnectionError("net down"), second])
        written, failures = run_all(
            ["Matin Nuhamunada", "Broken Person", "Second Person"],
            semester="20261",
            outdir=str(tmp_path),
            endpoint=None,
            max_login_min=30,
            verbose=False,
            scraper_factory=lambda **kw: scraper,
        )
        assert failures == 1
        assert len(written) == 1
        # third lecturer never attempted: the loop stopped at the fatal error
        assert scraper.names == ["Matin Nuhamunada", "Broken Person"]
        assert (tmp_path / "jadwal_matin_nuhamunada_20261.json").exists()