# M7 — Heuristic classifier (modular pipeline)

**Status:** in progress (this milestone)

**Source:** [.claude/plans/bootstrap.md](../.claude/plans/bootstrap.md) §Classifier; [build-plan.md](build-plan.md) for upstream/downstream context. Replaces the original single-function sketch with a three-pipeline architecture so new heuristics drop in as small, isolated modules.

## Goal

A pure-Python, rule-based first-pass that processes `RecordedAction` rows through three composable pipelines:

1. **Filter** — drops actions that are noise (focus-only inputs without typing, duplicate navigates to the same URL, actions on disabled elements).
2. **Normalize** — cleans surviving actions (trim input whitespace, coalesce rapid-keystroke bursts, canonicalize navigate URLs).
3. **Classify** — assigns a `(SemanticIntent, confidence, reasoning, source)` tuple to each remaining action.

When no classify rule produces a candidate above the configured floor, the action stays at `(UNKNOWN, 0.0, ...)` so the M9 LLM tier can take over.

The architecture is designed so a new heuristic — say, "recognize 2FA code entry" — drops in as a single new file under `classifiers/`, registers itself in the default-rule list, and ships with its own unit test. No edits to existing rules, no changes to the engine.

## Files

### Create

- `src/rpa_recorder/classifier/heuristic/__init__.py` — public API: `HeuristicEngine`, `default_pipeline()`, `Classification`, `classify()` (single-action shim)
- `src/rpa_recorder/classifier/heuristic/protocol.py` — `FilterRule`, `NormalizeRule`, `ClassifyRule`, `RuleContext`, `Classification`, `ClassifyCandidate`
- `src/rpa_recorder/classifier/heuristic/engine.py` — `FilterPipeline`, `NormalizePipeline`, `ClassifyPipeline`, `HeuristicEngine`
- `src/rpa_recorder/classifier/heuristic/filters/__init__.py` — explicit registry: `default_filters()` returns `list[FilterRule]`
- `src/rpa_recorder/classifier/heuristic/filters/drop_focus_blur_only.py`
- `src/rpa_recorder/classifier/heuristic/filters/drop_duplicate_navigate.py`
- `src/rpa_recorder/classifier/heuristic/filters/drop_disabled_target.py`
- `src/rpa_recorder/classifier/heuristic/filters/drop_coalesced_followers.py` — paired with the coalesce normalizer
- `src/rpa_recorder/classifier/heuristic/normalizers/__init__.py` — `default_normalizers()`
- `src/rpa_recorder/classifier/heuristic/normalizers/trim_input_value.py`
- `src/rpa_recorder/classifier/heuristic/normalizers/coalesce_input_bursts.py`
- `src/rpa_recorder/classifier/heuristic/normalizers/canonicalize_url.py`
- `src/rpa_recorder/classifier/heuristic/classifiers/__init__.py` — `default_classifiers()`
- `src/rpa_recorder/classifier/heuristic/classifiers/login.py`
- `src/rpa_recorder/classifier/heuristic/classifiers/search.py`
- `src/rpa_recorder/classifier/heuristic/classifiers/form_submit.py`
- `src/rpa_recorder/classifier/heuristic/classifiers/confirmation.py`
- `src/rpa_recorder/classifier/heuristic/classifiers/dismiss_modal.py`
- `src/rpa_recorder/classifier/heuristic/classifiers/navigation.py`
- `src/rpa_recorder/classifier/heuristic/classifiers/form_fill.py`
- `tests/test_heuristic_protocol.py`
- `tests/test_heuristic_engine.py`
- `tests/test_heuristic_filters.py`
- `tests/test_heuristic_normalizers.py`
- `tests/test_heuristic_classifiers.py`

### Modify

- `src/rpa_recorder/classifier/__init__.py` — re-export `HeuristicEngine`, `Classification`, `default_pipeline`, `classify` (back-compat single-action API).

### Delete

- `src/rpa_recorder/classifier/heuristic.py` — the existing uncommitted single-file sketch is superseded by the package above.

## Public API

### `classifier/heuristic/protocol.py`

