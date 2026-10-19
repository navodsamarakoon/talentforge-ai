# TalentForge AI

TalentForge AI combines the existing candidate-evaluation and retrieval code with a local assessment platform for Python-based Software Engineer and Software Engineering Intern interviews. Recruiters create and publish assessments, issue one-use invitations, review persisted submissions and execution results, and compare candidates. Candidates receive only visible sample cases and their own attempt.

The platform does not make hiring decisions. AI evaluation is optional and is separate from authoritative sandbox test results.

## Architecture

- `app/` is the existing AI foundation. It is retained and its `AIEvaluator`, hybrid retriever, GraphRAG retriever, and LangSmith tracing are reused when enabled.
- `backend/talentforge/` is a FastAPI service with SQLAlchemy models, signed expiring JWTs, Argon2 password hashing, organization-scoped recruiter access, invitations, attempts, submissions, reports, and audit events.
- `backend/migrations/` contains the Alembic migration environment. Schema creation is performed by explicit migration commands; the service does not create or drop the platform schema at startup.
- `frontend/` is a React, TypeScript, Vite application with recruiter and candidate screens and Monaco Editor.
- `docker-compose.yml` runs PostgreSQL, the API, and the frontend. PostgreSQL data uses a named persistent volume.

Candidate Python is never executed by the host Python interpreter. Each run uses a fresh Docker container with networking disabled, a read-only root filesystem, an unprivileged user, resource limits, a temporary filesystem, no mounted repository, and bounded output. Docker is not required to start the API, but it is required to run code; if unavailable, submissions are retained and execution is explicitly marked unavailable.

## Prerequisites

- Python 3.12 or newer and pip.
- Node.js 22.12 or newer and npm.
- PostgreSQL 16 (local development) or Docker Compose.
- Docker Engine/Desktop with permission to start isolated Linux containers for candidate execution.
- Optional: Ollama with the configured model for AI reports.
- Optional: existing ChromaDB and Neo4j services for retrieval context.

## Configuration

The repository already contains a local `.env`. **Do not replace that file.** Merge the required settings from `.env.example` into it, replacing the placeholders locally. Do not commit `.env`.

Generate independent values for `JWT_SECRET` and `POSTGRES_PASSWORD`. A URI-safe hexadecimal value works for both the PostgreSQL environment variable and connection URL. In PowerShell, run this command twice and use a different result each time:

```powershell
[Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
```

Use one value for `JWT_SECRET` and the other for `POSTGRES_PASSWORD`. Never use the example placeholders outside local setup.

The Docker Compose backend needs `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, and `JWT_SECRET`. `DATABASE_URL` in `.env.example` is for running the API directly on the host; Compose builds its in-network connection from the PostgreSQL variables.

### Sandbox Docker access

The API backend does not mount the Docker socket and does not include the Docker CLI. It sends run requests to a dedicated, non-root `sandbox-runner` on a private Compose network. Only that service mounts `/var/run/docker.sock`; it has no database connection, API secrets, host project mounts, or published port. The runner starts candidate code in a separate container with no network, a read-only root filesystem, no capabilities, no-new-privileges, a non-root user, and CPU, memory, PID, time, and output limits.

The runner's Docker socket access is still highly privileged: anyone able to control the runner process can control the Docker daemon and potentially the host. Keep the runner private, do not expose its port or socket to candidate containers, and use it only on a trusted development host. Do not use `chmod 666`, a privileged runner container, or run the API as root.

Set `DOCKER_GID` to the numeric group ID of the mounted socket; it is granted only to the runner's unprivileged UID. In PowerShell, derive the actual group ID, then build and recreate both services:

```powershell
$env:DOCKER_GID = (docker run --rm -v /var/run/docker.sock:/var/run/docker.sock python:3.12-alpine stat -c '%g' /var/run/docker.sock).Trim()
docker compose build --no-cache backend sandbox-runner
docker compose up -d --force-recreate backend sandbox-runner
docker compose exec backend sh -c "id; test ! -S /var/run/docker.sock && ! command -v docker"
docker compose exec sandbox-runner sh -c "id; command -v docker; docker version"
```

The backend check confirms that the API has neither the socket nor Docker CLI; the runner check confirms that the runner can reach the daemon. On Docker Desktop/Windows, the socket GID may be `0`; on Linux use the actual socket group rather than assuming that value. A supplementary GID of `0` expands the runner's access to root-group-readable files inside its own container, so the runner image intentionally receives no application secrets or database configuration.

Docker container startup can take up to 30 seconds; `SANDBOX_TIMEOUT_SECONDS` still limits candidate-code execution after the sandbox runner starts it. If the runner is unavailable or the socket cannot be accessed, execution fails closed with `sandbox_unavailable`; there is no host-Python fallback. Running the API directly on the host requires a separately reachable runner configured with `SANDBOX_RUNNER_URL`.

If you do not want the API to access a Docker daemon, omit the socket mount. API startup and non-execution endpoints remain available, while code runs return a clear `sandbox_unavailable` response. There is no host-Python fallback.

## Run locally on Windows

1. Ensure PostgreSQL is running and configure its local URL in `.env`:

   ```text
   DATABASE_URL=postgresql+psycopg://<user>:<password>@localhost:5432/talentforge
   ```

2. Install backend dependencies using your project environment:

   ```powershell
   .\venv\Scripts\python.exe -m pip install -r backend\requirements.txt
   ```

3. Apply schema migrations:

   ```powershell
   $env:PYTHONPATH = "$PWD\backend;$PWD"
   .\venv\Scripts\python.exe -m alembic -c backend\alembic.ini upgrade head
   ```

4. Start the API in one terminal:

   ```powershell
   $env:PYTHONPATH = "$PWD\backend;$PWD"
   .\venv\Scripts\python.exe -m uvicorn talentforge.main:app --app-dir backend --reload
   ```

   The API health endpoint is `http://localhost:8000/api/health`.

