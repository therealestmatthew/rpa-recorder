# M9 — LLM classifier (modular pluggable backends)

**Status:** pending

**Source:** [.claude/plans/bootstrap.md](../.claude/plans/bootstrap.md) §Classifier; [build-plan.md](build-plan.md) §Concurrency conventions for cross-cutting rules. Replaces the original sketch with a modular architecture so backends, prompt strategies, response parsers, retry policies, caches, and merge strategies are independently swappable.

## Goal

An Anthropic-backed LLM classifier composed of five swappable concerns plus three orthogonal ones, then wrapped by a hybrid `Classifier` that composes with the M7 heuristic engine:

| Concern | Protocol | Default impl |
|---|---|---|
| Backend (model API call) | `LLMBackend` | `AnthropicBackend` |
| Prompt building | `PromptStrategy` | `ClassifyV1Prompt` |
| Response parsing | `ResponseParser` | `ToolUseParser` (fallback `JsonModeParser`, `FreeFormParser`) |
| Retry policy | `RetryPolicy` | `ExponentialBackoffRetry(max_attempts=3)` |
| Merge (heuristic + LLM) | `MergeStrategy` | `HighestConfidenceMerge` |
| Response cache | `ResponseCache` | `RedisResponseCache` (or `InMemoryResponseCache`) |
| Concurrency control | `asyncio.Semaphore` | size=`Config.llm_max_concurrency` (5) |
| Cost guard | `BudgetGuard` | Redis daily counter w/ `Config.llm_daily_budget_usd` |

The hybrid `Classifier` runs the heuristic engine first; only when `confidence < threshold` does it call the LLM tier. Results are merged by the configured `MergeStrategy`. Every LLM call writes a bronze JSON blob (M6.5), a silver `LLMCallRow` (M5), and a cache entry — atomic via `asyncio.TaskGroup`.

## Files

### Create

- `src/rpa_recorder/classifier/llm/__init__.py` — public API: `LLMClassifier`, `Classifier`, `default_classifier()`
- `src/rpa_recorder/classifier/llm/protocol.py` — Protocols + Pydantic models (`LLMResponse`, etc.)
- `src/rpa_recorder/classifier/llm/classifier.py` — `LLMClassifier` orchestrator
- `src/rpa_recorder/classifier/llm/hybrid.py` — `Classifier` (heuristic + LLM composition) and `classify_batch`
- `src/rpa_recorder/classifier/llm/backends/__init__.py`
- `src/rpa_recorder/classifier/llm/backends/anthropic.py` — `AnthropicBackend`
- `src/rpa_recorder/classifier/llm/prompts/__init__.py`
- `src/rpa_recorder/classifier/llm/prompts/base.py` — shared helpers: redact, truncate, signature
- `src/rpa_recorder/classifier/llm/prompts/classify_v1.py` — `ClassifyV1Prompt`
- `src/rpa_recorder/classifier/llm/parsers/__init__.py`
- `src/rpa_recorder/classifier/llm/parsers/tool_use.py` — `ToolUseParser`
- `src/rpa_recorder/classifier/llm/parsers/json_mode.py` — `JsonModeParser`
- `src/rpa_recorder/classifier/llm/parsers/free_form.py` — `FreeFormParser` (regex fallback)
- `src/rpa_recorder/classifier/llm/retry.py` — `ExponentialBackoffRetry`, `NoRetry`
- `src/rpa_recorder/classifier/llm/cache.py` — `RedisResponseCache`, `InMemoryResponseCache`
- `src/rpa_recorder/classifier/llm/cost.py` — `compute_cost(...)`, `MODEL_RATES`, `BudgetGuard`
- `src/rpa_recorder/classifier/llm/concurrency.py` — semaphore factory keyed per-backend
- `src/rpa_recorder/classifier/llm/merge.py` — `HighestConfidenceMerge`, `VotingMerge`, `WeightedMerge`
- `tests/test_llm_protocol.py`
- `tests/test_llm_anthropic_backend.py`
- `tests/test_llm_prompts.py`
- `tests/test_llm_parsers.py`
- `tests/test_llm_retry.py`
- `tests/test_llm_cache.py`
- `tests/test_llm_cost.py`
- `tests/test_llm_concurrency.py`
- `tests/test_llm_merge.py`
- `tests/test_llm_classifier.py`
- `tests/test_llm_hybrid.py`