```python
class RuleContext(BaseModel):
    """Information rules might need beyond the action itself.

    Constructed once per Recording inside HeuristicEngine.process. Rules
    must treat `actions` as read-only; mutate state through `scratch`.
    """
    actions: list[RecordedAction]                # the full sequence after filter (for normalizers + classifiers)
    index: int                                   # current action's position in `actions`
    scratch: dict[str, Any] = Field(default_factory=dict)


class Classification(BaseModel):
    """Final per-action verdict produced by ClassifyPipeline."""
    intent: SemanticIntent
    confidence: float                            # 0.0–1.0
    reasoning: str
    source: str                                  # rule.name that produced this verdict


class ClassifyCandidate(BaseModel):
    """A single rule's verdict; the pipeline picks the highest-confidence one."""
    intent: SemanticIntent
    confidence: float
    reasoning: str
    source: str


class FilterRule(Protocol):
    name: str

    def apply(self, action: RecordedAction, ctx: RuleContext) -> bool:
        """True keeps, False drops."""


class NormalizeRule(Protocol):
    name: str

    def apply(self, action: RecordedAction, ctx: RuleContext) -> RecordedAction:
        """Return a possibly-modified action; returning the input unchanged is a no-op."""


class ClassifyRule(Protocol):
    name: str

    def apply(
        self, action: RecordedAction, ctx: RuleContext
    ) -> ClassifyCandidate | None:
        """Return a candidate or None to abstain. Abstaining is the default
        when the rule's preconditions don't match."""
```

### `classifier/heuristic/engine.py`

```python
class FilterPipeline:
    def __init__(self, rules: Sequence[FilterRule]) -> None: ...
    def apply(self, actions: list[RecordedAction]) -> list[RecordedAction]: ...


class NormalizePipeline:
    def __init__(self, rules: Sequence[NormalizeRule]) -> None: ...
    def apply(self, actions: list[RecordedAction]) -> list[RecordedAction]: ...


class ClassifyPipeline:
    def __init__(self, rules: Sequence[ClassifyRule]) -> None: ...
    def apply(self, action: RecordedAction, ctx: RuleContext) -> Classification: ...


class HeuristicEngine:
    def __init__(
        self,
        filter_pipeline: FilterPipeline,
        normalize_pipeline: NormalizePipeline,
        classify_pipeline: ClassifyPipeline,
    ) -> None: ...

    def process(
        self, actions: list[RecordedAction]
    ) -> list[tuple[RecordedAction, Classification]]:
        """Filter → Normalize → Classify. Returns (cleaned_action, verdict) pairs."""
```

### `classifier/heuristic/__init__.py`

```python
from .engine import HeuristicEngine, FilterPipeline, NormalizePipeline, ClassifyPipeline
from .filters import default_filters
from .normalizers import default_normalizers
from .classifiers import default_classifiers
from .protocol import (
    Classification, ClassifyCandidate, FilterRule, NormalizeRule, ClassifyRule, RuleContext,
)


def default_pipeline() -> HeuristicEngine:
    """Construct the engine with the project's curated default rule set."""
    return HeuristicEngine(
        filter_pipeline=FilterPipeline(default_filters()),
        normalize_pipeline=NormalizePipeline(default_normalizers()),
        classify_pipeline=ClassifyPipeline(default_classifiers()),
    )


def classify(action: RecordedAction) -> Classification:
    """Single-action convenience for callers without a full sequence (tests, REPL).

    Builds a one-element RuleContext and runs only the classify pipeline.
    Filter and normalize are skipped since they typically need surrounding context.
    """
    engine = default_pipeline()
    ctx = RuleContext(actions=[action], index=0)
    return engine.classify_pipeline.apply(action, ctx)
```

### Per-rule module shape

Each rule module exports exactly one class. Example (`classifiers/login.py`):

```python
class LoginClassifier:
    name = "login"

    def apply(
        self, action: RecordedAction, ctx: RuleContext
    ) -> ClassifyCandidate | None:
        if action.action_type is not ActionType.INPUT:
            return None
        ctx_attrs = (action.element_context.attributes if action.element_context else {})
        if ctx_attrs.get("type") == "password":
            return ClassifyCandidate(
                intent=SemanticIntent.LOGIN,
                confidence=0.95,
                reasoning="password field",
                source=self.name,
            )
        return None
```

This shape is the contract for *every* rule. Adding a new heuristic = a new file with one class implementing the same shape.

### Registry shape

Each subpackage's `__init__.py` is the explicit registry:

```python
# classifiers/__init__.py
from .login import LoginClassifier
from .search import SearchClassifier
from .form_submit import FormSubmitClassifier
from .confirmation import ConfirmationClassifier
from .dismiss_modal import DismissModalClassifier
from .navigation import NavigationClassifier
from .form_fill import FormFillClassifier


def default_classifiers() -> list[ClassifyRule]:
    """Order matters only for tie-breaking; confidence dominates."""
    return [
        LoginClassifier(),           # 0.95
        SearchClassifier(),          # 0.90
        FormSubmitClassifier(),      # 0.85
        ConfirmationClassifier(),    # 0.80
        DismissModalClassifier(),    # 0.80
        NavigationClassifier(),      # 1.00
        FormFillClassifier(),        # 0.70 (catch-all for INPUT)
    ]
```

