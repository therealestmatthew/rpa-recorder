# M8 — CLI commands (modular Typer package)

**Status:** pending

**Source:** [.claude/plans/bootstrap.md](../.claude/plans/bootstrap.md) §CLI Specification; [build-plan.md](build-plan.md) for upstream/downstream context.

## Goal

Wire the storage layer (M5) and browser layer (M3 + M4 + M6 + M6.5) into a Typer-driven CLI so the project is end-to-end usable from the shell. The CLI is structured as a package with one command per file, reusable building blocks (async runner, output renderers, parameter parsers, shared console), and explicit registration — so M11 (`confirm`), M11.5 (`worker`, `medallion *`), and any future commands drop in by adding a file and a single registration line, with no edits to existing commands.

## Files

### Create

- `src/rpa_recorder/cli/__init__.py` — re-exports `app: typer.Typer` so `rpa = "rpa_recorder.cli:app"` in `pyproject.toml` continues to work
- `src/rpa_recorder/cli/app.py` — constructs the root Typer app; imports each command module to register it
- `src/rpa_recorder/cli/console.py` — shared `rich.console.Console` instance with the project's theme
- `src/rpa_recorder/cli/async_runner.py` — `run_async(coro)` wrapper with KeyboardInterrupt handling
- `src/rpa_recorder/cli/params.py` — custom Typer parameter parsers (e.g., `--param key=value` → `dict[str, str]`)
- `src/rpa_recorder/cli/errors.py` — `CLIError` + a click/typer error handler that renders nicely via `rich`
- `src/rpa_recorder/cli/dependencies.py` — factory functions: `make_engine()`, `make_session_factory()`, `make_bronze_writer()`, `make_anthropic_client()`. Each command pulls what it needs.
- `src/rpa_recorder/cli/output/__init__.py`
- `src/rpa_recorder/cli/output/recording.py` — `render_recording_summary(rec)`, `render_recording_detail(rec, *, redact=True)`
- `src/rpa_recorder/cli/output/run.py` — `render_run_result(rr)`, `render_run_progress(event)`
- `src/rpa_recorder/cli/commands/__init__.py` — barrel imports so `app.py` only does `from .commands import *` indirectly
- `src/rpa_recorder/cli/commands/record.py` — `rpa record`
- `src/rpa_recorder/cli/commands/list_recordings.py` — `rpa list`
- `src/rpa_recorder/cli/commands/show.py` — `rpa show`
- `src/rpa_recorder/cli/commands/classify.py` — `rpa classify`
- `src/rpa_recorder/cli/commands/replay.py` — `rpa replay`
- `src/rpa_recorder/cli/commands/serve.py` — `rpa serve`
- `tests/test_cli_async_runner.py`
- `tests/test_cli_params.py`
- `tests/test_cli_output.py`
- `tests/test_cli_record.py` (`@pytest.mark.integration`)
- `tests/test_cli_list_show.py`
- `tests/test_cli_classify.py`
- `tests/test_cli_replay.py`
- `tests/test_cli_serve.py`

### Modify