### Modify

- `src/rpa_recorder/classifier/__init__.py` — re-export `Classifier`, `default_classifier()`
- `src/rpa_recorder/cli/commands/classify.py` — switch from `default_pipeline()` (M7) to `default_classifier()` (hybrid)
- `src/rpa_recorder/config.py` — add `llm_max_concurrency: int = 5`, `llm_cache_ttl_s: int = 86400`, `llm_daily_budget_usd: float = 5.0`, `llm_request_timeout_s: float = 60.0`

## Public API

### `protocol.py`

```python
class LLMResponse(BaseModel):
    text: str | None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    input_tokens: int
    output_tokens: int
    stop_reason: str
    raw: dict[str, Any]                  # full SDK response, written to bronze


class LLMBackend(Protocol):
    name: str                            # "anthropic", "openai", ...
    model: str

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float = 0.0,
        timeout_s: float = 60.0,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse: ...


class PromptStrategy(Protocol):
    name: str
    version: str

    def build(
        self,
        action: RecordedAction,
        surrounding: list[RecordedAction],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
        """Returns (messages, tools). tools is None for non-tool-use prompts."""

    def signature(
        self, action: RecordedAction, surrounding: list[RecordedAction]
    ) -> str:
        """Stable hash key for caching. Excludes timestamps and IDs."""


class ResponseParser(Protocol):
    name: str

    def parse(self, response: LLMResponse) -> ClassifyCandidate | None: ...


class RetryPolicy(Protocol):
    async def execute(
        self,
        fn: Callable[[], Awaitable[T]],
        *,
        retryable: tuple[type[Exception], ...],
    ) -> T: ...


class MergeStrategy(Protocol):
    def merge(
        self,
        heuristic: ClassifyCandidate | None,
        llm: ClassifyCandidate | None,
    ) -> Classification: ...


class ResponseCache(Protocol):
    async def get(self, key: str) -> LLMResponse | None: ...
    async def set(self, key: str, response: LLMResponse, ttl_s: int) -> None: ...
```

### `classifier.py`

```python
class LLMClassifier:
    def __init__(
        self,
        *,
        backend: LLMBackend,
        prompt: PromptStrategy,
        parser: ResponseParser,
        retry: RetryPolicy,
        cache: ResponseCache | None = None,
        cache_ttl_s: int = 86400,
        semaphore: asyncio.Semaphore | None = None,
        bronze: BronzeWriter | None = None,
        session_factory: Callable[[], AsyncContextManager[AsyncSession]] | None = None,
        budget: BudgetGuard | None = None,
    ) -> None: ...

    async def classify(
        self,
        action: RecordedAction,
        surrounding: list[RecordedAction],
    ) -> ClassifyCandidate | None:
        """None means 'fall through to default UNKNOWN' (parse failure,
        budget exceeded, or model abstained)."""
```

### `hybrid.py`

```python
class Classifier:
    def __init__(
        self,
        *,
        heuristic: HeuristicEngine,
        llm: LLMClassifier,
        threshold: float = 0.7,
        merge: MergeStrategy | None = None,        # default HighestConfidenceMerge
    ) -> None: ...

    async def classify(
        self,
        action: RecordedAction,
        surrounding: list[RecordedAction],
    ) -> Classification: ...

    async def classify_batch(
        self, actions: list[RecordedAction]
    ) -> list[Classification]:
        """Async fan-out via asyncio.TaskGroup. Each LLM call is bounded
        by the LLMClassifier's semaphore. Per-action exceptions are
        converted to UNKNOWN classifications so one bad action doesn't
        abort the batch."""
```

### `__init__.py`

