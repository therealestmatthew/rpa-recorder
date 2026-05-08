# GitHub Workflow Checklist

Configuration checklist for optimizing the `rpa-recorder` team workflow on GitHub.
Check off items as they are completed. Sections marked *(already done)* require
no action — they exist for reference.

---

## What are Pre/Post Tool Run Hooks?

Claude Code hooks are shell scripts that run automatically at specific lifecycle
events during a Claude session. No user intervention is needed — they fire silently
in the background. This project already uses two:

| Hook event | Trigger | This project's hook | Effect |
|---|---|---|---|
| **PostToolUse** | After every Edit / Write / MultiEdit tool call | `.claude/hooks/python-autofmt.cmd` | Runs `ruff format` + `ruff check --fix` silently on the whole repo after any file is saved |
| **Stop** | When Claude is about to end its turn (declare done) | `.claude/hooks/check-stop.cmd` | Runs `ruff check` → `mypy` → `pytest`; exits code 2 to **block** Claude from stopping if anything fails, forcing fixes first |

There are four hook events in total:

- **`PreToolUse`** — fires *before* a tool runs; exit 2 blocks the tool call entirely
- **`PostToolUse`** — fires *after* a tool runs; exit 2 blocks Claude from continuing
- **`Stop`** — fires when Claude tries to end its turn; exit 2 blocks the stop
- **`Notification`** — fires when Claude sends a notification (informational; cannot block)

Hooks receive a JSON payload on stdin describing the event (tool name, file path,
arguments, etc.). They live in `.claude/hooks/` and are registered in
`.claude/settings.json` (project-level) or `~/.claude/settings.json` (user-level).

**Important:** hooks are local — they run on each developer's machine during Claude
sessions. They do **not** run in GitHub Actions CI. The CI pipeline (§3) is the
production enforcement layer.

Potential future additions for this project:

- A `PostToolUse` hook that runs `actionlint` whenever a `.github/workflows/*.yml`
  file is written, catching YAML errors before commit.
- A `PreToolUse` hook on Edit/Write to log which symbols were touched, feeding into
  a `gitnexus_detect_changes()` pre-commit reminder.

---

## 1 — Repository Settings (GitHub UI)

*Settings → General*

- [ ] **Default branch** set to `main`
- [ ] **Merge strategies** — disable "Allow merge commits" and "Allow rebase merging";
      enable "Allow squash merging" only (linear history, readable blame)
- [ ] **Auto-delete head branches** — enabled (removes feature branches after PR merge)
- [ ] **Wikis** — disabled (docs live in `docs/`; separate wiki creates drift)
- [ ] **Issues** — enabled; templates added (see §7)
- [ ] **Projects** — enable if using GitHub Projects for milestone tracking

---

## 2 — Branch Protection Rules (`main`)

*Settings → Branches → Add rule for `main`*

- [ ] **Require a pull request before merging** (no direct pushes to `main`)
- [ ] **Require approvals** — minimum **1** reviewer
- [ ] **Dismiss stale pull request approvals when new commits are pushed**
- [ ] **Require review from Code Owners** (once `.github/CODEOWNERS` is created — see §7)
- [ ] **Require status checks to pass before merging** — add all of:
  - `lint`
  - `typecheck`
  - `unit (ubuntu-latest)`
  - `unit (macos-latest)`
  - `integration`
  - `worker`
  - `coverage`
- [ ] **Require branches to be up to date before merging**
- [ ] **Do not allow bypassing the above settings** (applies to admins too)

*Note: status check names above become available in the dropdown only after CI has run
at least once. Implement §3 first, then come back and add the checks.*

---

## 3 — CI/CD Pipeline (M13 — not yet implemented)

Full spec: [`docs/m13-github-actions-ci.md`](m13-github-actions-ci.md)

### Workflow files

