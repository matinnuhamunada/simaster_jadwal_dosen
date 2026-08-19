#!/usr/bin/env python3
"""Compatibility shim: reproduce the original hardcoded single-lecturer run.

Prefer the new CLI instead:

  conda run -n simaster simaster --lecturer "Matin Nuhamunada"
  conda run -n simaster simaster --names target.md
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from simaster.cli import main

if __name__ == "__main__":
    sys.exit(main(["--lecturer", "Matin Nuhamunada"]))