To add a rule: create the module, import + append in this list, write a unit test.

## Behavior

### Pipeline execution order

`HeuristicEngine.process(actions)` runs in this fixed order:

1. **Filter first.** Removes noise so subsequent stages don't waste work on it.
2. **Normalize second.** Cleans surviving actions before classification — e.g., trim trailing whitespace before checking if a button text matches `/^submit$/i`.
3. **Classify last.** Runs against the final, cleaned action stream.

Within each pipeline, rules run in declaration order. The default order is curated; callers can construct custom pipelines by passing their own list to `FilterPipeline(...)` etc.

### Filter pipeline semantics

- Each rule is asked `apply(action, ctx) -> bool`. Returns `True` to keep, `False` to drop.
- Rules are AND-ed: an action survives only if every rule says `True`. One drop and the action is gone.
- Drops are not silently lost — `FilterPipeline.apply` emits a `structlog.debug(rule_name=..., sequence=..., reason=...)` for every drop so traceability is preserved.
- Rules cannot mutate the action (mypy strict + Pydantic immutability enforces this).

### Normalize pipeline semantics

- Each rule is asked `apply(action, ctx) -> RecordedAction`. The returned action is passed to the next rule, so rules chain: `final = ruleN(... rule2(rule1(action)) ...)`.
- A no-op rule returns the input unchanged; modifications use `action.model_copy(update={...})` (Pydantic v2 immutable-friendly).
- `ctx.actions` reflects the post-filter sequence (so cross-action normalizers see only survivors).

### Classify pipeline semantics

- Each rule is asked `apply(action, ctx) -> ClassifyCandidate | None`. `None` means "this rule abstains."
- All rules run for every action — no early exit. The pipeline collects every candidate, then picks the one with the **highest `confidence`**. Ties broken by registration order (earlier wins).
- If no rule produces a candidate, the result is `Classification(intent=UNKNOWN, confidence=0.0, reasoning="no rule matched", source="default")`.
- The chosen `Classification` becomes what the M8 CLI persists to `RecordedActionRow.semantic_intent` / `classification_confidence` / `classification_reasoning` (with `source` folded in as a `"[<source>] <reasoning>"` prefix until M11.5 adds a dedicated column).

### Default filter rules

| Rule | Drop when |
|---|---|
| `drop_focus_blur_only` | `INPUT` action with empty value AND no follow-up `INPUT` on the same selector within 2000 ms (focus/blur without typing) |
| `drop_duplicate_navigate` | `NAVIGATE` action whose URL matches the immediately preceding action's URL (idempotent reloads, hash-only changes) |
| `drop_disabled_target` | any action on an element with `element_context.is_enabled=False` (defensive — flaky pages occasionally fire) |
| `drop_coalesced_followers` | `INPUT` action whose `sequence` appears in `ctx.scratch["coalesced_indexes"]` (paired with the coalesce normalizer; see pitfalls) |

### Default normalize rules

| Rule | Effect |
|---|---|
| `trim_input_value` | for `INPUT` payloads, replaces `value` with `value.strip()` unless `is_sensitive=True` |
| `coalesce_input_bursts` | when N consecutive `INPUT` actions target the same selector within 200 ms, returns a single merged action carrying the *last* value; marks followers' indexes in `ctx.scratch["coalesced_indexes"]` for `drop_coalesced_followers` to remove |
| `canonicalize_url` | for `NAVIGATE` payloads, lowercases scheme + host, strips trailing slashes from path, sorts query params alphabetically; hash fragment preserved verbatim (might be route-relevant) |

### Default classify rules