```python
from .classifier import LLMClassifier
from .hybrid import Classifier
from .backends.anthropic import AnthropicBackend
from .prompts.classify_v1 import ClassifyV1Prompt
from .parsers.tool_use import ToolUseParser
from .retry import ExponentialBackoffRetry
from .cache import RedisResponseCache, InMemoryResponseCache
from .merge import HighestConfidenceMerge


def default_classifier(*, redis: Redis | None = None) -> Classifier:
    """Curated defaults: Anthropic backend, classify_v1 prompt, tool-use
    parser, exponential backoff retry, Redis cache (or in-memory if redis
    is None), highest-confidence merge."""
```

## Behavior

### `LLMClassifier.classify` flow

1. **Build prompt**: `messages, tools = prompt.build(action, surrounding)`.
2. **Cache check**: `key = sha256(backend.model + prompt.version + prompt.signature(...))`; `cached = await cache.get(key)`. If hit, parse cached response and return — no API call, no LLM row.
3. **Budget check**: `await budget.check_or_raise()`. If today's spend exceeds `Config.llm_daily_budget_usd`, raise `LLMBudgetExceeded`.
4. **Acquire semaphore**: `async with semaphore:` caps parallel LLM calls to `Config.llm_max_concurrency`.
5. **Call backend with retry**: `response = await retry.execute(lambda: backend.complete(messages, tools=tools, ...), retryable=(RateLimitError, APIStatusError, asyncio.TimeoutError))`.
6. **Release semaphore** (implicit at `async with` exit).
7. **Parse**: `candidate = parser.parse(response)`. None → log a warning, still write the call row + bronze blob (audit), then return None.
8. **Persist** in parallel via `asyncio.TaskGroup`:
   - Bronze: `await bronze.write_llm_call(call_id, {prompt: messages, response: response.raw})`.
   - Silver: `LLMCallRow(called_for="classify", model, prompt, response_text, input_tokens, output_tokens, latency_ms, cost_usd, ...)`.
   - Cache: `await cache.set(key, response, ttl_s)`.
   - Budget: `await budget.record_spend(cost_usd)`.
9. **Return** the candidate.

The four persistence steps are independent so a failure in one (e.g., bronze write) doesn't block the others. Wrap each `tg.create_task(...)` body with its own try/except + structlog so a bronze failure logs but doesn't poison the silver write.

### `Classifier.classify` flow (hybrid)

1. Run `heuristic.classify_pipeline.apply(action, ctx)` → `heuristic_classification`.
2. If `heuristic_classification.confidence >= threshold`: return as-is (LLM is skipped — fast path).
3. Else: `llm_candidate = await llm.classify(action, surrounding)`.
4. Merge: `final = merge.merge(heuristic=<pulled from M7 candidates>, llm=llm_candidate)`.
5. The `source` becomes `"heuristic:<rule>"`, `"llm"`, or `"merged:<strategy>"`.

### `classify_batch` flow

```python
async def classify_batch(self, actions):
    results: list[Classification] = [None] * len(actions)
    async with asyncio.TaskGroup() as tg:
        for i, action in enumerate(actions):
            surrounding = actions[max(0, i-2):i+3]
            async def one(idx=i, a=action, s=surrounding):
                try:
                    results[idx] = await self.classify(a, s)
                except Exception as exc:
                    structlog.warning("classify_failed", action_id=a.id, exc=str(exc))
                    results[idx] = Classification(
                        intent=SemanticIntent.UNKNOWN,
                        confidence=0.0,
                        reasoning=f"classify failed: {exc}",
                        source="error",
                    )
            tg.create_task(one())
    return results
```

The `LLMClassifier`'s semaphore (size 5 by default) bounds total in-flight LLM calls, so even with 100 actions in the batch only 5 hit the API at once. Heuristic-only paths run unbounded (cheap).

### Caching

- **Key**: `sha256(model + prompt.version + signature(action, surrounding))`. The `signature` excludes volatile fields (timestamps, UUIDs) and includes selector + payload + element_context + surrounding action types.
- **Backends**:
  - `RedisResponseCache` — Redis hash with TTL. Used when a Redis client is available (production, M11.5 worker context).
  - `InMemoryResponseCache` — `cachetools.TTLCache(maxsize=10_000, ttl=ttl_s)`. Used for tests and local dev without Redis.
