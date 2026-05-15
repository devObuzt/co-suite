# co-Suite

AI-powered marketing suite SaaS platform.

## Stack

- **Frontend:** Next.js 15 (App Router) + shadcn/ui + Tailwind
- **Backend:** Python FastAPI + SQLAlchemy (async) + PostgreSQL
- **Engine:** AI content generation (Claude + Gemini image/video)
- **Payments:** Morning (local), expandable

## Quick Start

### 1. Start infrastructure

```bash
docker compose up -d
```

### 2. Start API

```bash
cd api
cp .env.example .env   # fill in your keys
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 3. Start frontend

```bash
cd web
npm install
npm run dev
```

Open http://localhost:3000

## Project structure

```
oneshare/
├── api/                 # FastAPI backend
│   ├── core/            # DB, auth, config
│   ├── models/          # SQLAlchemy models
│   ├── routers/         # API endpoints
│   ├── services/        # Business logic
│   └── engine/          # AI content engine (from connec-content-engine)
├── web/                 # Next.js frontend
│   └── src/app/
│       ├── (auth)/      # login, signup
│       ├── (dashboard)/ # main app
│       └── suite/       # suite pages
├── docs/                # prompts, diagrams
└── docker-compose.yml
```

## Pricing

| Plan | Price |
|------|-------|
| Solo | $14.99/user/month |
| Team (2-24 users) | $11.99/user/month |
| Enterprise (25+) | $7.99/user/month |

**Credits:** API costs × 3 billed as negative credits. Auto-freeze at -$10.
