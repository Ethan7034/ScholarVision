[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Redis](https://img.shields.io/badge/Cache-Redis_B5312C?style=flat-square&logo=redis&logoColor=white)](https://redis.io/)
[![VLM](https://img.shields.io/badge/VLM-Intern--S2-FF6F00?style=flat-square)]()
[![arXiv](https://img.shields.io/badge/Data_Source-arXiv-B31B1B?style=flat-square&logo=arxiv&logoColor=white)](https://arxiv.org/)

# 🏛️ Scholar Vision v2.0

**An Agentic Multimodal Academic Pipeline.**

Upload an academic PDF → PyMuPDF extracts embedded charts → a Vision-Language Model
analyzes every chart concurrently → structured Markdown insights, served through a
session-guarded FastAPI gateway with Redis-backed caching and a standalone worker.

> ## 📐 Architecture honesty note
> Earlier drafts described an aspirational 8-tier microservices stack (LangChain,
> RabbitMQ, PostgreSQL/MongoDB, WAF…). This README documents **what the code actually
> does today**, with a separate "Roadmap" for the rest.

## 🏗️ System Architecture (as implemented)

| Layer | Module | What actually runs |
|---|---|---|
| 1. Presentation | `frontend/index.html`, `frontend/dashboard.html` | Single-page Web UI (Tailwind, inlined script) + protected history page |
| 2. Gateway / Security | `app/core/gateway.py`, `app/core/security.py` | ASGI middleware: unauthenticated page requests → **302** back to `/?auth=required&next=…`; API requests → **401 JSON**. JWT in **httpOnly** cookie, server-side revocation list on logout |
| 3. Business Logic | `app/main.py`, `app/routers/*` | FastAPI + full asyncio path (`httpx.AsyncClient`); no blocking calls on the event loop |
| 4. Orchestration | `app/services/agent.py` | Deterministic plan: parse → fan-out per chart (bounded concurrency) → aggregate Markdown |
| 5. AI Processing | `app/pipelines/llm_client.py` | Intern-S2 VLM for charts, semaphore-limited (`MAX_CONCURRENT_ANALYSIS`) |
| 6. Parsing | `app/pipelines/parser.py` | PyMuPDF in a worker thread; xref dedup; 0-byte image guard; per-job output isolation |
| 7. Data & Cache | `app/core/store.py`, `app/models/database.py` | **Redis**: analysis/search cache + job state + token revocation + **reliable job queue** (auto-degrades to in-process memory if Redis is absent); **SQLite** via SQLAlchemy |
| 8. Deployment | `Dockerfile`, `docker-compose.yml`, `worker.py`, `start_server.bat`, `connection_guardian.py` | Three compose services (api / redis / worker); local: cloudflared tunnel + watchdog; **worker runs analyses in its own process** |

## ⚙️ v2.1: the standalone worker (dual-mode execution)

`POST /api/analyze` no longer executes inside the API process when Redis is up:

```
API process                        worker process (python worker.py)
──────────                         ─────────────────────────────────
auth → md5 → cache hit? ──yes──►  instant 202, 0 model calls
        └─ miss ─► LPUSH sv:queue:analyze ──► BRPOPLPUSH → execute
                   (job stays "queued")        (running → progress → completed)
                                               result → Redis cache + paper_history
                                               LREM ack only on normal finish
```

Reliability semantics (BRPOPLPUSH pattern):
- Pop moves the payload into `sv:queue:processing`; it is acked (LREM) only when the
  job finishes normally (including business-level failures, whose reasons are stored
  in the job record). A crash mid-analysis leaves the payload in `processing`.
- On startup the worker runs `reclaim_processing()`, moving stranded payloads back to
  the main queue. Analyses are idempotent — a re-run costs a little API quota, nothing else.
- `WORKER_CONCURRENCY` (default 2) bounds how many PDFs one worker handles at once;
  a semaphore is acquired **before** popping, so popped jobs never sit unpersisted in
  process memory.

Fallback (the reason your box needs no Redis to develop): if Redis is unreachable,
`submit_analysis_task` runs the job in-process (v2.0 behavior) and `worker.py`
exits with a clear message + non-zero code. `GET /api/health` reports which mode
is live: `queue.enabled` / `queue.pending`.

## 🚀 Quickstart

### Option A — local, no Redis required
```bash
pip install -r requirements.txt
cp .env.example .env         # fill INTERN_API_KEY, SECRET_KEY
python -m uvicorn app.main:app --reload --port 8000
```

### Option B — local, with Redis queue + worker
```bash
docker compose up -d redis   # or any reachable redis://
python -m uvicorn app.main:app --port 8000
python worker.py             # separate window; CTRL+C drains gracefully
```

### Option C — full stack via Docker
```bash
docker compose up --build    # api :8000 + redis + worker, shared volumes for uploads/ & images/
```

### Option D — your daily Windows setup
```bash
start_server.bat   # port-scoped cleanup → API window → (if :6379 alive) worker window
                   # → cloudflared tunnel → connection_guardian watchdog
start_worker.bat   # (re)start just the worker after Redis comes up
```

## 🔌 API Surface

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /auth/register` | public | create account (bcrypt hash) |
| `POST /auth/login` | public | set httpOnly `sv_session` JWT cookie |
| `POST /auth/logout` | session | clear cookie **and** revoke jti |
| `GET /auth/me` | session | whoami (401 → UI pops SYSTEM_AUTH modal) |
| `GET /api/health` | public | liveness + storage backend + queue mode/depth |
| `POST /api/analyze` | session | 202 `{job_id}` — or instant result if md5 cached |
| `GET /api/tasks/{job_id}` | session | queued / running `{done,total}` / completed / failed |
| `GET /api/history` | session | current user's past analyses |
| `GET /api/search?keyword=` | session | arXiv search, 10-min Redis cache |
| `GET /` | public | main SPA |
| `GET /dashboard` | session | history page — **the 302-redirect demo target** |

## ✅ What's verified (pytest 15/15 + live server)

- Session/gateway (v2.0): 302/401 split, tampered-token rejection, full lifecycle
  incl. post-logout server-side revocation, async job progress, cache short-circuit,
  path-traversal-safe uploads
- Live server run: 2.2 MB / 10-page PDF → **3/3 charts analyzed**, real progress,
  identical re-upload served from cache in **0.02 s**; `/api/health` p95 **5 ms**
  during a full analysis (v1.0 would have frozen every user for up to 420 s)
- Queue dual-mode (v2.1): enqueue path leaves job `queued` with no in-process task;
  consumption completes + acks + cleans temp files; push failure falls back to
  in-process execution without a 500; progress persists via the job record (the only
  channel that survives cross-process); BRPOPLPUSH/LREM/RPOPLPUSH command semantics
  exercised against an in-memory Redis-protocol implementation
- Not yet exercised: a long run against a **real** Redis server + worker process
  (this box had no reachable Redis; the compose file is the intended environment)

## 🗺️ Roadmap (documented honestly, not implemented)

- ~~Independent worker processes~~ ✅ shipped in v2.0 (reliable Redis list queue;
  arq/Celery remains an option if you outgrow this)
- Rate limiting / WAF at the gateway edge
- PostgreSQL migration for multi-instance deployments (worker + API need shared
  filesystem today — see compose volumes)
- LangChain-style autonomous planning — orchestration is still a fixed pipeline
- Semantic Scholar ingestion

## 🛠️ Tech Stack
Python 3.10+ · FastAPI · asyncio · httpx · PyMuPDF · Pillow · SQLAlchemy · passlib/bcrypt ·
python-jose · Redis (queue + cache, optional-fallback) · arxiv · Docker · Cloudflare Tunnel

---
*Built by Ethan GU (NOTECH / UNNC CS). Foundation patterns migrated from News-Retriever V2.0.*
