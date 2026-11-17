# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`mk-qa-master` is a Python MCP server (stdio) plus a cross-host agent skill that lets an AI client drive test suites: analyze → generate → run → report → optimize. It is published to PyPI and has been under a **v1.0 stability lock** since 2026-06-02 — the MCP tool surface is a frozen public contract (see "Stability lock" below, it shapes almost every change).

## Commands

There is no linter, formatter, or type checker configured. The only gate is pytest.

```bash
pip install -e .                    # dev install (hatchling; src layout)
pip install -e '.[api]'             # + schemathesis runner
pip install -e '.[edge]'            # + opencv/ultralytics (pulls torch, ~1GB — CI never installs this)

pytest tests/ -v                    # the unit suite (what CI's smoke job runs on py3.10–3.13)
pytest tests/test_qa_plan.py -v     # one file
pytest tests/test_qa_plan.py::test_name -v
pytest tests/test_visual_challenge.py -k hcaptcha -v

mk-qa-master                        # start the MCP stdio server (also: python -m mk_qa_master.server)
mk-qa-master doctor [--json]        # install/env audit; exit 1 only on critical gaps
```

Other suites, not part of `pytest tests/`:

- `pytest tests_project/ -v` — the bundled sample *project under test*; needs `playwright install chromium` and hits live example.com.
- `pytest examples/sample_vulnerable_api/tests/` — OWASP scanner dogfood against the deliberately vulnerable Flask fixture (`pip install -r examples/sample_vulnerable_api/requirements.txt`). `/vuln/*` must trigger every rule, `/safe/*` must produce zero findings.

### Windows caveats (CI is Linux-only)

- Run pytest with `PYTHONUTF8=1`; otherwise tests that `read_text()` without an encoding fail with `UnicodeDecodeError: 'cp950'`.
- Even then, ~21 tests in `tests/test_runner_api_security*.py` fail locally: `load_spec()` in `runners/api_security.py` runs `urlparse` on the spec location, so a bare `C:\...` path is read as URL scheme `c` and `file://C:\...` loses its path to netloc → `spec_load_failed`. Only `file:///C:/...` works. CI is Linux-only, so don't treat these as regressions from an unrelated change. Details: `docs/bug-reports/windows-file-url.md`.

## Architecture

### Request path

`server.py` is the single MCP entry: `_core_tools()` declares every `Tool()` schema inline, and `_dispatch()` is a flat `if name == ...` chain. `call_tool()` wraps dispatch so exceptions become a text result (never a crash) and every call is logged to telemetry. Adding a core tool means touching both `_core_tools()` and `_dispatch()` — `tests/test_smoke.py` checks they stay in parity.

`tools/runner.py`, `tools/reporter.py`, `tools/generator.py` are thin shims: validate input (`security.py`), then delegate to `runners.get_runner()`. Real logic lives in the runner classes and in the standalone tool modules (`analyzer`, `optimizer`, `qa_context`, `qa_plan`, `visual_challenge`, `analyze_stream`).

### Runners

`runners/base.py::TestRunner` is the abstract interface (`list_tests`, `run_tests`, `run_failed`, `get_report_summary`, `get_failure_details`, `generate_test`; optional `codegen`, `get_history`, `get_all_test_details`). One process serves exactly one runner, chosen by `QA_RUNNER` through `runners/__init__.py::REGISTRY` (several aliases map to one class).

