import pytest

from simaster.cli import _dedupe, main, parse_args, run_all


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


class FakeScraper:
    def __init__(self, **kwargs):
        self.endpoint = kwargs.get("endpoint") or "http://fake:9223"
        self.results = kwargs.pop("results", [])
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def scrape_many(self, names):
        self.names = names
        return self.results


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