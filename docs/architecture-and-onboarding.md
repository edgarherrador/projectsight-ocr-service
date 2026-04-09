# ProjectSight OCR Service - Architecture and Onboarding

## 1. Solution Architecture

### 1.1 High-level view

```mermaid
flowchart LR
    U[User / Reviewer] --> UI[Gradio Web App\nweb/app.py]
    UI --> API[FastAPI\napi/main.py]

    API --> PDF[PDF Processor\nutils/pdf_processor.py]
    API --> GEM[Gemini Service\napi/gemini_service.py]
    API --> JUDGE[Quality Judge\napi/judge_service.py]
    API --> DB[(SQLite Cache\ncache/pdf_cache.db)]

    DB --> API
    GEM --> API
    PDF --> API
    JUDGE --> API

    API --> UI
```

### 1.2 Core runtime flow (convert request)

```mermaid
sequenceDiagram
    participant User
    participant Web as Gradio UI
    participant API as FastAPI
    participant DB as SQLite
    participant OCR as Gemini Service
    participant Judge as Judge Service

    User->>Web: Upload PDF + judge_mode
    Web->>API: POST /api/convert

    API->>DB: Check cache by content hash
    alt Cache hit
        DB-->>API: Cached markdown and metadata
        opt judge_mode=force OR auto with low similarity
            API->>Judge: evaluate_metrics(cached metrics)
            Judge-->>API: decision
            API->>DB: Save new metrics snapshot
        end
        API-->>Web: Cached response
    else Cache miss
        API->>OCR: Extract pages + generate markdown + metrics
        OCR-->>API: markdown + page metrics + totals
        API->>Judge: should_run_judge + evaluate_metrics
            Judge-->>API: decision (llm/rules_fallback/skip)
        API->>DB: Save markdown cache
        API->>DB: Save OCR metrics/decision
        API-->>Web: New response
    end

    Web->>API: GET /api/metrics/{pdf_id}
    API->>DB: Load latest metrics snapshot
    DB-->>API: Metrics + decision
    API-->>Web: Actionable quality references

        Web->>API: GET /api/judge/diagnostics/{pdf_id}
        API->>DB: Load latest judge diagnostics
        DB-->>API: decision_json metadata
        API-->>Web: judge_mode/model + diagnostics payload
```

### 1.3 Data layer model

```mermaid
erDiagram
    PDF_CACHE {
        string pdf_id PK
        string file_name
        string content_hash UK
        string markdown_content
        int pages_processed
        datetime timestamp
        bool is_cached
    }

    OCR_METRICS_CACHE {
        int id PK
        string pdf_id
        string file_name
        bool is_cached
        text metrics_json
        text decision_json
        datetime created_at
    }

    PDF_CACHE ||--o{ OCR_METRICS_CACHE : "pdf_id"
```

### 1.4 Key design choices

- Content-based caching using SHA256 avoids duplicate OCR work.
- Metrics are stored as snapshots to keep a quality audit trail over time.
- Judge execution is configurable at policy level and overridable per request (`auto`, `force`, `skip`).
- Judge uses Gemini 3.1 Pro for final decision when available; deterministic rules are used as fallback.
- Human review is guided via page-level references (`review_pages`, `page_review_references`).
- Judge diagnostics are persisted with decisions for traceability in API/UI.

## 2. Onboarding (setup + flow + key endpoints)

## 2.1 Setup

### Prerequisites

- Python 3.10+
- Valid Gemini API key
- Windows PowerShell or equivalent shell

### Install

```bash
git clone <repo-url>
cd projectsight-ocr-service
python -m venv .venv
.\.venv\Scripts\activate
uv pip install -e .
```

### Configure environment

Create `.env` from `.env.example` and set at least:

```ini
GEMINI_API_KEY=your_api_key_here
SYSTEM_PROMPT=./prompts/system_prompt.prompty
GEMINI_MODEL=gemini-3.1-flash-preview
GEMINI_SMALL_DOC_MODEL=gemini-3.1-flash-preview
GEMINI_LARGE_DOC_MODEL=gemini-3.1-flash-lite-preview
GEMINI_LARGE_DOC_PAGE_THRESHOLD=100
MAX_FILE_SIZE_MB=30
DATABASE_PATH=./cache/pdf_cache.db
API_HOST=127.0.0.1
API_PORT=8000
GRADIO_HOST=127.0.0.1
GRADIO_PORT=7860

# Judge controls
JUDGE_MODEL=gemini-3.1-pro-preview
JUDGE_ENABLED=true
JUDGE_SIMILARITY_THRESHOLD=0.95
JUDGE_ONLY_NEW_DOCUMENTS=true
JUDGE_SAMPLE_RATE=0.0
```

### Run

Terminal 1:

```bash
uv run uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2:

```bash
uv run python web/app.py
```

Access points:

- UI: http://localhost:7860
- API docs: http://localhost:8000/docs

## 2.2 Operational flow (what to do first)

1. Start API and UI.
2. Upload a PDF in the UI.
3. Choose Judge Mode:
   - `auto`: policy-driven
   - `force`: always run judge
   - `skip`: bypass judge
4. Review:
   - Markdown output
   - Quality summary (verdict, indicators)
   - Suggested pages to inspect
5. If needed, clear cache from UI or `DELETE /api/cache` and re-run.

## 2.3 Key endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Service health status |
| `/api/models` | GET | List available Gemini models |
| `/api/convert` | POST | Convert PDF to markdown (supports `judge_mode`) |
| `/api/metrics/{pdf_id}` | GET | Get latest OCR metrics + judge decision + page references |
| `/api/judge/diagnostics/{pdf_id}` | GET | Get judge diagnostics (mode/model, latency, summarized signals, parsed output) |
| `/api/history` | GET | List processed/cached PDFs |
| `/api/convert/{pdf_id}` | GET | Retrieve cached converted markdown |
| `/api/cache` | DELETE | Clear server cache (`include_metrics=true/false`) |

### Example: conversion with judge override

```bash
curl -X POST "http://localhost:8000/api/convert?judge_mode=force" \
  -H "accept: application/json" \
  -F "file=@./dataset/sample.pdf"
```

### Example: clear cache

```bash
curl -X DELETE "http://localhost:8000/api/cache?include_metrics=true"
```

## 2.4 Quick troubleshooting

- API not reachable: verify FastAPI terminal is running.
- Empty/invalid PDF error: validate file and size (`MAX_FILE_SIZE_MB`).
- Gemini failures: verify key and available models in `/api/models`.
- Unexpected cached behavior: clear cache and retry conversion.

## 2.5 Judge behavior notes

- Judge execution mode returned by metrics/diagnostics can be `llm`, `rules_fallback`, `rules`, or `skipped`.
- Decision payload includes `judge_model` and `judge_mode` to make audits explicit.
- For cached documents, `force` mode triggers a fresh judge run and stores a new metrics snapshot.