- **TTL**: default 24 h via `Config.llm_cache_ttl_s`.
- **Stored format**: the *raw* `LLMResponse` (so token counts and stop_reason replay correctly); the parser runs again on cache hit (cheap; gives us the typed `ClassifyCandidate`).
- **Versioning**: bumping `prompt.version` naturally invalidates old entries. Don't manually flush Redis on prompt changes.

### Concurrency

- `LLMClassifier` constructor accepts a `semaphore: asyncio.Semaphore | None = None`. If None, one is created with size `Config.llm_max_concurrency` (default 5).
- The semaphore is **per-instance**, not per-call. All calls through one `LLMClassifier` share it.
- For batched calls (`Classifier.classify_batch`), `asyncio.TaskGroup` spawns N coroutines; the semaphore in the inner classifier serializes them.
- M11.5's `classify_recording` worker job constructs one `Classifier` per job invocation (built in `WorkerSettings.on_startup`), so the semaphore caps concurrency *per worker process*. Across W workers, total = `W × llm_max_concurrency`.

### Retry policy

`ExponentialBackoffRetry(max_attempts=3, base_delay=1.0, jitter=0.5)`:
- Attempt 1 immediate.
- Attempt 2 after `1.0 ± jitter` seconds.
- Attempt 3 after `2.0 ± jitter` seconds.
- Final failure: re-raises.

Retryable exceptions: `anthropic.RateLimitError`, `anthropic.APIStatusError` (5xx only), `asyncio.TimeoutError`. Non-retryable (raise immediately): `anthropic.APIStatusError` (4xx), `LLMBudgetExceeded`.

The Anthropic SDK has its own internal retries; **disable them** (`max_retries=0`) in the `AnthropicBackend` constructor so our policy is the only retry layer. Otherwise: SDK retries 2× × our retries 3× = up to 6 attempts, latency unbounded, rate-limit cascades.

### Cost tracking

- `MODEL_RATES = {"claude-sonnet-4-6": (3.0e-6, 15.0e-6), ...}` — `(input_per_token, output_per_token)` USD.
- `compute_cost(model, in_tok, out_tok) -> float` — multiplies through. Unknown model → 0.0 with a warning.
- `BudgetGuard.check_or_raise()` reads the day's total via `await redis.get("spend:llm:YYYY-MM-DD")`; raises `LLMBudgetExceeded` if above `Config.llm_daily_budget_usd`.
- `BudgetGuard.record_spend(usd)` calls `await redis.incrbyfloat("spend:llm:YYYY-MM-DD", usd)` and `await redis.expire(key, 90 * 86400)`.
- Without Redis: in-memory dict per-process. **Not** distributed — log this clearly so a dev doesn't think they've spent more than they have.

### Adding a new backend (worked example: OpenAI)

1. Create `backends/openai.py` with `class OpenAIBackend` implementing `LLMBackend`. Map OpenAI's `chat.completions.create` to the `complete(messages, ...)` signature; convert response to `LLMResponse`.
2. Add a factory branch in `default_classifier(... backend_name="openai")` to construct it from config.
3. Add `tests/test_llm_openai_backend.py` mocking the OpenAI SDK.

Zero edits to `LLMClassifier`, prompts, parsers, retry, cache, merge.

### Adding a new prompt strategy (worked example: chain-of-thought)

1. Create `prompts/classify_cot.py` with `class ClassifyCotPrompt(PromptStrategy)`. Set `name="classify_cot"`, `version="1"`. Implement `build(action, surrounding)` returning the CoT-shaped messages.
2. Wire as alternative in `default_classifier(... prompt_name="classify_cot")` based on a config flag.
3. Add `tests/test_llm_prompts.py::test_classify_cot_*`.

The cache key includes `prompt.version`, so swapping prompts naturally invalidates entries.

### Adding a new merge strategy (worked example: weighted)

