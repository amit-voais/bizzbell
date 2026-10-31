#!/usr/bin/env python3
"""Bizzbell CLI: python3 scripts/bb.py <command> [options]. Run with --help for the command list.

Subcommands are discovered from scripts/bizzbell/commands/*.py (see docs/extending.md)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if sys.version_info < (3, 9):
    sys.exit("bizzbell needs Python 3.9 or newer")

from bizzbell.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
