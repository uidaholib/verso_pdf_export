"""Tests for script.py refactoring — verifying no import side effects and CLI parsing."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_script_import_no_side_effects(tmp_path):
    """Importing script should not create directories or configure logging."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import logging; "
                "baseline_handlers = len(logging.getLogger().handlers); "
                "import script; "
                "import os; "
                "dirs = sorted(os.listdir('.')); "
                "new_handlers = len(logging.getLogger().handlers) - baseline_handlers; "
                "print(f'{dirs}|{new_handlers}')"
            ),
        ],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
    )
    assert result.returncode == 0, f"Import failed: {result.stderr}"
    dir_listing, handler_count = result.stdout.strip().split("|")
    assert "C" not in dir_listing, "Importing script should not create C/ directory"
    assert int(handler_count) == 0, (
        "Importing script should not configure logging handlers"
    )


def test_script_parse_args_defaults():
    """parse_args([]) returns correct defaults."""
    import script

    args = script.parse_args([])
    assert args.csv == "assetsWithPDFs_just_ETDs.csv"
    assert args.debug is False
    assert args.subset_size == 5


def test_script_parse_args_all_flags():
    """parse_args with all flags returns correct overrides."""
    import script

    args = script.parse_args(["--csv", "x.csv", "--debug", "--subset-size", "3"])
    assert args.csv == "x.csv"
    assert args.debug is True
    assert args.subset_size == 3


def test_script_parse_args_debug_only():
    """parse_args with only --debug returns debug=True, others at defaults."""
    import script

    args = script.parse_args(["--debug"])
    assert args.debug is True
    assert args.csv == "assetsWithPDFs_just_ETDs.csv"
    assert args.subset_size == 5