1. Create `merge.py::WeightedMerge(weight_heuristic=0.4, weight_llm=0.6)` implementing `MergeStrategy.merge`.
2. Use it: `Classifier(heuristic=..., llm=..., merge=WeightedMerge(...))`.

No `LLMClassifier` changes.

## Medallion / worker integration

| Layer | Effect |
|---|---|
| Bronze | every LLM call writes `data/bronze/llm/<call-id>.json` (full prompt + response) via `BronzeWriter.write_llm_call(...)`; pointer registered in `bronze_artifacts` |
| Silver | every LLM call inserts a `LLMCallRow` (M5 schema, already present) with token counts, latency, computed cost |
| Cold gold | M11.5's `recompute_llm_costs_daily(...)` reads `LLMCallRow` to build `gold_llm_costs_daily.parquet`; `recompute_classifier_accuracy(...)` joins on `RecordedActionRow.classification_reasoning` (parses the `[<source>]` prefix) to break out heuristic-vs-LLM accuracy |
| Worker | M11.5's `classify_recording` job constructs one `Classifier` (hybrid) and iterates over a recording's actions via `classify_batch` |
| FastAPI | M12 enqueues `classify_recording` jobs; live progress via Redis pub/sub same as `replay_run` |

## Integration points

| Touch | File | How |
|---|---|---|
| M2 → M9 | [src/rpa_recorder/models/actions.py](../src/rpa_recorder/models/actions.py) | reads `RecordedAction`; writes nothing |
| M5 → M9 | [src/rpa_recorder/storage/db.py](../src/rpa_recorder/storage/db.py) | `LLMCallRow` already defined; M9 writes to it |
| M6.5 → M9 | `medallion/bronze.py` | `BronzeWriter.write_llm_call` consumed by `LLMClassifier` persistence step |
| M7 → M9 | `classifier/heuristic/__init__.py` | `Classifier` composes `HeuristicEngine` |
| M9 → M8 | `cli/commands/classify.py` | switches from `default_pipeline()` to `default_classifier()` |
| M9 → M10 | recovery's `LLMReselectStrategy` reuses `LLMBackend` directly with a different `PromptStrategy` |
| M9 → M11.5 | `classify_recording` job uses `Classifier.classify_batch`; `gold_llm_costs_daily.parquet` reads from `LLMCallRow` |

## Models / DB rows used

- **Reads:** `RecordedAction` (M2).
- **Writes:** `LLMCallRow` (silver, already in M5 schema), `BronzeArtifactRow` (M6.5), files under `data/bronze/llm/`.
- **In-memory:** `Classification`, `ClassifyCandidate` from M7's protocol — reused, not duplicated.

## Tests

`tests/test_llm_protocol.py`:
- `test_llm_response_round_trips_via_pydantic` — validates `LLMResponse` model_dump/model_validate.
- `test_classify_candidate_imported_from_m7_not_redefined` — sanity: M7's `ClassifyCandidate` is reused.

`tests/test_llm_anthropic_backend.py`:
- `test_complete_returns_llm_response_with_tokens(mock_anthropic)` — mock returns fixture; assert `LLMResponse.input_tokens` matches.
- `test_complete_disables_sdk_retries(mock_anthropic)` — assert constructor passes `max_retries=0` to the Anthropic client.
- `test_complete_translates_rate_limit(mock_anthropic)` — mock raises `RateLimitError`; method propagates so retry policy can catch.
- `test_complete_with_tools_passes_tools(mock_anthropic)` — assert tools array forwarded to the SDK.
- `test_complete_respects_timeout(mock_anthropic)` — pass `timeout_s=1`; SDK call should receive timeout.

`tests/test_llm_prompts.py`:
- `test_classify_v1_builds_user_message_with_action_context` — assert built messages include selector, payload (redacted), element_context, surrounding action types.
- `test_classify_v1_redacts_sensitive_payloads` — input with `is_sensitive=True` does not appear in the message text.
- `test_classify_v1_signature_excludes_timestamps` — same action with different timestamps yields the same signature.
- `test_classify_v1_signature_includes_surrounding_count` — different surrounding lengths → different signatures.

