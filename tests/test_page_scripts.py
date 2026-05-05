"""Tests for the page_scripts loader and its packaged JS tree."""

from importlib.resources import files

import pytest

from rpa_recorder.page_scripts import bundle, load


class TestLoad:
    def test_returns_inject_script_contents(self) -> None:
        script = load("recorder/inject")
        assert isinstance(script, str)
        assert "(() =>" in script
        assert "window.__rpaInjected" in script

    def test_returns_shared_text_utils(self) -> None:
        script = load("shared/text_utils")
        assert "window.__rpa.shared.text" in script
        assert "function trim" in script

    def test_returns_shared_selectors(self) -> None:
        script = load("shared/selectors")
        assert "window.__rpa.shared.selectors" in script
        assert "function uniqueCss" in script

    def test_unknown_script_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load("recorder/missing")


class TestBundle:
    def test_concatenates_in_order(self) -> None:
        b = bundle("shared/text_utils", "recorder/inject")
        text_idx = b.index("window.__rpaSharedTextLoaded")
        inject_idx = b.index("window.__rpaInjected")
        assert text_idx < inject_idx

    def test_separator_is_newline_semicolon(self) -> None:
        b = bundle("shared/text_utils", "shared/selectors")
        assert "\n;\n" in b

    def test_empty_bundle_is_empty_string(self) -> None:
        assert bundle() == ""


class TestPackageTreeIsConsistent:
    def test_every_js_file_in_tree_is_loadable(self) -> None:
        # Walk the page_scripts package tree and assert every .js file
        # loads via `load(...)`. Catches typos in stub names + missing
        # __init__.py files in subpackages.
        root = files("rpa_recorder.page_scripts")
        scripts: list[str] = []
        for sub in root.iterdir():
            if not sub.is_dir():
                continue
            for entry in sub.iterdir():
                if entry.is_file() and entry.name.endswith(".js"):
                    rel = f"{sub.name}/{entry.name[:-3]}"
                    scripts.append(rel)
        assert scripts, "no .js files discovered under page_scripts"
        for path in scripts:
            assert isinstance(load(path), str)