| Rule | Fires when | Verdict |
|---|---|---|
| `login` | `INPUT` on `attributes.type == "password"` | `(LOGIN, 0.95)` |
| `search` | `INPUT` on `selector.role == "searchbox"` OR `attributes.type == "search"` OR placeholder/`name`/`aria-label` contains "search" (case-insensitive) | `(SEARCH, 0.90)` |
| `form_submit` | `CLICK` on text matching `/^(submit|save|continue|next)$/i` AND `element_context.parent_form_id is not None` | `(FORM_SUBMIT, 0.85)` |
| `confirmation` | `CLICK` on text matching `/^(ok|confirm|yes|accept)$/i` | `(CONFIRMATION, 0.80)` |
| `dismiss_modal` | `CLICK` where `aria-label` matches `/close|dismiss/i` OR class contains "close" OR text in `{×, ✕, x, "close"}` | `(DISMISS_MODAL, 0.80)` |
| `navigation` | `action_type == NAVIGATE` | `(NAVIGATION, 1.00)` |
| `form_fill` | any `INPUT` action (catch-all) | `(FORM_FILL, 0.70)` |

The catch-all `form_fill` always fires for INPUT, but its 0.70 confidence means LOGIN (0.95) and SEARCH (0.90) shadow it when they match. That's the intended interaction.

### Adding a new rule (worked example: 2FA code entry)

1. Create `src/rpa_recorder/classifier/heuristic/classifiers/mfa.py`:
   ```python
   class MfaCodeClassifier:
       name = "mfa_code"

       def apply(self, action, ctx):
           if action.action_type is not ActionType.INPUT:
               return None
           attrs = action.element_context.attributes if action.element_context else {}
           if (
               attrs.get("autocomplete") == "one-time-code"
               or "otp" in (attrs.get("name") or "").lower()
           ):
               return ClassifyCandidate(
                   intent=SemanticIntent.LOGIN,
                   confidence=0.93,
                   reasoning="2FA / one-time-code field",
                   source=self.name,
               )
           return None
   ```
2. Add `MfaCodeClassifier()` to `default_classifiers()` in `classifiers/__init__.py`.
3. Add `tests/test_heuristic_classifiers.py::test_mfa_code_classifier_fires_on_otp_autocomplete`.

No other file changes. Same pattern for new filters or normalizers.

## Medallion / worker integration

Minimal at this stage — the engine is pure-Python and runs in-process. Two downstream touchpoints:

- **M9 (LLM classifier)** wraps `HeuristicEngine` in a hybrid `Classifier`: heuristic runs first, LLM runs only when `Classification.confidence < Config.classifier_confidence_threshold`. The `source` field then reflects which tier (`heuristic:<rule>` or `llm`).
- **M11.5 (gold cold)** reads `Classification.source` from `classification_reasoning` (or the future column) when computing `gold_classifier_accuracy_history.parquet`. The per-rule attribution is what makes the heuristic's accuracy independently measurable from the LLM's.

No bronze writes from this milestone.

## Integration points

| Touch | File | How |
|---|---|---|
| M2 → M7 | [src/rpa_recorder/models/actions.py](../src/rpa_recorder/models/actions.py) | reads `RecordedAction`, `SemanticIntent`, `ElementContext`, `ActionType`, payload models |
| M5 → M7 | [src/rpa_recorder/storage/repositories.py](../src/rpa_recorder/storage/repositories.py) | M8 calls `RecordingRepository.save(...)` after running the engine |
| M7 → M8 | [src/rpa_recorder/cli.py](../src/rpa_recorder/cli.py) | `rpa classify <id>` instantiates `default_pipeline()` and runs it across the recording's actions |
| M7 → M9 | M9 `Classifier` composes the heuristic engine with the LLM tier |
| M7 → M11 | confirmation flow may overwrite `Classification.intent` with `user_label`; `user_confirmed=True` flips |
| M7 → M11.5 | `gold_classifier_accuracy` aggregates by `Classification.source` |

## Models / DB rows used

- **Reads:** `RecordedAction`, `ElementContext`, `ElementSelector`, `ClickPayload`, `InputPayload`, `NavigatePayload`, `SelectPayload` (M2).
- **Produces:** in-memory `Classification` objects. Persistence is M8's responsibility (CLI updates `RecordedActionRow.semantic_intent` / `classification_confidence` / `classification_reasoning`).
- **No DB schema change** in this milestone. `Classification.source` is stored as a `[<source>]` prefix in `classification_reasoning` until M11.5 wants per-rule attribution at column granularity.

## Tests

`tests/test_heuristic_protocol.py`:

- `test_classification_round_trips_through_pydantic` — validates `Classification` and `ClassifyCandidate` round-trip via `model_dump` / `model_validate`.
- `test_rule_context_scratch_is_mutable_dict` — assert that mutating `ctx.scratch` from one rule is visible to a later rule with the same `ctx`.

`tests/test_heuristic_engine.py`:

