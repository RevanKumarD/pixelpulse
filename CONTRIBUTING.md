# Contributing to PixelPulse

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev,langgraph,otel]"
```

## Running Tests

```bash
# All tests
pytest

# Lint
python -m ruff check src/

# Visual tests (requires a display or virtual framebuffer)
python tests/visual/run_visual_tests.py
```

## Adding a New Adapter

1. Create `src/pixelpulse/adapters/<framework>.py`
2. Implement `instrument(target) -> None` — patches the framework to emit `pp.*` calls
3. Implement `detach() -> None` — removes patches cleanly
4. Register the adapter in `AdapterRegistry` (`src/pixelpulse/adapters/registry.py`)
5. Add unit tests under `tests/adapters/test_<framework>.py`
6. Add a usage example under `examples/`

Adapters must only use the public `PixelPulse` API (`pp.agent_started`, `pp.agent_thinking`,
`pp.agent_completed`, `pp.artifact_created`, `pp.cost_update`, `pp.run_started`,
`pp.run_completed`). Never import internals from `pixelpulse.bus` or `pixelpulse.protocol`.

## Code Style

- Line length: 100 characters
- Formatter/linter: [ruff](https://docs.astral.sh/ruff/)
- Run `python -m ruff check src/ --fix` before committing

## PR Process

1. Fork the repo and create a branch: `git checkout -b feat/my-feature`
2. Write tests first (TDD) — all new code needs tests
3. Ensure `pytest` passes and `ruff check src/` shows no errors
4. Open a pull request against `main` with a clear description of what and why
5. PRs require all CI checks to pass before merge

## Commit Message Format

```
<type>: <short description>

Types: feat, fix, refactor, docs, test, chore, perf
```
