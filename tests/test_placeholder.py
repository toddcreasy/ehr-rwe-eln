import importlib
import tomllib
from pathlib import Path

import ehr_rwe_eln


def test_package_version_matches_pyproject():
    # A release bumps pyproject.toml; this catches __init__.py left behind.
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert ehr_rwe_eln.__version__ == pyproject["project"]["version"]


def test_modules_import():
    for name in ("cohort", "eln", "tte", "dq"):
        importlib.import_module(f"ehr_rwe_eln.{name}")