- `test_engine_runs_pipelines_in_order_filter_normalize_classify` — recording with one noise action, one whitespace-padded input, one valid click; assert noise dropped, whitespace trimmed, click classified.
- `test_classify_picks_highest_confidence_candidate` — register two rules: one returns `(LOGIN, 0.5, ...)`, one returns `(SEARCH, 0.9, ...)` for the same action. Engine picks SEARCH.
- `test_classify_breaks_ties_by_registration_order` — two rules return identical 0.7 confidence; the one registered first wins.
- `test_classify_returns_unknown_when_no_rule_matches` — single CLICK on an element no rule recognizes; result is `(UNKNOWN, 0.0, "no rule matched", "default")`.
- `test_engine_logs_dropped_actions_with_rule_name(caplog)` — capture structlog output; assert each filtered drop logs `rule_name`, `sequence`, and `reason`.
- `test_engine_supports_custom_pipeline` — instantiate `HeuristicEngine(filter_pipeline=FilterPipeline([]), ...)` with empty filter; assert nothing is dropped.
- `test_default_pipeline_smoke` — `default_pipeline()` returns a working engine; processes a 5-action fixture without raising; result list length == filtered count.
- `test_engine_constructs_fresh_context_per_process_call` — call `process()` twice; assert `ctx.scratch` from the first call doesn't leak into the second.

`tests/test_heuristic_filters.py` (one parametrized test per rule):

