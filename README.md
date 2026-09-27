# Bodhrik Booking Service
 
A small FastAPI service modeling a service booking and review platform:
providers offer time slots, customers book them, and completed bookings
can be reviewed. Reviews are summarized asynchronously via a Redis-backed
job queue.
 
## Stack
 
FastAPI · PostgreSQL · Redis · SQLAlchemy · Docker Compose
 
## Run it (Docker — recommended)
 
```bash
docker compose up --build
```
 
This starts four containers:
 
| Service    | What it does                                                        |
|------------|----------------------------------------------------------------------|
| `postgres` | The database                                                         |
| `redis`    | Backs the review-summarization job queue                             |
| `api`      | Creates tables, then serves the API on `http://localhost:8000`       |
| `worker`   | Consumes the queue and writes the (stubbed) summary back to Postgres |
 
Interactive API docs (Swagger UI): **http://localhost:8000/docs**
 
To stop everything: `docker compose down` (add `-v` to also wipe the Postgres volume).
 
## Run it locally (no Docker)
 
Requires a local Postgres and Redis already running.
 
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
 
cp .env.example .env   # then edit DATABASE_URL / REDIS_URL if needed
export $(cat .env | xargs)
 
python -m app.init_db          # creates tables
uvicorn app.main:app --reload  # terminal 1: the API
python worker.py                # terminal 2: the summarization worker
```
 
## Creating an admin user
 
`/auth/register` only allows `provider` or `customer` — self-registering
as `admin` is blocked (see `WRITTEN_NOTE.md`). Create one directly instead:
 
```bash
# Docker:
docker compose exec api python -m app.create_admin admin@example.com yourpassword
 
# Local (no Docker):
python -m app.create_admin admin@example.com yourpassword
```
 
## Running the tests
 
```bash
pytest -v
```
 
Tests run against an in-memory SQLite database and a mocked job queue —
no real Postgres or Redis needed. This is why `app/models.py` uses a
cross-dialect `GUID` type instead of Postgres's native UUID column.
 
## Linting
 
```bash
ruff check .
```
 
## Trying the API
 
```bash
# 1. Register a provider and a customer
curl -X POST localhost:8000/auth/register -H "Content-Type: application/json" \
  -d '{"email": "provider@example.com", "password": "password123", "role": "provider"}'
curl -X POST localhost:8000/auth/register -H "Content-Type: application/json" \
  -d '{"email": "customer@example.com", "password": "password123", "role": "customer"}'
 
# 2. Log in as the provider (OAuth2 form body, not JSON)
curl -X POST localhost:8000/auth/login \
  -d "username=provider@example.com&password=password123"
# -> copy the access_token from the response
 
# 3. Create a slot (as the provider, using that token)
curl -X POST localhost:8000/slots -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"start_time": "2026-10-01T10:00:00Z", "end_time": "2026-10-01T11:00:00Z"}'
 
# ...log in as the customer, book the slot, complete it as the provider,
# then review it and hit /reviews/{id}/summarize — see the Swagger UI
# at /docs for the full request/response shape of every endpoint.
```
 
## Project layout
 
```
app/
  database.py      # Postgres connection + session dependency
  models.py         # SQLAlchemy models (schema) + cross-dialect GUID type
  schemas.py        # Pydantic request/response shapes
  security.py       # password hashing
  auth.py           # JWT auth + the RBAC dependency (role + ownership checks)
  redis_client.py   # the review-summarization job queue
  main.py           # all API endpoints
  init_db.py        # creates tables (stand-in for a real migration tool)
  create_admin.py   # CLI to create an admin user (registration blocks role=admin)
worker.py            # consumes the queue, writes the (stub) summary
tests/                # pytest suite, incl. explicit RBAC tests
WRITTEN_NOTE.md        # schema/RBAC/production-gap write-up (300-500 words)
```
 
See `WRITTEN_NOTE.md` for the schema reasoning, how RBAC would extend to a
fourth role or nested organisations, and what's deliberately left out for
a production deployment.
