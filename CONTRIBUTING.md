# Contributing to CodePilot

## Local setup

1. Start PostgreSQL and Redis with `docker compose up --build`.
2. Install backend development dependencies: `cd backend && python -m pip install -e ".[dev]"`.
3. Install frontend dependencies: `cd frontend && npm ci`.

Run backend checks from `backend/`:

```bash
ruff check .
ruff format --check .
mypy
pytest
```

Run frontend checks from `frontend/`:

```bash
npm test
npm run build
```

Use test doubles for GitHub and LLM providers. Tests must not call paid providers or mutate external repositories. Keep deterministic evidence as the source of truth and add a focused test before changing behavior.

## Change boundaries

- Keep external calls behind their adapter boundary.
- Do not log credentials, installation tokens, webhook secrets, or repository contents.
- Preserve the ordered prompt scope and use a conventional commit message.
- Update the relevant architecture or security documentation when a boundary changes.
