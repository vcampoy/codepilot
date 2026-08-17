FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --system codepilot \
    && adduser --system --ingroup codepilot codepilot

RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src

RUN pip install --no-cache-dir ".[llm,github]"

FROM base AS api

USER codepilot

EXPOSE 8000

CMD ["uvicorn", "codepilot.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS worker

RUN apt-get update \
    && apt-get install --no-install-recommends -y nodejs npm \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir ".[analysis]"

COPY analyzer-runtime/package.json analyzer-runtime/package-lock.json /opt/codepilot/analyzer-runtime/
RUN npm ci --prefix /opt/codepilot/analyzer-runtime --omit=dev --ignore-scripts \
    && ln -s /opt/codepilot/analyzer-runtime/node_modules/.bin/eslint /usr/local/bin/eslint
COPY analyzer-runtime/eslint.config.mjs /opt/codepilot/analyzer-runtime/eslint.config.mjs

USER codepilot

EXPOSE 8000

FROM api AS default
