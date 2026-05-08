"""Default M11 review mode: walk candidates one at a time, prompt per action.

`rich.prompt.Prompt.ask` is synchronous; calling it inside `async def` blocks
the event loop. That is intentional and fine here — the user is the loop's
only task. Wrapping in `asyncio.to_thread` would add latency and complicate
Ctrl+C handling.
"""

from datetime import UTC, datetime

from rich.prompt import Prompt

from rpa_recorder.cli.console import console
from rpa_recorder.confirmation.protocol import (
    ActionReviewResult,
    Decision,
    OnDecision,
    Renderer,
)
from rpa_recorder.models import RecordedAction, SemanticIntent

_INTENT_CHOICES: list[str] = [member.value for member in SemanticIntent]


class PerActionMode:
    """Sequential review: one prompt per candidate. Default mode."""

    name = "per_action"

    async def review(
        self,
        candidates: list[RecordedAction],
        *,
        renderer: Renderer,
        on_decision: OnDecision,
    ) -> list[ActionReviewResult]:
        results: list[ActionReviewResult] = []
        for action in candidates:
            console.print(renderer.render_action(action))
            answer = Prompt.ask(
                "[a]ccept / [r]elabel / [s]kip",
                choices=["a", "r", "s"],
                default="a",
            )
            if answer == "a":
                result = ActionReviewResult(
                    action_id=action.id,
                    decision=Decision.ACCEPT,
                    reviewed_at=datetime.now(UTC),
                )
            elif answer == "r":
                new_label_str = Prompt.ask("new label", choices=_INTENT_CHOICES, default="unknown")
                result = ActionReviewResult(
                    action_id=action.id,
                    decision=Decision.RELABEL,
                    new_label=SemanticIntent(new_label_str),
                    reviewed_at=datetime.now(UTC),
                )
            else:
                result = ActionReviewResult(
                    action_id=action.id,
                    decision=Decision.SKIP,
                    reviewed_at=datetime.now(UTC),
                )
            await on_decision(result)
            results.append(result)
        return results


__all__ = ["PerActionMode"]