- [ ] `.github/workflows/ci.yml` — 6-job pipeline:
  `lint` ‖ `typecheck` → `unit` (ubuntu + macos matrix) → `integration` ‖ `worker` → `coverage`
- [ ] `.github/workflows/llm-tests.yml` — weekly schedule (Mondays 09:00 UTC),
      gated by `ANTHROPIC_API_KEY` secret; never runs in daily CI
- [ ] `.github/workflows/README.md` — workflow conventions, secret setup,
      marker meanings, `act` local-replication instructions

### Composite actions (DRY building blocks)

- [ ] `.github/actions/setup-environment/action.yml` — checkout + uv + cache + `uv sync --frozen`
- [ ] `.github/actions/setup-browser/action.yml` — Playwright Chromium install with system deps

### Supporting config

- [ ] `.github/codecov.yml` — coverage targets (80% project, 75% patch);
      ignores `tests/`, `src/rpa_recorder/page_scripts/**/*.js`, `src/rpa_recorder/__main__.py`
- [ ] `.github/dependabot.yml` — weekly updates for `github-actions` and `pip` ecosystems

### Job dependency graph

```
┌─────────┐   ┌───────────┐
│  lint   │   │ typecheck │   ← parallel, ~30 s each
└────┬────┘   └─────┬─────┘
     └────────┬─────┘
              ▼
         ┌────────┐
         │  unit  │ (ubuntu-latest + macos-latest matrix)
         └────┬───┘
              │
       ┌──────┴──────┐
       ▼             ▼
┌──────────┐  ┌────────┐
│integration│  │ worker │   ← parallel; worker needs Redis service
└─────┬─────┘  └────┬───┘
      └──────┬──────┘
             ▼
         ┌────────┐
         │coverage│   ← aggregates XMLs from all three test jobs → Codecov
         └────────┘
```

---

## 4 — Secrets and Variables

*Settings → Secrets and Variables → Actions*

- [ ] `ANTHROPIC_API_KEY` — repository secret; powers `llm-tests.yml`;
      absent = LLM workflow silently skipped (not a CI failure)
- [ ] `CODECOV_TOKEN` — repository secret; for coverage upload to Codecov;
      absent on forks = non-fatal (`fail_ci_if_error: false` in workflow)

---

## 5 — Pre-commit Hooks *(`.pre-commit-config.yaml` already configured)*

Every team member must install locally after cloning:

```bash
uv add --dev pre-commit   # if not already in dev deps
uv run pre-commit install
```

Current hooks (all active):

- [x] `ruff` — lint + auto-fix
- [x] `ruff-format` — formatting
- [x] `mypy` — strict type check on `src/`
- [x] `trailing-whitespace`
- [x] `end-of-file-fixer`
- [x] `check-yaml`
- [x] `check-added-large-files`
- [x] `check-merge-conflict`

Recommended addition:

- [ ] **`actionlint`** — lint GitHub Actions YAML files before commit; catches
      syntax errors, undefined secrets, and invalid step references. Add to
      `.pre-commit-config.yaml`:
  ```yaml
  - repo: https://github.com/rhysd/actionlint
    rev: v1.7.3
    hooks:
      - id: actionlint
  ```

---

## 6 — Claude Code Hooks *(`.claude/hooks/` already implemented)*

Hooks are local — each developer gets them automatically from the repo.
They do not run in CI.

- [x] **PostToolUse** — `python-autofmt.cmd` — auto-formats Python after every file edit
- [x] **Stop** — `check-stop.cmd` — blocks Claude from finishing until ruff + mypy + pytest pass

Remaining items:

- [ ] **Verify hook registration** — confirm both hooks are listed in
      `.claude/settings.json` under the correct event keys; team members should
      not need to configure anything manually after cloning
- [ ] **Document hooks** in contributor onboarding docs so the team understands
      why Claude re-runs checks automatically and how to interpret exit-2 blocks

---

## 7 — Pull Request and Issue Templates (`.github/`)

