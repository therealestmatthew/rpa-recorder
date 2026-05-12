"""Smoke test: the package imports and exposes its version."""

import rpa_recorder


def test_package_imports() -> None:
    assert rpa_recorder.__name__ == "rpa_recorder"
    assert rpa_recorder.__version__ == "0.2.0"
