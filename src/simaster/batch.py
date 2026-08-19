"""Batch inputs: read lecturer names from a plain text file."""

from __future__ import annotations

from pathlib import Path


def read_lecturers(path: str | Path) -> list[str]:
    """Read one lecturer name per line.

    Blank lines and lines starting with ``#`` are ignored. Full names including
    academic titles are preserved exactly as written.
    """
    p = Path(path)
    names: list[str] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        names.append(line)
    return names
