import importlib

import ehr_rwe_eln


def test_package_version():
    assert ehr_rwe_eln.__version__ == "0.1.0"


def test_modules_import():
    for name in ("cohort", "eln", "tte", "dq"):
        importlib.import_module(f"ehr_rwe_eln.{name}")