- Every runner normalizes its native output into the same pytest-json-report-shaped `PROJECT_ROOT/report.json`. That shared shape is what the HTML reporter, history, `verify_plan` auto-discovery and the optimizer all read — a new runner that skips this breaks the downstream pipeline silently (v1.3.1 was exactly this bug for the edge runner's `get_all_test_details`).
- After each run a runner archives the report into `test-results/history/` and regenerates `optimization-plan.md` (`_archive_report`).
- `generate_test` signatures differ per runner; `tools/generator.py` uses `inspect.signature` to pass `url` / `module` / `business_context` only to runners that declare them. Keep that pattern rather than widening the abstract method.
- Non-Python runners shell out (`npx jest`, `cypress`, `go test`, `maestro`, `newman`, `schemathesis`). Subprocess is always list-argv with `DEFAULT_TIMEOUT_SECONDS` (`QA_TIMEOUT_SECONDS`); timeouts return `exit_code=124`.
- `runners/api_security.py` is *not* a `TestRunner` — it is the engine behind the `run_api_security_scan` tool, walking an OpenAPI spec and dispatching `security_rules.ALL_RULES` (each rule implements the `SecurityRule` Protocol in `security_rules/base.py`).
- The edge runner (`runners/edge_inference.py` + `edge/`) manages mediamtx/ffmpeg, translates `QA_*` config into `EDGE_*` env vars, then invokes pytest on generated tests; `edge/pytest_plugin.py` feeds per-test `edge_metrics` into the report.

### Config

`config.py` reads env **at import time** into module constants (`PROJECT_ROOT`, `RUNNER_NAME`, report paths, consent flags). Everything the server writes — `report.json`, `junit.xml`, `test-results/{history,telemetry}`, `optimization-plan.md`, `qa-knowledge.md` — lands under `QA_PROJECT_ROOT` (default `./tests_project`), i.e. in the *project under test*, not this repo. Tests that need different values must monkeypatch the constant on the importing module, not just the env var. The exception is `EdgeConfig`, deliberately read-on-access properties so `monkeypatch.setenv` works.

### Safety gates (part of the frozen contract)

- `security.py`: `validate_filter` (argument-injection guard for anything reaching subprocess argv) and `validate_filename` (path-traversal guard, confined to `PROJECT_ROOT`). Any new tool arg that becomes argv or a path goes through these.
- Consent-gated tools return structured `{"error": "consent_required", ...}` envelopes *before any side effect*: visual challenge (`QA_VISUAL_CHALLENGE_CONSENT`, optional domain allowlist, hard-stop identity-provider blacklist, per-call `confirm=true`), API security scan (`QA_API_SECURITY_CONSENT` + `QA_API_SECURITY_AUTHORIZED_DOMAINS`; `mass_assignment` excluded from default categories because it mutates state), edge netem (`QA_EDGE_NETEM_ENABLED`, Linux only), edge vendor-host blacklist (`QA_EDGE_ALLOW_VENDOR_HOSTS`).
- Tool errors are returned as `{"error": "<kind>", "hint": ...}` dicts, not raised.

### Plan + verify bookend

`tools/qa_plan.py` implements `qa_plan` / `verify_plan`. Five tools (`run_tests`, `solve_visual_challenge`, `analyze_url`, `auto_generate_tests`, `run_api_security_scan`) accept an optional `plan_id` and, when given, append a `plan_verification` envelope. Omitting `plan_id` must leave the response shape byte-for-byte as before. Per-tool evidence contracts: `docs/prd-v0.10-universal-bookend.md`.

### Plugins (v1.5.0)

`plugins.py` discovers four entry-point groups (`mk_qa_master.runners` / `.tools` / `.knowledge` / `.result_hooks`). Invariants: discovery never raises (errors surface via `get_runner_info`), built-in runner names and core tool names always win, plugin tools are appended *after* the core list. `tests/conftest.py` sets `MK_QA_PLUGINS=0` so locally installed plugins can't perturb the snapshot tests; `tests/test_plugins.py` exercises plugins with hand-built state (`plugins.set_state` / `reset`). Author-facing spec: `docs/PLUGINS.md`.

### QA knowledge layer

`tools/qa_context.py` holds the built-in methodology as large inline Markdown in two languages (`QA_LANG=en` default, `zh-tw`). The EN and zh-TW bodies must keep the same set of sections; plugin knowledge sections are appended after them.

### Skill distribution

`skills/mk-qa-master/` (SKILL.md + `commands/` + `reference/`) is the single source for the agent skill, exposed through `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json`. `tests/test_skill_distribution.py` enforces frontmatter validity and that both manifests' `version` equals `pyproject.toml`.

## Stability lock — rules that CI enforces

The 22 core tools (name + `inputSchema`; descriptions are free to change) are frozen in `tests/snapshots/v1/tool_surface.json`.

- **Any schema change fails `tests/test_v1_schema_snapshot.py`.** To change it intentionally: run the test with `BREAKING_CHANGE_ACK=true` (it rewrites the snapshot) *and* add an entry to `docs/MIGRATION-1.x.md` in the same PR — CI's `ack-check` job fails an acked PR that touches no `docs/MIGRATION-*.md`.
- Within v1.x only additive changes are allowed (new tool, new optional arg, new response field). Removal/rename needs the deprecation cycle in `docs/DEPRECATION-POLICY.md`.
- **Tool-count claims are tested.** `tests/test_v1_doc_sync.py` regex-scans `README.md`, `skills/mk-qa-master/SKILL.md` and `skills/mk-qa-master/reference/*.md` for phrases like "22 tools" / "22 MCP tools" / "22-tool" and fails on any mismatch with the live server; the reference docs must also name every registered tool. `tests/test_smoke.py` hardcodes the count too. Be careful writing "N tools" in those files for any other meaning.
- **Deprecation pairing.** If a tool description contains "deprecat…", `tests/test_v1_deprecation_policy.py` requires a matching `warnings.warn(..., DeprecationWarning)` in `src/`.
- `mcp` is pinned `<2` because the server uses the 1.x `Server.list_tools()` decorator API.

## Release / PR conventions

- Version lives in three places that must match: `pyproject.toml`, `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`. The `pyproject.toml` `description` must stay ≤ 512 chars (PyPI Summary limit).
- Releases: merge → `git tag vX.Y.Z` → `gh release create` → `publish.yml` publishes to PyPI via OIDC and fails if the tag ≠ `pyproject` version. No auto-publish on tag push.
- PR templates in `.github/PULL_REQUEST_TEMPLATE/` (`feat-tool.md`, `feat-runner.md`, `feat-bookend.md`, `release.md`) are checklists of the paperwork each change type needs — read the matching one before starting that kind of change.
- Features ship as numbered PR series against a locked PRD in `docs/prd-*.md`; commit subjects follow `feat(vX.Y.Z): …` / `fix(vX.Y.Z): …` / `release(vX.Y.Z): …`.
- External PRs are auto-closed by `external-pr-policy.yml` (solo-maintained repo).
- `README.zh-TW.md` mirrors `README.md`.

## Stale docs to distrust

- `docs/framework.md` is the original v0.1 design sketch (7 tools, no runner abstraction) — not the current architecture.
- The "Project layout" tree in `README.md` omits most current modules.
- User-facing strings and some error messages are in Traditional Chinese (e.g. `未知的 QA_RUNNER`, `執行錯誤`); tests may assert on them.
