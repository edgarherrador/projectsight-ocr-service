# PDF to Markdown Converter

AI-powered PDF to Markdown converter using Google Gemini (configurable model with fallback) with FastAPI backend and Gradio web interface.

## ✨ Features

- 🤖 **AI-Powered Conversion**: Uses Google Gemini for intelligent PDF parsing and Markdown formatting
- 🔁 **Model Fallback**: Automatically tries fallback models when the primary model is unavailable
- 📄 **Page-by-Page Processing**: Handles large PDFs efficiently by processing one page at a time
- 💾 **Intelligent Caching**: Stores conversion results to avoid reprocessing the same PDF (saves API tokens!)
- 🧹 **Server Cache Clear**: Clear cached PDFs and OCR metrics from API/UI when you need a clean rerun
- 🚦 **Quality Judge (Rule-Based)**: Auto/Force/Skip judge execution mode with RED/AMBER/GREEN decisioning
- 🔎 **Actionable Quality References**: Returns pages to review with short excerpts to guide human validation
- ⏱️ **Human-Friendly Timing**: UI shows processing duration in `mm:ss`
- 🚀 **FastAPI Backend**: RESTful API with automatic Swagger documentation
- 🎨 **Gradio Web Interface**: User-friendly web UI for easy PDF uploads
- 📊 **History Tracking**: View all processed PDFs and their metadata
- 🔐 **OAuth Ready**: Authentication structure prepared for future OAuth2 integration
- 📋 **Multiple Access Methods**: Use via web UI, curl, Bruno, or any HTTP client

## 📋 Requirements

- Python 3.10+
- Google Gemini API Key
- System Prompt for Gemini
- Max PDF size: 30 MB

## 🚀 Quick Start

### 1. Clone and Setup

```bash
# Clone the repository
git clone <repo-url>
cd projectsight-ocr-service

# Create virtual environment (optional, if not using system Python)
python -m venv venv
venv\Scripts\activate  # On Windows
source venv/bin/activate  # On macOS/Linux

# Install dependencies using uv
uv pip install -e .
# Or with pip
pip install -e .
```

### 2. Configure Environment

```bash
# Copy example environment file
copy .env.example .env  # Windows
# OR
cp .env.example .env  # macOS/Linux

# Edit .env and add your credentials:
# GEMINI_API_KEY=your_actual_api_key_here
# SYSTEM_PROMPT=./prompts/system_prompt.prompty
# BENCHMARK_MODELS=gemini-3.1-pro-preview,gemini-2.5-pro
# BENCHMARK_MODEL_PRICES=gemini-3.1-pro-preview:INPUT_PER_1M:OUTPUT_PER_1M,gemini-2.5-pro:INPUT_PER_1M:OUTPUT_PER_1M
```

### 3. Run the Application

**Option A: Using the startup script (Windows)**
```bash
run.bat
```

**Option B: Manual startup (All platforms)**

Terminal 1 - Start FastAPI backend:
```bash
uv run uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2 - Start Gradio frontend:
```bash
uv run python web/app.py
```

### 4. Access the Application

- **Web Interface**: http://localhost:7860
- **API Swagger Docs**: http://localhost:8000/docs
- **API OpenAPI JSON**: http://localhost:8000/openapi.json
- **Health Check**: http://localhost:8000/health

## 📚 API Endpoints

### Convert PDF to Markdown
```bash
POST /api/convert

# Using curl:
curl -X POST "http://localhost:8000/api/convert" \
  -H "accept: application/json" \
  -F "file=@your_file.pdf"

# Optional judge override per request:
# auto (default), force, skip
curl -X POST "http://localhost:8000/api/convert?judge_mode=force" \
  -H "accept: application/json" \
  -F "file=@your_file.pdf"

# Using Bruno or Postman: Import from http://localhost:8000/docs
```

**Response:**
```json
{
  "pdf_id": "abc123...",
  "file_name": "document.pdf",
  "markdown_content": "# Your Markdown Content...",
  "pages_processed": 10,
  "is_cached": false,
  "timestamp": "2024-04-06T10:30:00"
}
```

### Get Processing History
```bash
GET /api/history

curl "http://localhost:8000/api/history"
```

**Response:**
```json
{
  "total_pdfs": 3,
  "history": [
    {
      "pdf_id": "abc123...",
      "file_name": "document.pdf",
      "timestamp": "2024-04-06T10:30:00",
      "pages_processed": 10,
      "is_cached": true
    }
  ]
}
```

### Retrieve Cached Result
```bash
GET /api/convert/{pdf_id}

curl "http://localhost:8000/api/convert/abc123..."
```

### Get OCR Metrics + Judge Decision
```bash
GET /api/metrics/{pdf_id}