- `test_drop_focus_blur_only_drops_empty_input_with_no_followup` — three actions: focus-only input on `#email`, click, focus-only input on `#name`. Engine outputs only the click.
- `test_drop_focus_blur_only_keeps_input_with_followup_typing` — focus-only input followed within 200 ms by a real value-typing input; first one kept (followup proves it wasn't focus-only).
- `test_drop_duplicate_navigate_drops_consecutive_same_url` — two NAVIGATE actions to `/home`; one survives.
- `test_drop_disabled_target_drops_disabled_action` — input with `is_enabled=False` is removed; same input with `is_enabled=True` is kept.
- `test_drop_coalesced_followers_consumes_scratch` — populate `ctx.scratch["coalesced_indexes"]={2,3}`; sequence-2 and -3 actions dropped; sequence-1 and -4 kept.

`tests/test_heuristic_normalizers.py`:

- `test_trim_input_value_strips_whitespace` — value `"  alice  "` → `"alice"`.
- `test_trim_input_value_preserves_sensitive` — `is_sensitive=True` value unchanged (passwords often have intentional leading/trailing chars).
- `test_coalesce_input_bursts_merges_rapid_typing` — three INPUT actions on `#email` within 100 ms with values `"a"`, `"al"`, `"ali"`; engine output has one INPUT with value `"ali"`.
- `test_coalesce_input_bursts_keeps_separate_when_gap_exceeds_threshold` — two INPUT actions on `#email` 500 ms apart; both kept.
- `test_canonicalize_url_lowercases_scheme_and_host` — `HTTP://Example.COM/` → `http://example.com/`.
- `test_canonicalize_url_sorts_query_params` — `?b=2&a=1` → `?a=1&b=2`.
- `test_canonicalize_url_preserves_hash_fragment` — `https://x.com/#section` unchanged.

`tests/test_heuristic_classifiers.py`:

- `test_login_classifier_fires_on_password_field` — input action with `attributes={"type": "password"}` → LOGIN, 0.95.
- `test_search_classifier_fires_on_role_searchbox` — input with `selector.role="searchbox"` → SEARCH, 0.9.
- `test_search_classifier_fires_on_type_search` — input with `attributes={"type": "search"}` → SEARCH.
- `test_search_classifier_fires_on_placeholder_contains_search` — placeholder "Search products…" → SEARCH.
- `test_form_submit_fires_inside_form_only` — click on text "Submit" with `parent_form_id="loginForm"` → FORM_SUBMIT; same click with `parent_form_id=None` → returns None.
- `test_confirmation_classifier_fires_on_confirm_text` — text "Confirm" → CONFIRMATION, 0.8.
- `test_confirmation_classifier_is_case_insensitive` — "OK", "ok", "Ok" all fire.
- `test_dismiss_modal_fires_on_close_icon` — text "✕" → DISMISS_MODAL.
- `test_dismiss_modal_fires_on_aria_label` — `aria-label="Close dialog"` → DISMISS_MODAL.
- `test_navigation_classifier_always_fires_on_navigate` — `action_type=NAVIGATE` → NAVIGATION, 1.0.
- `test_form_fill_classifier_is_catch_all` — input that no other rule claims → FORM_FILL, 0.7.
- `test_form_fill_loses_to_login_when_both_match` — full pipeline: input on a password field; LOGIN wins (0.95 > 0.70).
- `test_classifier_abstains_when_action_type_does_not_match` — login classifier on a NAVIGATE action returns None.

Test fixtures build small `RecordedAction` instances with the relevant `ElementContext` / `ElementSelector` fields populated. No browser involvement.

Coverage target: **≥95% branch coverage** on the rule modules and engine. Each new rule module must arrive with at least one positive-firing test and one abstain test.

## Known pitfalls

- **Coalescing is cross-action, but the per-rule API is one-action-at-a-time.** `coalesce_input_bursts` needs to look at neighbors. Keep it as a normalizer that uses `ctx.scratch["coalesced_indexes"]` to mark followers, paired with `drop_coalesced_followers` filter that consumes the scratch dict. This preserves the simple per-rule shape and makes the coalescing logic localized to two cooperating files.
  - **However:** filters run *before* normalizers, so `drop_coalesced_followers` runs in the wrong stage by default. The fix: the coalesce normalizer also writes a coalesced action **and** a `scratch["coalesce_drops"]: set[int]` set during the *normalize* pass; the engine then runs a *post-normalize filter pass* (one extra pipeline) using `drop_coalesced_followers`. Document this exception clearly in `engine.py`.
- **Classify pipeline = "all rules run, highest-confidence wins"**, not "first match wins". A rule that returns 0.99 unconditionally will dominate. Document the confidence convention in `protocol.py` (cap rules at 0.95 unless they have ground-truth signal like `type=password`; reserve 1.00 for `NavigationClassifier` and similar where the rule is logically equivalent to the action type).
- **`form_fill` catch-all positioning.** It returns 0.70 for any INPUT, intended to be shadowed by LOGIN (0.95) and SEARCH (0.90). If you accidentally raise its confidence above LOGIN, LOGIN gets shadowed. The test `test_form_fill_loses_to_login_when_both_match` guards against regressions.
- **`Classification.source` not in DB.** Until M11.5 wants per-rule accuracy attribution at column granularity, the `source` is stored as a `[<source>]` prefix in `classification_reasoning`. M11.5 can either add a column (one Alembic migration) or parse the prefix at query time. Don't add the column in M7 — it's premature.
- **`RuleContext.scratch` lifecycle.** Scratch is reset between `HeuristicEngine.process` calls. Within one `process` call, scratch persists across pipelines (filter → normalize → classify) so the coalesce normalizer can hand off to `drop_coalesced_followers`. Document this in `protocol.py`.
- **Pydantic v2 mutability.** If `RecordedAction` is configured `frozen=True` in M2, normalizers must use `action.model_copy(update={"payload": new_payload})` rather than direct attribute assignment. Verify M2 config; if not frozen today, the right hardening is to make it frozen and update normalizers — but that's a follow-up cleanup, not in M7's scope.
- **Existing uncommitted `heuristic.py`.** Delete it. Don't try to evolve the single-function API into the new package — the call signatures are incompatible (single `tuple[...]` return vs. structured `Classification`). The M8 CLI will import from the new package; nothing else references the old file.
- **PEP 758 `except` syntax.** Python 3.14 allows parens-less `except A, B:`. Style choice; either form works.

## Commit

`feat(classifier): add modular heuristic engine with filter / normalize / classify pipelines`

Body: replaces the single-function heuristic with a three-pipeline architecture. New rules drop in as small modules under `classifier/heuristic/{filters,normalizers,classifiers}/` with explicit registries. Default rule set covers password / search / submit / confirmation / dismiss-modal / navigation / form-fill plus filters for focus-only inputs, duplicate navigates, disabled targets, and coalesced followers, and normalizers for whitespace, URL canonicalization, and rapid-keystroke coalescing. Each rule is unit-tested in isolation; engine tests cover ordering, ties, custom pipelines, and structlog drop traceability.

## Critical files

- `src/rpa_recorder/classifier/heuristic/protocol.py` — the rule contracts
- `src/rpa_recorder/classifier/heuristic/engine.py` — pipelines + engine
- `src/rpa_recorder/classifier/heuristic/{filters,normalizers,classifiers}/__init__.py` — registries
- The per-rule modules under those subdirs
- `tests/test_heuristic_engine.py`, `test_heuristic_filters.py`, `test_heuristic_normalizers.py`, `test_heuristic_classifiers.py`, `test_heuristic_protocol.py`
