FROM python:3.12-slim AS backend

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace/backend:/workspace

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app

WORKDIR /workspace
COPY backend/requirements.txt /tmp/requirements.txt
COPY backend/requirements-ai.txt /tmp/requirements-ai.txt
COPY backend/requirements-retrieval.txt /tmp/requirements-retrieval.txt
ARG INSTALL_RETRIEVAL_DEPS=false
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements-ai.txt \
    && if [ "$INSTALL_RETRIEVAL_DEPS" = "true" ]; then pip install --no-cache-dir -r /tmp/requirements-retrieval.txt; fi
COPY backend/ /workspace/backend/
COPY app/ /workspace/app/
COPY knowledge_base/ /workspace/knowledge_base/
USER 10001:10001
EXPOSE 8000
CMD ["sh", "-c", "python -m alembic -c backend/alembic.ini upgrade head && python -m uvicorn talentforge.main:app --host 0.0.0.0 --port 8000 --app-dir backend"]

FROM python:3.12-slim AS sandbox-runner
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace/backend:/workspace
RUN apt-get update \
    && apt-get install -y --no-install-recommends docker-cli \
    && rm -rf /var/lib/apt/lists/* \
    && command -v docker \
    && docker --version \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app
WORKDIR /workspace
COPY backend/requirements.txt /tmp/backend-requirements.txt
RUN pip install --no-cache-dir -r /tmp/backend-requirements.txt
COPY backend/talentforge/__init__.py backend/talentforge/config.py backend/talentforge/sandbox.py backend/talentforge/sandbox_service.py /workspace/backend/talentforge/
USER 10001:10001
EXPOSE 8001
CMD ["python", "-m", "uvicorn", "talentforge.sandbox_service:app", "--host", "0.0.0.0", "--port", "8001", "--app-dir", "backend", "--limit-concurrency", "16"]