curl "http://localhost:8000/api/metrics/abc123..."
```

**Response highlights:**
- `similarity`, `cer_estimate`, `wer_estimate`
- `latency_ms_total`, token totals, cost estimate
- `decision` (verdict/semaphore/reason/trigger)
- `review_pages` and `page_review_references` (page-level hints for humans)

### Clear Server Cache
```bash
DELETE /api/cache?include_metrics=true

curl -X DELETE "http://localhost:8000/api/cache?include_metrics=true"
```

Use this endpoint to remove cached PDF conversions and (optionally) OCR metrics rows.

### Health Check
```bash
GET /health

curl "http://localhost:8000/health"
```

### List Available Gemini Models
```bash
GET /api/models

curl "http://localhost:8000/api/models"
```

Use this endpoint to verify which models are available for your current API key and whether your configured model is accessible.

## 🏗️ Project Structure

```
projectsight-ocr-service/
├── config/
│   └── settings.py           # Configuration and environment loading
├── models/
│   └── schemas.py            # Pydantic schemas for API
├── cache/
│   └── database.py           # SQLite caching layer
├── utils/
│   └── pdf_processor.py      # PDF extraction and validation
├── api/
│   ├── main.py              # FastAPI application and endpoints
│   ├── gemini_service.py    # Gemini integration + per-page metrics
│   └── judge_service.py     # Rule-based quality judge
├── web/
│   └── app.py               # Gradio web interface
├── auth/
│   └── oauth.py             # OAuth2 preparation (not active)
├── prompts/
│   └── system_prompt.prompty # System prompt file (.prompty or .md)
├── scripts/
│   └── benchmark_ocr.py     # OCR benchmark runner
├── pyproject.toml           # Project dependencies
├── .env.example             # Environment variables template
├── .gitignore               # Git ignore rules
├── run.bat                  # Windows startup script
└── README.md               # This file
```

## 🔧 Configuration

Edit `.env` to customize:

```ini
# Google Generative AI
GEMINI_API_KEY=your_api_key_here
GEMINI_MODEL=gemini-3.1-pro
GEMINI_FALLBACK_MODELS=gemini-1.5-pro

# System prompt file path (.prompty or .md)
SYSTEM_PROMPT=./prompts/system_prompt.prompty

# Database location
DATABASE_PATH=./cache/pdf_cache.db

# API settings
API_HOST=127.0.0.1
API_PORT=8000

# Gradio settings
GRADIO_HOST=127.0.0.1
GRADIO_PORT=7860

# File size limit
MAX_FILE_SIZE_MB=30

# Benchmark defaults
BENCHMARK_MODELS=gemini-3.1-pro-preview,gemini-2.5-pro
BENCHMARK_DISABLE_CACHE=true
BENCHMARK_IGNORE_SIZE_LIMIT=true
BENCHMARK_MAX_FILE_SIZE_MB=50

# Optional pricing map for estimated benchmark cost (USD per 1M tokens)
# Format: model:input_per_1m:output_per_1m,model2:input_per_1m:output_per_1m
BENCHMARK_MODEL_PRICES=

# Judge behavior
JUDGE_MODEL=gemini-3.1-pro
JUDGE_ENABLED=true
JUDGE_SIMILARITY_THRESHOLD=0.95
JUDGE_ONLY_NEW_DOCUMENTS=true
JUDGE_SAMPLE_RATE=0.0
```

### Judge Mode (`POST /api/convert`)

- `auto`: Follows policy + thresholds.
- `force`: Always runs judge for this request.
- `skip`: Skips judge for this request.

In the Gradio UI, this is exposed as **Judge Mode** (`auto | force | skip`).

## 🚦 OCR Quality and Human Review

The service stores OCR metrics and judge outcomes per document.

Key indicators:
- **Text similarity**: Higher is better.
- **Estimated character error rate (CER)**: Lower is better.
- **Document structure fidelity (proxy)**: Higher is better.

When quality needs attention, the API returns:
- `review_pages`: list of page numbers to inspect first.
- `page_review_references`: per-page severity/reason and a short source excerpt.

This helps a human reviewer quickly navigate to where quality drift likely happened.

## ⚖️ Quick OCR Benchmark (Quality + Cost + Latency)

Use the benchmark runner to compare models over a local PDF dataset without cache effects.

### What it measures

- Text similarity (reference PDF extracted text vs generated Markdown)
- Latency (total, p50, p95)
- Token usage (input/output/total when exposed by SDK)
- Estimated cost from token totals and configured prices
- Throughput (pages per minute)
- Basic robustness (failed pages, empty output rate)

### Run benchmark

```bash
uv run python scripts/benchmark_ocr.py --pdf-dir ./dataset
```

### Optional flags

```bash
# Limit processed pages for quick demos
uv run python scripts/benchmark_ocr.py --pdf-dir ./dataset --max-pages 5