`tests/test_llm_parsers.py`:
- `test_tool_use_parser_extracts_intent` — fixture response with one `classify(intent="login", confidence=0.9, reasoning="...")` tool call; parser returns matching candidate.
- `test_tool_use_parser_returns_none_on_no_tool_call`.
- `test_json_mode_parser_handles_malformed_json` — broken JSON; parser returns None and logs.
- `test_free_form_parser_regex_fallback` — text contains `INTENT: login`; parser extracts.

`tests/test_llm_retry.py`:
- `test_exponential_backoff_retries_on_rate_limit` — fn raises `RateLimitError` twice then succeeds; observed delays ~1 s, ~2 s.
- `test_no_retry_passes_through` — `NoRetry` raises immediately.
- `test_retry_re_raises_after_max_attempts` — fn always fails; raises last exception.
- `test_retry_does_not_retry_non_retryable` — `LLMBudgetExceeded` skips retry, raises immediately.

`tests/test_llm_cache.py`:
- `test_in_memory_cache_round_trip`.
- `test_in_memory_cache_respects_ttl` — set with TTL=1, advance time by 2, get returns None.
- `test_redis_cache_round_trip(redis_fake)` — set/get via fake Redis client.
- `test_cache_key_changes_with_prompt_version` — same action, different prompt versions → different keys.

`tests/test_llm_cost.py`:
- `test_compute_cost_for_known_model` — sonnet rates × token counts → expected USD.
- `test_compute_cost_unknown_model_returns_zero_with_warning(caplog)`.
- `test_budget_guard_blocks_after_threshold` — set spend at 0.99 of budget; next call raises `LLMBudgetExceeded`.
- `test_budget_guard_in_memory_is_per_process(caplog)` — assert a warning is logged once per process when running without Redis.

`tests/test_llm_concurrency.py`:
- `test_semaphore_caps_parallel_calls` — semaphore size 2; spawn 5 concurrent classify calls; observe at most 2 in-flight at any instant.
- `test_semaphore_per_instance_not_global` — two `LLMClassifier` instances each with size 2 → 4 in-flight max combined.

`tests/test_llm_merge.py`:
- `test_highest_confidence_picks_winner` — heuristic 0.5 vs LLM 0.9 → LLM wins.
- `test_voting_merge_resolves_ties_by_priority` — equal confidence → predetermined winner.
- `test_weighted_merge_blends_confidences` — heuristic 0.6 with weight 0.4, LLM 0.8 with weight 0.6 → final 0.72.

`tests/test_llm_classifier.py`:
- `test_classify_cache_hit_skips_backend(mock_backend, in_memory_cache)`.
- `test_classify_writes_llm_call_row(mock_backend, mock_session)`.
- `test_classify_writes_bronze_blob(mock_backend, mock_bronze)`.
- `test_classify_returns_none_on_parse_failure_but_still_writes_audit(mock_backend)` — parser returns None; classifier returns None; row + bronze still written.
- `test_classify_respects_budget_guard` — budget exceeded → raises before backend call; no row written.
- `test_classify_persists_via_taskgroup_partial_failure(mock_bronze_failing)` — bronze raises; silver still written; classify still returns candidate.

`tests/test_llm_hybrid.py`:
- `test_hybrid_skips_llm_when_heuristic_confident` — heuristic returns 0.9 (above threshold 0.7); LLM not called.
- `test_hybrid_calls_llm_when_heuristic_uncertain` — heuristic returns 0.3; LLM called; merge returns the LLM verdict.
- `test_hybrid_classify_batch_uses_taskgroup` — submit 10 actions; assert all classified concurrently bounded by semaphore.
- `test_hybrid_classify_batch_isolates_per_action_failures` — one mocked failure; other 9 still classify.
- `test_hybrid_threshold_configurable` — threshold=0.95 forces LLM even on heuristic 0.9.

Real-API tests gated behind `@pytest.mark.llm` and skipped unless `RPA_RUN_LLM_TESTS=1`. CI runs `pytest -m "not llm"`.

