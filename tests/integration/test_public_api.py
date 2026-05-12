"""Guard rails for the public API surface in `rpa_recorder/__init__.py`.

These tests don't exercise behavior — they protect against accidental removal
or rename of advertised re-exports. If the public API needs to change, this
file should change in lock-step with the version bump in pyproject.toml.
"""

import importlib


def test_top_level_reexports_data_models() -> None:
    mod = importlib.import_module("rpa_recorder")
    for name in [
        "RecordedAction",
        "ActionType",
        "ElementSelector",
        "ElementContext",
        "ClickPayload",
        "InputPayload",
        "NavigatePayload",
        "SelectPayload",
        "SemanticIntent",
        "ActionPayload",
        "Recording",
        "NetworkEvent",
        "ParameterDef",
        "REDACTED_VALUE",
    ]:
        assert hasattr(mod, name), f"missing public re-export: {name}"


def test_top_level_reexports_classifier_surface() -> None:
    mod = importlib.import_module("rpa_recorder")
    for name in ["HeuristicEngine", "default_pipeline", "classify", "Classification"]:
        assert hasattr(mod, name), f"missing public re-export: {name}"


def test_top_level_reexports_medallion_surface() -> None:
    mod = importlib.import_module("rpa_recorder")
    for name in ["BronzeWriter", "BronzeStore", "LocalFilesystemStore"]:
        assert hasattr(mod, name), f"missing public re-export: {name}"


def test_top_level_reexports_integration_surface() -> None:
    mod = importlib.import_module("rpa_recorder")
    for name in [
        "SeleniumEvent",
        "SeleniumLocators",
        "SeleniumTarget",
        "SeleniumEventTranslator",
        "IngestSession",
        "SyncIngestSession",
        "EventType",
    ]:
        assert hasattr(mod, name), f"missing public re-export: {name}"


def test_config_is_reexported() -> None:
    mod = importlib.import_module("rpa_recorder")
    assert hasattr(mod, "Config")


def test_version_is_advertised() -> None:
    mod = importlib.import_module("rpa_recorder")
    assert hasattr(mod, "__version__")
    assert isinstance(mod.__version__, str)
    assert mod.__version__ == "0.2.0"


def test_all_listing_matches_module_attributes() -> None:
    mod = importlib.import_module("rpa_recorder")
    assert hasattr(mod, "__all__")
    for name in mod.__all__:
        assert hasattr(mod, name), f"declared in __all__ but missing: {name}"