# Override models
uv run python scripts/benchmark_ocr.py --pdf-dir ./dataset \
  --model gemini-3.1-pro-preview --model gemini-2.5-pro

# Override prices directly from CLI (USD per 1M tokens)
uv run python scripts/benchmark_ocr.py --pdf-dir ./dataset \
  --price gemini-3.1-pro-preview:INPUT_PER_1M:OUTPUT_PER_1M \
  --price gemini-2.5-pro:INPUT_PER_1M:OUTPUT_PER_1M
```

### Outputs

- `benchmark_results.json`: full results including page-level metrics
- `benchmark_results.csv`: summary rows by file/model

Notes:
- Internal model context window is not directly observable from the API, so it is exported as `null`.
- If token usage is unavailable for a response, estimated cost is exported as `null`.

## 🗄️ Database

- **Type**: SQLite (local file-based)
- **Location**: `./cache/pdf_cache.db`
- **Tables**: 
  - `pdf_cache`: Stores PDF IDs, file names, converted Markdown, and timestamps
  - `ocr_metrics_cache`: Stores OCR metrics snapshots and judge decisions
- **Features**:
  - Automatic schema creation on first run
  - SHA256 hashing for duplicate detection
  - Indexed queries for performance

## 🔐 Authentication (OAuth2 - Prepared)

OAuth2 authentication structure is ready but not enforced. To activate:

1. Edit `auth/oauth.py` with your JWT secret
2. Implement token verification logic
3. Add `Depends(oauth2_scheme)` to endpoints
4. Test with Swagger UI

Currently, all endpoints are accessible without authentication.

## 📊 Caching Strategy

The application uses content-based caching:

1. **Hash Check**: PDF content is hashed (SHA256)
2. **Cache Lookup**: Before processing, the hash is checked against the database
3. **Cache Hit**: If found, return stored Markdown immediately (⚡ fast!)
4. **Cache Miss**: If not found, process with Gemini and store result

**Benefits:**
- ✅ Faster responses for repeated PDFs
- ✅ Reduced API token usage
- ✅ Same PDF from different uploads = single Gemini call
- ✅ Transparent to the user

## 🐛 Troubleshooting

### API Connection Error
```
❌ Connection Error: Cannot reach API at http://127.0.0.1:8000
```
**Solution**: Make sure FastAPI is running in Terminal 1

### Missing .env File
```
⚠️ WARNING: .env file not found!
```
**Solution**: 
```bash
copy .env.example .env
# Edit .env with your GEMINI_API_KEY
```

### Invalid PDF
```
❌ Error: File is empty
```
**Solution**: Upload a valid PDF file under 30 MB

### Gemini API Error
```
❌ Error parsing PDF: [Gemini error message]
```
**Solutions**:
- Check GEMINI_API_KEY is valid
- Check model availability at `GET /api/models`
- Configure `GEMINI_FALLBACK_MODELS` in `.env`
- Check internet connection
- Review API usage limits

### Database Error
```
❌ Database error while saving to cache
```
**Solution**: Ensure `cache/` directory is writable

## 📦 Dependencies

- **fastapi**: Web framework
- **uvicorn**: ASGI server
- **gradio**: Web UI framework
- **google-genai**: Gemini API client
- **sqlalchemy**: ORM for database
- **pypdf**: PDF parsing
- **python-dotenv**: Environment variable management
- **pydantic**: Data validation

See `pyproject.toml` for complete list.

## 🧪 Testing

### Manual API Test with curl
```bash
# Convert a PDF
curl -X POST "http://localhost:8000/api/convert" \
  -H "accept: application/json" \
  -F "file=@test.pdf"

# Get history
curl "http://localhost:8000/api/history"

# Health check
curl "http://localhost:8000/health"
```

### Using Bruno (Postman alternative)
1. Open Bruno
2. Create New Collection
3. Add Request
4. Import from OpenAPI: `http://localhost:8000/openapi.json`
5. Test endpoints with your PDF files

## 📝 System Prompt

The system prompt guides Gemini's PDF to Markdown conversion. Customize it in `.env`:

```
SYSTEM_PROMPT=./prompts/system_prompt.prompty
```

Then edit the prompt content directly in `prompts/system_prompt.prompty` (or point to any `.md` file path).

## 🚀 Performance Notes

- **Page-by-page processing**: Optimized for large PDFs
- **Caching**: Eliminates redundant API calls
- **Async/await**: Non-blocking operations where possible
- **Typical conversion time**:
  - Cached result: < 100ms
  - New PDF (10 pages): 10-30 seconds
  - New PDF (50 pages): 30-90 seconds

## 📄 License

TBD

## 👥 Support

For issues or questions, please open an issue on GitHub or contact ProjectSight.

---

**Made with ❤️ by ProjectSight**