Coverage target: **≥90%** on the `classifier/llm/` package.

## Known pitfalls

- **Anthropic SDK retries vs our retry.** Disable SDK retries (`max_retries=0`) so our `RetryPolicy` is the only layer. Otherwise nested retries multiply attempts and saturate rate limits unexpectedly.
- **Token counting.** Use the response's `usage.input_tokens` / `output_tokens` — *don't* estimate locally. Cost computation assumes API-reported counts.
- **Tool use vs JSON mode.** Prefer tool use (`ToolUseParser`) for newer Sonnet models; structured output is more reliable. JSON Mode parser is the documented fallback path.
- **Cache key sensitivity.** `signature()` must exclude timestamps, UUIDs, and `RunResult` linkage — they're volatile. Test: same action with different `timestamp` → same signature → cache hit.
- **Cache cross-version invalidation.** Bumping `prompt.version` naturally invalidates entries via the key. Don't write a manual flush.
- **Budget guard distributed semantics.** The per-day Redis counter is shared across workers; the in-memory fallback is per-process and logs a warning once at startup. M11.5 should always use Redis in production.
- **`asyncio.Semaphore` event-loop binding.** A `Semaphore` is bound to its event loop. Construct one per `LLMClassifier` instance, never module-global, since each worker process / FastAPI process has its own loop. Sharing across loops crashes with `RuntimeError: ... attached to a different loop`.
- **`asyncio.TaskGroup` and partial failures in `classify_batch`.** If one action's classification raises, the TaskGroup cancels siblings *and* re-raises an `ExceptionGroup`. Wrap each task body in try/except to convert per-action failures to `Classification(intent=UNKNOWN, ...)` so one bad action doesn't abort the batch — heuristic verdicts still hold.
- **`asyncio.TaskGroup` in persistence step.** Three tasks (bronze write, silver insert, cache set) run in parallel. Each must catch its own exceptions internally; otherwise an `ExceptionGroup` propagates and the classifier appears to fail even though the model call succeeded.
- **Streaming vs non-streaming.** Classification uses non-streaming. M10's recovery may use streaming for live UI feedback; that's a different `LLMBackend.stream_complete` method introduced in M10.
- **PII / sensitive payloads.** `ClassifyV1Prompt` redacts payloads with `is_sensitive=True` *before* building the message. This is the trust boundary — never let a password reach the API. Tests assert this; CI fails if regression slips in.
- **`LLMResponse.raw` size.** The full SDK response can be tens of KB (especially with tool use). Bronze writes go through `BronzeStore.put` which is async; don't block on it inside the cache-set TaskGroup task.
- **PEP 758 except syntax.** Python 3.14 allows parens-less `except A, B:`. Style choice.

## Commit

`feat(classifier): add modular LLM tier with pluggable backends, prompts, parsers, retry, cache, merge`

Body: introduces the `classifier/llm/` package with five swappable concerns (`LLMBackend`, `PromptStrategy`, `ResponseParser`, `RetryPolicy`, `MergeStrategy`) plus orthogonal ones (`ResponseCache`, semaphore-based concurrency control, cost tracking with `BudgetGuard`). Default wiring uses Anthropic + classify_v1 + tool-use + exponential backoff + Redis cache + highest-confidence merge. The hybrid `Classifier` composes M7's `HeuristicEngine` with the LLM tier — heuristic first, LLM only when confidence < threshold. Every LLM call writes a bronze JSON blob, a silver `LLMCallRow`, and a cache entry, persisted via `asyncio.TaskGroup` so one failure doesn't poison the others. M11.5's `classify_recording` job consumes `Classifier.classify_batch` end-to-end with structured concurrency.

## Critical files

- `src/rpa_recorder/classifier/llm/protocol.py`
- `src/rpa_recorder/classifier/llm/classifier.py` and `hybrid.py`
- `src/rpa_recorder/classifier/llm/{backends,prompts,parsers}/__init__.py` — registries
- `src/rpa_recorder/classifier/llm/{retry,cache,cost,concurrency,merge}.py`
- `tests/test_llm_*.py`
