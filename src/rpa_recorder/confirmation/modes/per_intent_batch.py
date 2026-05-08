"""M11 review mode: bulk-handle every action of a given intent in one prompt.

Demonstrates mode composition — the relabel-each branch falls back to
`PerActionMode().review(...)` for that intent's actions, so we don't
re-implement per-action prompting.
"""

from collections import defaultdict
from datetime import UTC, datetime

from rich.prompt import Prompt

from rpa_recorder.cli.console import console
from rpa_recorder.confirmation.modes.per_action import PerActionMode
from rpa_recorder.confirmation.protocol import (
    ActionReviewResult,
    Decision,
    OnDecision,
    Renderer,
)
from rpa_recorder.models import RecordedAction, SemanticIntent

_INTENT_CHOICES: list[str] = [member.value for member in SemanticIntent]


class PerIntentBatchMode:
    """Group candidates by `semantic_intent`, prompt once per group."""

    name = "per_intent_batch"

    def __init__(self, fallback: PerActionMode | None = None) -> None:
        self._fallback = fallback or PerActionMode()

    async def review(
        self,
        candidates: list[RecordedAction],
        *,
        renderer: Renderer,
        on_decision: OnDecision,
    ) -> list[ActionReviewResult]:
        groups: dict[SemanticIntent, list[RecordedAction]] = defaultdict(list)
        for action in candidates:
            groups[action.semantic_intent].append(action)

        results: list[ActionReviewResult] = []
        for intent, actions in groups.items():
            console.print(renderer.render_intent_batch(intent, actions))
            answer = Prompt.ask(
                "[a]ccept all / [r]eview each / [s]kip group / [c]ustom relabel",
                choices=["a", "r", "s", "c"],
                default="a",
            )
            if answer == "a":
                for action in actions:
                    result = ActionReviewResult(
                        action_id=action.id,
                        decision=Decision.ACCEPT,
                        reviewed_at=datetime.now(UTC),
                    )
                    await on_decision(result)
                    results.append(result)
            elif answer == "r":
                results.extend(
                    await self._fallback.review(actions, renderer=renderer, on_decision=on_decision)
                )
            elif answer == "c":
                new_label_str = Prompt.ask(
                    "label for whole group",
                    choices=_INTENT_CHOICES,
                    default="unknown",
                )
                new_label = SemanticIntent(new_label_str)
                for action in actions:
                    result = ActionReviewResult(
                        action_id=action.id,
                        decision=Decision.RELABEL,
                        new_label=new_label,
                        reviewed_at=datetime.now(UTC),
                    )
                    await on_decision(result)
                    results.append(result)
            else:
                for action in actions:
                    result = ActionReviewResult(
                        action_id=action.id,
                        decision=Decision.SKIP,
                        reviewed_at=datetime.now(UTC),
                    )
                    await on_decision(result)
                    results.append(result)
        return results


__all__ = ["PerIntentBatchMode"]