- [ ] `.github/PULL_REQUEST_TEMPLATE.md` — standard checklist for every PR:
  - Tests added / updated
  - Types checked (`mypy` passes)
  - Docs updated if public API changed
  - No `Co-Authored-By: Claude` in commits (per working agreement)
  - `gitnexus_detect_changes()` run before commit

- [ ] `.github/ISSUE_TEMPLATE/bug_report.md` — fields:
      reproduction steps, expected vs actual behavior, Python version, OS

- [ ] `.github/ISSUE_TEMPLATE/feature_request.md` — fields:
      milestone alignment, motivation, acceptance criteria

- [ ] `.github/CODEOWNERS` — maps directory paths to required reviewers:
  ```
  # example — adjust to actual team
  src/rpa_recorder/recovery/   @team-lead
  src/rpa_recorder/browser/    @team-lead
  .github/                     @team-lead
  ```

---

## 8 — Code Quality Integrations

- [ ] **Codecov** — sign into [codecov.io](https://codecov.io) with GitHub OAuth;
      add the `rpa-recorder` repo; copy the upload token into `CODECOV_TOKEN` secret (§4);
      CI badge goes in `README.md` (covered by M14)
- [ ] **actionlint** — add to pre-commit (§5); no separate service needed
- [x] **Ruff** — runs in CI (`lint` job); no separate integration needed
- [x] **mypy** — runs in CI (`typecheck` job); no separate integration needed

---

## 9 — Security

*Settings → Security*

- [ ] **`SECURITY.md`** — responsible disclosure policy: who to contact, response SLA,
      supported versions
- [ ] **Private vulnerability reporting** — enable in Settings → Security → Private
      vulnerability reporting (lets researchers report without opening a public issue)
- [ ] **Dependabot security alerts** — enable in Settings → Security → Dependabot
      (separate from the version-update Dependabot in `dependabot.yml`)
- [ ] **Secret scanning** — enable in Settings → Security → Secret scanning
      (catches accidentally committed API keys, tokens, credentials)
- [ ] **Code scanning / CodeQL** — optional; recommended before the repo goes public;
      enable in Settings → Security → Code scanning → Set up CodeQL

---

## 10 — GitHub Environments (optional — for FastAPI deployment gating)

*Settings → Environments*

Only relevant once the FastAPI control plane (`uv run rpa serve`) is deployed.

- [ ] **`staging`** environment — required reviewer gate; environment-scoped secrets
      (e.g., staging `ANTHROPIC_API_KEY`, `DATABASE_URL`)
- [ ] **`production`** environment — stricter reviewer gate; deployment protection rules;
      production secrets isolated from CI

---

## 11 — Team Onboarding Checklist (per contributor)

Run these steps once after cloning the repo:

- [ ] `uv sync` — install all dependencies from `uv.lock`
- [ ] `uv run playwright install` — download Chromium browser binary
- [ ] `uv run pre-commit install` — wire git pre-commit hook
- [ ] Verify Claude Code hooks fire: edit any `.py` file in Claude and confirm
      auto-format runs silently
- [ ] Add `ANTHROPIC_API_KEY=sk-ant-...` to `.env` for local LLM classifier work
- [ ] Read `CLAUDE.md` — working agreements, GitNexus impact-analysis rules,
      hook behavior, commit attribution rules

---

## Implementation order

Recommended sequence to avoid blocking the team:

1. **§3** — implement M13 CI pipeline (creates the status check names for §2)
2. **§4** — add `ANTHROPIC_API_KEY` and `CODECOV_TOKEN` secrets
3. **§2** — add branch protection rules (now that check names exist)
4. **§8** — connect Codecov
5. **§7** — add PR/issue templates and CODEOWNERS
6. **§5** — add `actionlint` to pre-commit
7. **§1** — finalize repo settings (squash-only, auto-delete branches)
8. **§9** — enable security features
9. **§11** — share onboarding checklist with team
