"""Canonicalize NAVIGATE URLs: lower scheme/host, strip trailing slashes, sort query."""

from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from rpa_recorder.models import ActionType, NavigatePayload, RecordedAction

if TYPE_CHECKING:
    from ..protocol import RuleContext


class CanonicalizeUrl:
    """Normalize the destination URL of NAVIGATE actions for comparison.

    - Scheme + netloc (host[:port]) lowercased.
    - Trailing slashes stripped from non-root paths.
    - Query parameters sorted alphabetically (preserving duplicates).
    - Fragment preserved verbatim — a `#section` may be route-relevant.
    """

    name: str = "canonicalize_url"

    def apply(self, action: RecordedAction, ctx: RuleContext) -> RecordedAction:  # noqa: ARG002
        if action.action_type is not ActionType.NAVIGATE:
            return action
        if not isinstance(action.payload, NavigatePayload):
            return action

        parsed = urlparse(action.payload.url)
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path
        if len(path) > 1:
            path = path.rstrip("/") or "/"
        query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
        canonical = urlunparse((scheme, netloc, path, parsed.params, query, parsed.fragment))
        if canonical == action.payload.url:
            return action
        new_payload = action.payload.model_copy(update={"url": canonical})
        return action.model_copy(update={"payload": new_payload})
