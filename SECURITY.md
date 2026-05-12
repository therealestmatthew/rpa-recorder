# Security Policy

`rpa-recorder` is a single-operator portfolio tool, not a multi-tenant
service. The notes below describe the trust model that informs the code
and how to report security issues.

## Reporting a vulnerability

Email **mjmule623@gmail.com** with details of the issue. I aim to
acknowledge within 7 days and target a 90-day disclosure window for
coordinated fixes. Please don't open public GitHub issues for security
findings.

If you'd prefer encrypted email, request a PGP key in your initial
message.

## Trust boundaries

- **Bronze tier is operator-private.** The bronze layer
  (`data/bronze/...`) preserves raw capture artifacts byte-for-byte —
  including any `is_sensitive=True` payloads (typed credentials, OTP
  codes, personal data). It is intentionally not redacted, because raw
  fidelity is what makes failed-replay debugging tractable. Treat the
  bronze directory like any other on-disk credential cache: don't share
  it, don't sync it, don't ship it.
- **Silver and gold tiers redact sensitive payloads.** Validated rows
  in [`storage/`](src/rpa_recorder/storage/) and analytics shapes in
  [`medallion/`](src/rpa_recorder/medallion/) replace `is_sensitive=True`
  values with placeholders. CLI rendering
  ([`cli/output/`](src/rpa_recorder/cli/output/)) and FastAPI responses
  ([`api/`](src/rpa_recorder/api/)) consume the redacted shape.
- **LLM prompts redact sensitive payloads.** The LLM tier
  ([`classifier/llm/prompts/base.py`](src/rpa_recorder/classifier/llm/prompts/base.py))
  enforces redaction before any prompt leaves the process — this is an
  invariant, not a convention. The recovery
  [`llm_reselect`](src/rpa_recorder/recovery/strategies/llm_reselect.py)
  strategy obeys the same rule.

## Secret handling

- **Anthropic API key** is read from the `ANTHROPIC_API_KEY` environment
  variable (the SDK's default) and stored as `pydantic.SecretStr`. It
  is never logged, never persisted, and never sent to any host other
  than `api.anthropic.com`.
- **Postgres / Redis URLs** are read from `RPA_DATABASE_URL` and
  `RPA_REDIS_URL`. They may contain inline credentials; treat the
  environment / `.env` file as secret material.
- **No `.env` file is committed.** A `.env.example` documents the
  variables; populating real values is the operator's responsibility.

## Threat model exclusions

The following are **explicitly out of scope** for this project. Filing
an issue against them is not a vulnerability:

- **Multi-tenant isolation.** This is a single-operator tool. There is
  no row-level access control, no per-user authentication on the FastAPI
  control plane, no tenant scoping in storage. If you deploy it
  multi-tenant, that is your problem to solve.
- **Defenses against malicious recorded sites.** The operator chooses
  which sites to record. A site that injects malicious JavaScript into
  its own page can corrupt the bronze artifacts for that recording.
  Replay of corrupt recordings stays sandboxed in Playwright but the
  operator is the trust boundary, not the framework.
- **Authenticated replay without manual storage state.** Authenticated
  targets require the operator to provide a `storage_state` JSON
  ([`browser/session.py`](src/rpa_recorder/browser/session.py)). The
  framework will not attempt automated login flows.
- **Browser sandbox escapes.** Inherited from upstream Playwright /
  Chromium; report to the upstream project, not here.
