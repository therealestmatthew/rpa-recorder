"""Default parser: pull the first `reselect` tool_use block into an `ElementSelector`.

If no `reselect` tool block is present (or the block has no usable fields),
returns None. The orchestrator treats None as "abstain" — the audit row /
bronze blob still get written.
"""

from typing import TYPE_CHECKING

import structlog

from rpa_recorder.models import ElementSelector

if TYPE_CHECKING:
    from rpa_recorder.classifier.llm.protocol import LLMResponse

_log = structlog.get_logger(__name__)

_SELECTOR_FIELDS: tuple[str, ...] = (
    "test_id",
    "role",
    "accessible_name",
    "text_content",
    "css",
    "xpath",
)


def _str_or_none(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


class SelectorToolUseParser:
    """Find the first tool_use named `reselect` and return an `ElementSelector`."""

    name: str = "selector_tool_use"

    def parse(self, response: LLMResponse) -> ElementSelector | None:
        for call in response.tool_calls:
            if call.get("name") != "reselect":
                continue
            args = call.get("input", {}) or {}
            fields: dict[str, str | None] = {}
            for field in _SELECTOR_FIELDS:
                fields[field] = _str_or_none(args.get(field))
            if not any(v is not None for v in fields.values()):
                _log.warning("selector_reselect_empty", args=args)
                return None
            return ElementSelector(
                test_id=fields["test_id"],
                role=fields["role"],
                accessible_name=fields["accessible_name"],
                text_content=fields["text_content"],
                css=fields["css"],
                xpath=fields["xpath"],
            )
        return None


__all__ = ["SelectorToolUseParser"]