5. Install and run the frontend in another terminal:

   ```powershell
   Set-Location frontend
   npm ci
   npm run dev
   ```

   Open `http://localhost:5173`. The Vite app calls `http://localhost:8000/api` by default.

To stop the application, stop the API and Vite terminal processes. Migrations do not drop existing database data.

## Run with Docker Compose

After adding the required local values to `.env`:

```powershell
docker compose up --build
```

Open `http://localhost:8080`. Compose applies Alembic migrations before starting the API. The database is persisted in the `postgres-data` named volume. Avoid `docker compose down -v` if you need to keep that database.

For optional local Ollama evaluation, set `AI_ENABLED=true`, set `OLLAMA_HOST` to an address reachable from the backend container (usually `http://host.docker.internal:11434`), configure `OLLAMA_MODEL`, and pull that model in Ollama. The backend image includes the AI client dependencies. Retrieval context is separately opt-in with `RETRIEVAL_ENABLED=true` and `INSTALL_RETRIEVAL_DEPS=true`; the backend can then use the existing ChromaDB database and GraphRAG requires reachable Neo4j environment settings. ChromaDB may be updated by its existing `get_or_create_collection` behavior; candidate containers never mount it. LangSmith tracing follows the existing project's LangSmith environment configuration. None of these optional services is required for core account, assessment, invitation, submission-persistence, or reporting workflows.

## Migrations

Run from the repository root with `PYTHONPATH` containing both the backend and root folders:

```powershell
$env:PYTHONPATH = "$PWD\backend;$PWD"
.\venv\Scripts\python.exe -m alembic -c backend\alembic.ini upgrade head
```

Migration status:

```powershell
.\venv\Scripts\python.exe -m alembic -c backend\alembic.ini current
```

The initial migration creates only the platform's tables. It does not touch the existing `evaluations/`, `chroma_db/`, or knowledge-base files.

## Development-only seed

Once migrated and the API dependencies are installed, create a sample draft assessment without overwriting existing AI evaluation data:

```powershell
$env:PYTHONPATH = "$PWD\backend;$PWD"
.\venv\Scripts\python.exe -m talentforge.seed
```

Register a recruiter through the UI first. This creates a Software Engineer Python draft with visible and hidden cases only if the database contains no assessment, owned by the first recruiter in the database. It does not create users or hardcoded credentials.

## Tests and build

Backend unit/workflow tests use an isolated in-memory SQLite database and a fake sandbox; they do not require Docker, PostgreSQL, Ollama, Neo4j, ChromaDB, or LangSmith:

```powershell
$env:PYTHONPATH = "$PWD\backend;$PWD"
.\venv\Scripts\python.exe -m pytest backend\tests -q
```

Frontend authentication workflow test and production TypeScript build:

```powershell
Set-Location frontend
npm ci
npm test
npm run build
```

Existing AI foundation test scripts are distinct from these platform tests. Some existing scripts call external services or `app.main`, which writes sample evaluation files. Do not run those scripts as part of platform validation unless you have reviewed their effects and explicitly intend them. The platform neither reads nor overwrites those sample evaluation JSON files.

## Security and known limits

- Use TLS, a production secret manager, secure cookie/token storage, rate limiting, email delivery, and deployment-specific security controls before production use. The local UI stores its bearer token in browser local storage.
- Invitations are stored as SHA-256 token hashes, bound to normalized email addresses, expire, can be revoked, and are single-use. The generated raw URL is shown once to the recruiter; no email provider is configured.
- Recruiter data access is scoped to the recruiter's organization. Candidates see only assessments they accepted and their own attempts/submissions.
- Recruiters can archive assessments with candidate history using `POST /api/assessments/{assessment_id}/archive` and restore them with `POST /api/assessments/{assessment_id}/unarchive`. The default recruiter assessment list contains active assessments; `GET /api/assessments?archived=true` returns archived assessments. Archiving changes only the assessment state, preserves invitations and historical records, and blocks new invitations and attempts while allowing already-started attempts to continue. Permanent deletion remains blocked when invitations or attempts exist.
- Hidden test inputs/expected values are never serialized by candidate endpoints. Expected values stay in the database and are compared by trusted API code with returned values; container output never supplies a pass/fail flag.
- AI evaluation and retrieval are disabled by default. AI output is schema-validated; test outcomes remain server-generated and are not replaced by model claims. AI/retrieval failures do not discard submitted source or execution results.
- The sandbox has standard Docker isolation and limits, but is not a substitute for a dedicated hardened execution service, mandatory access-control profiles, kernel isolation, resource monitoring, and threat-model review in production.
- Candidate isolation still depends on Docker and the host kernel; it is not a substitute for a hardened multi-tenant execution service or stronger kernel isolation. Compromise of the runner itself is effectively host compromise because of its Docker socket access.
- The existing AI integrations depend on external Ollama/Neo4j/ChromaDB/LangSmith availability and credentials. Their live behavior is not claimed as verified by the deterministic platform tests.
