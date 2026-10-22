"""Fail loudly and clearly when the Python running the tests does not have the project's dependencies.

An ImportError or a missing QR code in a test run almost always means `pip install -r requirements.txt`
was not run in THIS interpreter. That is an environment problem, not a code bug.
"""
import importlib
import sys

import pytest

REQUIRED = [("httpx", "httpx"), ("cryptography", "cryptography"), ("segno", "segno")]


@pytest.mark.parametrize("module,package", REQUIRED)
def test_required_package_is_installed(module, package):
    try:
        importlib.import_module(module)
    except ImportError:
        pytest.fail(
            f"The package '{package}' is not installed in this Python ({sys.executable}, {sys.version.split()[0]}). "
            f"Install the project requirements into this same interpreter: {sys.executable} -m pip install -r requirements.txt",
            pytrace=False,
        )