- `src/rpa_recorder/cli.py` — **convert to a package.** Either delete the file and rely on `cli/__init__.py`, or leave it as a thin re-export `from rpa_recorder.cli.app import app` for back-compat. Recommend **delete**: the package is the new home, no callers besides `pyproject.toml`'s console-script entry depend on the module path.
- `pyproject.toml` — no change to `rpa = "rpa_recorder.cli:app"` (the entry point resolves to the package's `__init__.app`)

## Public API

### `cli/app.py`

```python
import typer
from .commands import record, list_recordings, show, classify, replay, serve

app = typer.Typer(
    name="rpa",
    help="Browser-RPA recorder, classifier, and replayer.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Each commands module registers itself by attaching to `app`. The imports above
# trigger registration via module-level `app.command()(...)` calls.
```

### `cli/__init__.py`

```python
from .app import app

__all__ = ["app"]
```

### `cli/async_runner.py`

```python
P = ParamSpec("P")
T = TypeVar("T")

def run_async(coro_fn: Callable[P, Awaitable[T]]) -> Callable[P, T]:
    """Decorate an async function so Typer can call it directly.

    Wraps `asyncio.run(coro_fn(*args, **kwargs))` with KeyboardInterrupt
    translated to a clean `CLIError("interrupted")` so commands can catch
    it and run any teardown (e.g., `recorder.stop()`).
    """
```

### `cli/params.py`

```python
def parse_key_value(raw: str) -> tuple[str, str]:
    """`'name=alice'` → `('name', 'alice')`. Raises `BadParameter` on bad input."""

def collect_params(values: list[str]) -> dict[str, str]:
    """Aggregate repeated `--param key=value` into a dict."""
```

### `cli/errors.py`

```python
class CLIError(Exception):
    """Raised by command bodies to render a styled error and exit non-zero."""
    def __init__(self, message: str, *, exit_code: int = 1) -> None: ...
```

### Per-command module shape

Each command file has the same shape. Example (`commands/record.py`):

```python
import typer
from rpa_recorder.cli.app import app
from rpa_recorder.cli.async_runner import run_async
from rpa_recorder.cli.console import console
from rpa_recorder.cli.dependencies import make_session_factory, make_bronze_writer
# ...

@app.command(name="record")
def record(
    name: str = typer.Argument(..., help="Recording name."),
    url: str = typer.Option(..., "--url", help="Starting URL."),
    headless: bool = typer.Option(False, "--headless"),
) -> None:
    """Open a browser, record interactively, save on Ctrl+C."""
    run_async(_record_async)(name=name, url=url, headless=headless)


async def _record_async(*, name: str, url: str, headless: bool) -> None:
    session_factory = make_session_factory()
    bronze = await make_bronze_writer()
    async with BrowserSession(headless=headless) as session:
        recorder = Recorder(session.page, name=name, starting_url=url, bronze=bronze)
        await recorder.start()
        try:
            await session.page.goto(url)
            console.print("[dim]Recording. Press Ctrl+C to stop.[/dim]")
            await asyncio.Event().wait()
        finally:
            await recorder.stop()
            recording = recorder.get_recording()
            recording = run_heuristic(recording)   # default_pipeline() from M7
            async with session_factory() as db:
                await RecordingRepository(db).save(recording)
            console.print(f"[green]Saved {recording.id}[/green]")
```

This shape is the contract for every command. Async commands wrap their `_<name>_async` body via `run_async`. Sync commands omit the wrapper.

## Behavior

### Pipeline architecture, summary

The CLI package has three concentric rings:

1. **`app.py`** — the Typer app object; just registration + help text.
2. **Reusable utilities** (`async_runner`, `console`, `params`, `errors`, `dependencies`, `output/`) — used by every command.
3. **Command modules** under `commands/` — one file per command, each calling into reusable utilities + the project layers (M3–M6, M5 storage, M7 classifier, M6.5 bronze).

Adding a new command never touches any existing command file. Reusable utilities only change when a *cross-cutting* concern changes (e.g., we change how all commands render run results).

### Command catalog (M8 ships)

| Command | Module | Async? | Notes |
|---|---|---|---|
| `rpa record <name> --url <url> [--headless]` | `commands/record.py` | yes | Opens `BrowserSession`, attaches `Recorder` (with `BronzeWriter` from M6.5), runs heuristic on each captured action, persists via `RecordingRepository` on Ctrl+C |
| `rpa list` | `commands/list_recordings.py` | yes | `RecordingRepository.list()` rendered via `output/recording.py:render_recording_summary` (`rich.table.Table`) |
| `rpa show <id>` | `commands/show.py` | yes | Pretty-print recording with intent labels and confidence; `output/recording.py:render_recording_detail(rec, redact=True)` masks `is_sensitive=True` payload values |
| `rpa classify <id>` | `commands/classify.py` | yes | Re-run M7 heuristic (`default_pipeline()`) across recording's actions; updates rows. M9 enhances this command to add the LLM tier when confidence < threshold |
| `rpa replay <id> [--param k=v]... [--headless]` | `commands/replay.py` | yes | Load recording, build `Executor`, render run result via `output/run.py:render_run_result`. M11.5 adds `--queue` flag |
| `rpa serve [--port 8000]` | `commands/serve.py` | no | `uvicorn.run("rpa_recorder.api.routes:app", ...)`. The api package is fleshed out in M12 |

### Reusable utilities

#### `async_runner.run_async`

- `run_async(coro_fn)` returns a sync wrapper. Inside, it calls `asyncio.run(coro_fn(*args, **kwargs))`.
- Catches `KeyboardInterrupt` and `asyncio.CancelledError`, translates both to `CLIError("interrupted", exit_code=130)` so commands' `try/finally` can run teardown.
- This means commands can write `try: ...wait... finally: await recorder.stop()` and trust that Ctrl+C runs the finally branch.

#### `console.console`

- Single `Console` instance shared across all commands so styling/theme stay consistent.
- Theme defines color slots: `success`, `warning`, `error`, `dim`, `accent`, `highlight`.
- `console.print(...)` is the only way commands emit user-visible text.

#### `params.parse_key_value` and `params.collect_params`

- Used by `replay` for `--param key=value` repetition.
- `parse_key_value` handles edge cases: missing `=` raises `BadParameter`, value can contain `=`, leading/trailing whitespace stripped.
- `collect_params` rejects duplicate keys (would shadow silently).

#### `errors.CLIError`

- Caught by a typer error handler registered on `app` that prints via `console` with `error` styling and exits with `exit_code`.
- Keeps command bodies from littering `try/except SystemExit` patterns.

#### `dependencies.*`

- Per-command dependency factories. Each command calls only the factories it needs.
- `make_engine()` / `make_session_factory()` are cached at module level (one engine per process).
- `make_bronze_writer()` is async because it constructs the `LocalFilesystemStore` (M6.5) and warms a session.
- `make_anthropic_client()` reads the API key from `Config` (lazy — only called by commands that need LLM access; M9 + M10).

### Output renderers

- `output/recording.py:render_recording_summary(recordings)` — tabular: ID, name, created_at, action count, last classified.
- `output/recording.py:render_recording_detail(rec, *, redact=True)` — per-action breakdown with intent + confidence + reasoning. Sensitive payloads masked.
- `output/run.py:render_run_result(rr)` — status, duration, per-action result with attempts, recovery summary.
- `output/run.py:render_run_progress(event)` — single line per WebSocket / pub-sub event for live runs (used by M12's `--follow`).

Each renderer takes plain Pydantic models and returns a `rich.renderable.RenderableType`. Tests assert renderable shape independently of console width.

### Adding a new command (worked example: `rpa export <id> --format json|csv`)

1. Create `src/rpa_recorder/cli/commands/export.py` following the per-command-module shape.
2. Add `from . import export` to `commands/__init__.py` so it gets imported (and thereby registered).
3. Add `tests/test_cli_export.py` with a `CliRunner`-driven scenario.

No edits to other commands. No changes to `app.py` (since `commands/__init__.py` is the registration site). The same pattern is used by M11 (`confirm.py`) and M11.5 (`worker.py`, `medallion/*.py`).

### Subcommand groups (M11.5 will use)

For commands that share a namespace — `rpa medallion promote/compact/status/prune` — the convention is a sub-Typer:

```python
# commands/medallion/__init__.py (added in M11.5)
import typer
from rpa_recorder.cli.app import app

medallion_app = typer.Typer(name="medallion", help="Bronze/silver/gold operations.")
app.add_typer(medallion_app, name="medallion")

from . import promote, compact, status, prune   # registers each on medallion_app
```

`commands/medallion/promote.py` then does `@medallion_app.command(...)` instead of `@app.command(...)`. M8 documents this pattern in `commands/__init__.py` so M11.5 follows it.

## Medallion / worker integration

| Touchpoint | Effect |
|---|---|
| `rpa record` | passes a `BronzeWriter` (from `dependencies.make_bronze_writer()`) into `Recorder`, so raw envelopes land in `data/bronze/recordings/<id>/raw_events.jsonl` per M6.5 |
| `rpa replay` | uses `Executor`'s M6.5-aware failure capture path; screenshots/DOM/a11y land in bronze with pointer rows |
| `rpa classify` | currently invokes only the M7 heuristic; M9 extends to the LLM tier (which writes bronze LLM blobs via `BronzeWriter.write_llm_call`) |
| `rpa serve` | unchanged surface — the FastAPI app it boots gets the workers integration in M12 |
| New commands in M11 / M11.5 | follow the per-command-module shape; no architecture changes needed |

M8 itself does **not** ship `rpa worker` or `rpa medallion *` — those are M11.5's scope. M8's job is to make sure the architecture is ready for them to drop in.

## Integration points

| Touch | File | How |
|---|---|---|
| M3 → M8 | [src/rpa_recorder/browser/session.py](../src/rpa_recorder/browser/session.py) | `record` and `replay` open `BrowserSession` |
| M4 → M8 | [src/rpa_recorder/browser/recorder.py](../src/rpa_recorder/browser/recorder.py) | `record` instantiates `Recorder` |
| M5 → M8 | [src/rpa_recorder/storage/repositories.py](../src/rpa_recorder/storage/repositories.py) | every command uses repositories via `dependencies.make_session_factory()` |
| M6 → M8 | [src/rpa_recorder/browser/executor.py](../src/rpa_recorder/browser/executor.py) | `replay` builds `Executor` |
| M6.5 → M8 | `medallion/bronze.py` | `record`/`replay` route artifacts via `BronzeWriter` |
| M7 → M8 | `classifier/heuristic/__init__.py` | `record` (post-stop) and `classify` invoke `default_pipeline()` |
| M8 → M9 | `commands/classify.py` extended to call hybrid `Classifier` |
| M8 → M11 | `commands/confirm.py` added; same per-command shape |
| M8 → M11.5 | `commands/worker.py` + `commands/medallion/*.py` added; uses sub-Typer pattern |
| M8 → M12 | `commands/serve.py` boots the FastAPI app |

## Models / DB rows used

- **Reads:** `Recording`, `RecordedAction`, `RunResult`, `ActionExecution` (all M2 models via M5 repositories).
- **Writes:** `RecordedActionRow` (intent fields updated by `classify`); `RunResultRow` (created by `replay`); `BronzeArtifactRow` (indirectly via `BronzeWriter` in `record`/`replay`).
- **Sensitive handling:** `render_recording_detail(rec, redact=True)` calls `rec.model_dump(context={"redact_secrets": True})` — relies on M2 Pydantic context support.

## Tests

`tests/test_cli_async_runner.py`:

- `test_run_async_returns_value` — async function returning 42 → wrapper returns 42.
- `test_run_async_translates_keyboard_interrupt(monkeypatch)` — coro raises `KeyboardInterrupt`; wrapper raises `CLIError("interrupted", exit_code=130)`.
- `test_run_async_runs_finally_block` — coro has `try/finally`; finally branch executes before the wrapper returns/raises.

`tests/test_cli_params.py`:

- `test_parse_key_value_basic` — `"name=alice"` → `("name", "alice")`.
- `test_parse_key_value_value_contains_equals` — `"x=a=b"` → `("x", "a=b")`.
- `test_parse_key_value_missing_equals_raises_bad_parameter`.
- `test_collect_params_aggregates` — `["a=1", "b=2"]` → `{"a": "1", "b": "2"}`.
- `test_collect_params_rejects_duplicate_keys` — `["a=1", "a=2"]` raises.

`tests/test_cli_output.py`:

- `test_render_recording_summary_includes_action_count` — render to a `rich.console.Console` with `record=True`; capture output; assert columns and row count match.
- `test_render_recording_detail_redacts_sensitive_inputs` — recording with `is_sensitive=True` input; rendered output contains `***` not the actual value.
- `test_render_run_result_classifies_failure_modes` — fixture `RunResult` with mixed success/failed/recovered actions; rendered table has the right rows.

`tests/test_cli_list_show.py` (no real browser):

- `test_list_with_seeded_db` — seed two recordings via repository; `runner.invoke(app, ["list"])` exits 0 and output contains both names.
- `test_show_existing_recording` — `runner.invoke(app, ["show", str(rec.id)])` exits 0 and rendered text matches expected per-action lines.
- `test_show_unknown_id_exits_nonzero` — bad UUID → exit code 1, stderr contains `Recording not found`.

`tests/test_cli_classify.py`:

- `test_classify_updates_intent_fields` — seed a recording with one INPUT on a password field; run `classify`; row's `semantic_intent == LOGIN`, `confidence == 0.95`.
- `test_classify_idempotent` — running twice yields same DB state.

`tests/test_cli_replay.py`:

- `test_replay_with_monkeypatched_executor` — patch `Executor.run` to return a fixture `RunResult`; `runner.invoke(app, ["replay", str(rec.id)])` exits 0 and renders the result.
- `test_replay_with_param_substitution` — `--param email=a@b.com`; assert the patched executor received the param dict.

`tests/test_cli_serve.py`:

- `test_serve_invokes_uvicorn_run(monkeypatch)` — patch `uvicorn.run`; `runner.invoke(app, ["serve", "--port", "9000"])` calls it with the right args.

`tests/test_cli_record.py` (`@pytest.mark.integration`):

- `test_record_against_fixture_url` — `runner.invoke(app, ["record", "demo", "--url", FIXTURE_URL, "--headless"], input="\x03")` (Ctrl+C as input). Asserts a recording is saved with at least 1 action and the bronze JSONL exists.
- `test_record_writes_to_bronze` — same, then asserts `data/bronze/recordings/<id>/raw_events.jsonl` exists with line count >= captured action count.

Coverage target: **≥85%** on the `cli/` package.

## Known pitfalls

- **Typer + async.** Typer commands are sync by default. The `run_async` decorator pattern is the cleanest path; avoid `@app.command()(asyncio.run(...))` lambda gymnastics. Keep async bodies in `_<name>_async` so they can be unit-tested independently of Typer.
- **Single shared `Console`.** `rich.Console` is not thread-safe, but our CLI is single-threaded asyncio per command. Don't construct ad-hoc `Console()` instances inside commands — always import the shared one. Tests use `Console(record=True)` to capture output.
- **`KeyboardInterrupt` during `BrowserSession.__aexit__`.** When the user hits Ctrl+C mid-record, asyncio cancels the current task; the `BrowserSession` async context manager runs its teardown in a cancellation-aware way. Don't catch CancelledError inside the command body — let it propagate to the `try/finally` so the recorder.stop() runs cleanly.
- **`commands/__init__.py` import order matters.** Each command module has a `@app.command()` decorator at module load time. The order in `__init__.py` determines the order in `--help` output. Convention: the order in the help should mirror the M8 command catalog table above. Document this at the top of `commands/__init__.py`.
- **`cli.py` vs `cli/` package.** `pyproject.toml` has `rpa = "rpa_recorder.cli:app"`. After deletion of `cli.py`, the entry point resolves to `rpa_recorder.cli` (the package), then attribute `app`. That's `cli/__init__.py:app` — works as long as we re-export. Run `uv pip install -e .` to refresh the entry point after the rename.
- **Subcommand-group future-proofing.** Don't put the `medallion` sub-Typer in M8 — that would force importing M11.5 modules from M8. Instead, document the sub-Typer pattern at the bottom of `commands/__init__.py` and let M11.5 add the `medallion/` subdirectory and registration.
- **CliRunner in tests vs real-process behavior.** `typer.testing.CliRunner` runs commands in-process, which means `asyncio.run` inside a command body can collide with pytest-asyncio's event loop. Use `runner.invoke(app, ..., catch_exceptions=False)` and ensure `pytest-asyncio` is set to `mode=auto` (already in `pyproject.toml`). For commands that genuinely need a separate process (rare), use `subprocess.run([sys.executable, "-m", "rpa_recorder", ...])`.
- **PEP 758 `except` syntax.** Same note as M6.5/M7 — Python 3.14 allows parens-less `except A, B:`. Style choice.

## Commit

`feat(cli): add modular Typer package with record / list / show / classify / replay / serve commands`

Body: introduces the `cli/` package with one file per command, reusable building blocks (`async_runner`, `console`, `params`, `errors`, `dependencies`, `output/`), and explicit registration so future commands (M11 `confirm`, M11.5 `worker` and `medallion *`) drop in without touching existing files. Six commands ship in this milestone — `record`, `list`, `show`, `classify`, `replay`, `serve` — using the M3–M6.5 layers and the M7 modular heuristic engine. The single-file `cli.py` from the M1 scaffold is replaced by the package.

## Critical files

- `src/rpa_recorder/cli/app.py` — the Typer root + registration site
- `src/rpa_recorder/cli/async_runner.py`, `console.py`, `params.py`, `errors.py`, `dependencies.py` — reusable building blocks
- `src/rpa_recorder/cli/output/{recording,run}.py` — renderers
- `src/rpa_recorder/cli/commands/{record,list_recordings,show,classify,replay,serve}.py` — the six commands
- `tests/test_cli_*.py`
