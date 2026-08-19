import pytest

from simaster.batch import read_lecturers


def test_reads_names_ignoring_blanks_and_comments(tmp_path):
    f = tmp_path / "names.txt"
    f.write_text(
        "Luthfi Nurhidayat, S.Si., M.Sc.\n"
        "\n"
        "# a comment\n"
        "Matin Nuhamunada, S.Si., M.Sc.\n"
        "   \n"
        "Dr. Eko Agus Suyono\n",
        encoding="utf-8",
    )
    assert read_lecturers(f) == [
        "Luthfi Nurhidayat, S.Si., M.Sc.",
        "Matin Nuhamunada, S.Si., M.Sc.",
        "Dr. Eko Agus Suyono",
    ]


def test_preserves_titles_exactly(tmp_path):
    f = tmp_path / "names.txt"
    f.write_text("  Luthfi Nurhidayat, S.Si., M.Sc.  \n", encoding="utf-8")
    assert read_lecturers(f) == ["Luthfi Nurhidayat, S.Si., M.Sc."]


def test_empty_file(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("", encoding="utf-8")
    assert read_lecturers(f) == []


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_lecturers(tmp_path / "nope.txt")