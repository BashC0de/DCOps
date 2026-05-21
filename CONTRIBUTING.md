# Contributing to DCOps Copilot

This is a solo build with public-facing ambitions — discipline now saves a code review later. These conventions are mandatory, not aspirational.

## Branching

- **Trunk-based.** `main` is always green and deployable.
- **Feature branches merge daily.** If a branch lives longer than 24h, it's drifted too far — rebase or split.
- Branch naming: `<type>/<short-slug>` — e.g. `feat/sentinel-xgb-baseline`, `fix/timescale-hypertable-retention`.

## Commits

Conventional commits, lowercase scope:

```
feat(sentinel): add XGBoost baseline trained on Backblaze
fix(ingestion): handle Redfish 503 retries with backoff
docs(architecture): clarify Haiku→Sonnet escalation criteria
refactor(event-bus): collapse pub/sub helpers into one wrapper
chore(deps): bump anthropic to 0.39.0
test(forensic): add fixture for mocked KG queries
```

Allowed types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `build`, `ci`.

One logical change per commit. If you find yourself writing "and also" in a commit message, split it.

## Python

- Format: `make format` runs `ruff` + `black`.
- Lint: `make lint` runs `ruff check` + `mypy --strict`.
- Type hints are mandatory. `Any` requires a `# type: ignore[no-any-return]` (or similar) plus a one-line comment justifying it.
- Pydantic v2 models for every inter-service boundary. No dicts-as-payloads across modules.

## TypeScript

- Next.js dashboard runs in strict mode (`tsconfig.json` already configured).
- Format: `cd apps/dashboard && npm run format` (prettier).
- Lint: `npm run lint` (eslint).
- No `any` without a comment explaining why.

## Pre-commit

Install hooks once:

```bash
pre-commit install
```

Hooks run `ruff --fix`, `black`, `mypy` (Python files only), `prettier`, and a check that no `.env` file is staged.

## Testing

- `make test` runs pytest.
- New code requires tests; new agent contracts require a fixture in `tests/conftest.py`.
- Mark slow tests with `@pytest.mark.slow`. Default CI run excludes them.
- Mock external services aggressively — `fakeredis`, `respx` for HTTP, `pytest-mock` for everything else.

## Project structure rules

- **No cross-app imports.** Agents talk via the Redis event bus, not by importing each other.
- **Shared utilities live in `apps/agents/shared/`.** If two agents need the same helper, it goes there.
- **TODOs are weekly milestones.** Every stub uses `# TODO(week-N): <thing>. See ROADMAP.md.` — this is grep-able and intentional.
- **No magic constants.** Tunables go in `.env.example` with comments.

## Memory discipline

This project targets a 16GB laptop. Before adding a service or raising a limit:

1. Check the existing cap in `docker-compose.yml`.
2. If you must raise it, document the new total in `ARCHITECTURE.md` and confirm `docker compose --profile dev up` still fits in 8GB combined.
3. Heavy ML training runs go in `scripts/`, not in long-running services.

## Documentation

- `README.md` is the front door — update it when capabilities materially change.
- `ARCHITECTURE.md` is the technical contract — update it when the data flow, agent contract, or federation model changes.
- `ROADMAP.md` is the truth about what ships when — strike items as they ship; do not silently delete them.
- `case_study/DRAFT.md` is updated weekly with what shipped and what was learned.

## Definition of done

A change is done when:

1. Code is merged to `main`.
2. Tests pass locally (`make test`).
3. Lints pass locally (`make lint`).
4. The relevant `TODO(week-N)` comment is removed or downgraded.
5. The corresponding ROADMAP item is checked off.
6. If user-visible: a screenshot or short demo gif is added to `case_study/`.
