"""
FastAPI application for PDF to Markdown conversion API.
Provides REST endpoints and automatic Swagger documentation.
"""
from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import logging

from models.schemas import (
    PDFConvertResponse,
    PDFHistoryResponse,
    PDFHistoryItem,
    OCRMetricsResponse,
    MetricLevelSummary,
    JudgeDecision,
    PageReviewReference,
)
from cache.database import (
    get_cached_result,
    save_to_cache,
    get_history,
    save_ocr_metrics,
    get_latest_ocr_metrics,
    clear_cache,
)
from api.gemini_service import (
    process_pdf_with_gemini_with_metrics,
    list_available_models_for_generate_content,
)
from api.judge_service import should_run_judge, evaluate_metrics
from utils.pdf_processor import get_pdf_page_count
from config.settings import settings

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI application
app = FastAPI(
    title="PDF to Markdown Converter API",
    description="Convert PDF files to Markdown format using Google Gemini (model configurable with fallback)",
    version="1.0.0",
    contact={
        "name": "ProjectSight",
        "url": "https://projectsight.dev",
    },
)

# Add CORS middleware for Gradio and external clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _normalize_model_name(model_name: str) -> str:
    cleaned = (model_name or "").strip()
    if cleaned.startswith("models/"):
        cleaned = cleaned[len("models/") :]
    return cleaned


def _estimate_total_cost_usd(metrics: dict) -> float | None:
    """Estimate cost using configured benchmark price map when available."""
    input_tokens = metrics.get("effective_input_tokens_total")
    output_tokens = metrics.get("effective_output_tokens_total")
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        return None

    model_name = _normalize_model_name(metrics.get("requested_model") or settings.gemini_model)
    price_map = settings.get_benchmark_price_map()
    model_price = price_map.get(model_name)
    if not model_price:
        return None

    input_per_1m = model_price.get("input_per_1m")
    output_per_1m = model_price.get("output_per_1m")
    if not isinstance(input_per_1m, float) or not isinstance(output_per_1m, float):
        return None

    input_cost = (input_tokens / 1_000_000) * input_per_1m
    output_cost = (output_tokens / 1_000_000) * output_per_1m
    return input_cost + output_cost


def _build_page_review_references(metrics: dict) -> list[dict]:
    """Build actionable page-level references from stored page metrics."""
    page_metrics = metrics.get("page_metrics")
    if not isinstance(page_metrics, list):
        return []

    references: list[dict] = []
    for page_metric in page_metrics:
        if not isinstance(page_metric, dict):
            continue

        similarity = page_metric.get("similarity")
        page_num = page_metric.get("page_num")
        if not isinstance(page_num, int):
            continue

        level = "AMBER"
        why = "No page-level similarity available"
        if isinstance(similarity, float):
            if similarity < 0.90:
                level = "RED"
                why = "Low similarity in this page"
            elif similarity < 0.98:
                level = "AMBER"
                why = "Potential formatting/text drift in this page"
            else:
                continue

        references.append(
            {
                "page_num": page_num,
                "similarity": similarity,
                "severity": level,
                "why": why,
                "source_excerpt": page_metric.get("source_excerpt"),
            }
        )

    references.sort(
        key=lambda item: (
            0 if item["severity"] == "RED" else 1,
            item["similarity"] if isinstance(item["similarity"], float) else 1.0,
        )
    )
    return references[:5]


@app.get("/health", tags=["System"])
async def health_check():
    """Health check endpoint to verify API is running."""
    return {"status": "healthy", "service": "pdf-to-markdown-converter"}


@app.get("/api/models", tags=["System"])
async def get_available_models():
    """List configured and available Gemini models for generateContent."""
    success, available_models, message = list_available_models_for_generate_content()
    configured_model = settings.gemini_model
    candidate_models = settings.get_candidate_models()
    policy_small_model = settings.gemini_small_doc_model
    policy_large_model = settings.gemini_large_doc_model
    policy_threshold = settings.gemini_large_doc_page_threshold

    normalized_available = {
        model_name.removeprefix("models/") for model_name in available_models
    }
    normalized_candidate = [
        model_name.removeprefix("models/") for model_name in candidate_models
    ]

    configured_available = configured_model.removeprefix("models/") in normalized_available
    policy_small_available = policy_small_model.removeprefix("models/") in normalized_available
    policy_large_available = policy_large_model.removeprefix("models/") in normalized_available

    return {
        "configured_model": configured_model,
        "candidate_models": candidate_models,
        "conversion_policy": {
            "small_document_model": policy_small_model,
            "large_document_model": policy_large_model,
            "large_document_page_threshold": policy_threshold,
        },
        "available_models": available_models,
        "configured_model_available": configured_available,
        "conversion_policy_models_available": {
            "small_document_model": policy_small_available,
            "large_document_model": policy_large_available,
        },
        "recommendation": (
            "Configured model is available"
            if configured_available
            else "Configured model is unavailable. Use one of available_models or keep fallback configured"
        ),
        "candidate_models_available": [
            model_name
            for model_name in normalized_candidate
            if model_name in normalized_available
        ],
        "status": "ok" if success else "warning",
        "message": message,
    }


@app.post(
    "/api/convert",
    response_model=PDFConvertResponse,
    response_description="PDF conversion successful",
    tags=["Conversion"],
)
async def convert_pdf(
    file: UploadFile = File(...),
    judge_mode: str = Query(
        default="auto",
        pattern="^(auto|force|skip)$",
        description="Judge execution policy override: auto, force, or skip",
    ),
):
    """
    Convert a PDF file to Markdown format.

    This endpoint accepts a PDF file and converts it to Markdown using Gemini.
    Results are cached to avoid reprocessing the same PDF.

    **Parameters:**
    - **file**: PDF file to convert (max 30 MB)

    **Returns:**
    - **pdf_id**: Unique identifier for the PDF (SHA256 hash)
    - **file_name**: Original file name
    - **markdown_content**: Converted Markdown text
    - **pages_processed**: Number of pages processed
    - **is_cached**: Whether result was from cache (True) or newly generated (False)
    - **timestamp**: Processing timestamp

    **Error Cases:**
    - 400: File validation failed (invalid PDF, too large)
    - 422: File upload validation error
    - 500: Gemini API error or processing failure
    """
    try:
        # Read file content
        content = await file.read()

        if not content:
            raise HTTPException(status_code=400, detail="File is empty")

        # Check cache first
        cached_result = get_cached_result(content)
        if cached_result:
            logger.info(f"Cache hit for PDF: {file.filename}")

            latest_metrics = get_latest_ocr_metrics(cached_result["pdf_id"])
            if latest_metrics:
                cached_metrics = latest_metrics.get("metrics", {})
                similarity = cached_metrics.get("average_similarity")
                similarity_value = similarity if isinstance(similarity, float) else None

                run_judge = False
                run_trigger = "cache_hit_skip"
                if judge_mode == "force":
                    run_judge = True
                    run_trigger = "cache_hit_force"
                elif judge_mode == "auto":
                    run_judge = (
                        settings.judge_enabled
                        and similarity_value is not None
                        and similarity_value < settings.judge_similarity_threshold
                    )
                    if run_judge:
                        run_trigger = "cache_hit_low_similarity"
                    else:
                        run_trigger = "cache_hit_auto_skip"

                if run_judge:
                    decision = evaluate_metrics(cached_metrics, run_trigger)
                    cached_metrics["judge_model"] = _normalize_model_name(settings.judge_model)
                    save_ocr_metrics(
                        pdf_id=cached_result["pdf_id"],
                        file_name=file.filename,
                        is_cached=True,
                        metrics=cached_metrics,
                        decision=decision,
                    )

            return PDFConvertResponse(
                pdf_id=cached_result["pdf_id"],
                file_name=file.filename,
                markdown_content=cached_result["markdown_content"],
                pages_processed=cached_result["pages_processed"],
                is_cached=True,
                timestamp=cached_result["timestamp"],
            )

        # Get page count
        success, page_count, page_message = get_pdf_page_count(content)
        if not success:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid PDF file: {page_message}",
            )

        logger.info(
            f"Processing PDF: {file.filename} ({page_count} pages)"
        )

        conversion_candidate_models = settings.get_conversion_candidate_models(page_count)
        selected_conversion_model = (
            conversion_candidate_models[0] if conversion_candidate_models else settings.gemini_model
        )
        logger.info(
            "Conversion model policy selected model '%s' for %s pages (threshold=%s)",
            selected_conversion_model,
            page_count,
            settings.gemini_large_doc_page_threshold,
        )

        # Process with Gemini and collect metrics for judge and UI reporting.
        success, markdown_content, gemini_message, metrics = process_pdf_with_gemini_with_metrics(
            content,
            model_override=selected_conversion_model,
            candidate_models_override=conversion_candidate_models,
        )

        if not success:
            logger.error(f"Gemini processing failed: {gemini_message}")
            raise HTTPException(
                status_code=500,
                detail=f"PDF processing failed: {gemini_message}",
            )

        # Generate unique ID (hash-based)
        import hashlib

        pdf_id = hashlib.sha256(content).hexdigest()

        # Save to cache
        save_success = save_to_cache(
            pdf_id=pdf_id,
            file_name=file.filename,
            file_content=content,
            markdown_content=markdown_content,
            pages_processed=page_count,
        )

        if not save_success:
            logger.warning(f"Failed to cache PDF: {file.filename}")

        metrics["requested_model"] = _normalize_model_name(
            metrics.get("requested_model") or selected_conversion_model
        )
        metrics["candidate_models"] = [
            _normalize_model_name(model_name)
            for model_name in (metrics.get("candidate_models") or conversion_candidate_models)
            if (model_name or "").strip()
        ]
        metrics["estimated_total_cost_usd"] = _estimate_total_cost_usd(metrics)
        metrics["judge_model"] = _normalize_model_name(settings.judge_model)

        similarity = metrics.get("average_similarity")
        run_judge, run_trigger = should_run_judge(
            is_cached=False,
            similarity=similarity if isinstance(similarity, float) else None,
        )
        if judge_mode == "force":
            run_judge = True
            run_trigger = "forced_by_request"
        elif judge_mode == "skip":
            run_judge = False
            run_trigger = "skipped_by_request"

        decision = evaluate_metrics(metrics, run_trigger) if run_judge else None

        save_metrics_success = save_ocr_metrics(
            pdf_id=pdf_id,
            file_name=file.filename,
            is_cached=False,
            metrics=metrics,
            decision=decision,
        )
        if not save_metrics_success:
            logger.warning(f"Failed to save OCR metrics for PDF: {file.filename}")

        logger.info(f"Successfully processed PDF: {file.filename}")

        return PDFConvertResponse(
            pdf_id=pdf_id,
            file_name=file.filename,
            markdown_content=markdown_content,
            pages_processed=page_count,
            is_cached=False,
            timestamp=datetime.utcnow(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error processing PDF: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}",
        )


@app.get(
    "/api/metrics/{pdf_id}",
    response_model=OCRMetricsResponse,
    response_description="Latest OCR metrics retrieved successfully",
    tags=["Metrics"],
)
async def get_pdf_metrics(pdf_id: str):
    """Return latest OCR metrics and judge decision for a PDF id."""
    record = get_latest_ocr_metrics(pdf_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"No metrics found for pdf_id={pdf_id}")

    metrics = record.get("metrics", {})
    decision_data = record.get("decision")

    levels: list[MetricLevelSummary] = []
    if decision_data and isinstance(decision_data.get("levels"), list):
        for item in decision_data["levels"]:
            levels.append(
                MetricLevelSummary(
                    score_name=item.get("score_name", "unknown"),
                    value=item.get("value"),
                    level=item.get("level", "AMBER"),
                    threshold_note=item.get("threshold_note", ""),
                )
            )

    decision = None
    if decision_data:
        decision = JudgeDecision(
            verdict=decision_data.get("verdict", "REVIEW_MANUAL"),
            semaphore=decision_data.get("semaphore", "AMBER"),
            reason=decision_data.get("reason", "No reason provided"),
            run_trigger=decision_data.get("run_trigger", "unknown"),
            judge_model=decision_data.get("judge_model"),
            judge_mode=decision_data.get("judge_mode"),
        )

    page_review_references_data = _build_page_review_references(metrics)
    page_review_references = [
        PageReviewReference(
            page_num=item["page_num"],
            similarity=item.get("similarity"),
            severity=item["severity"],
            why=item["why"],
            source_excerpt=item.get("source_excerpt"),
        )
        for item in page_review_references_data
    ]
    review_pages = [item["page_num"] for item in page_review_references_data]

    return OCRMetricsResponse(
        pdf_id=record["pdf_id"],
        file_name=record["file_name"],
        is_cached=record["is_cached"],
        token_count_method=metrics.get("token_count_method"),
        similarity=metrics.get("average_similarity"),
        cer_estimate=metrics.get("cer_estimate"),
        wer_estimate=metrics.get("wer_estimate"),
        latency_ms_total=metrics.get("total_latency_ms"),
        input_tokens_total=metrics.get("input_tokens_total"),
        output_tokens_total=metrics.get("output_tokens_total"),
        effective_input_tokens_total=metrics.get("effective_input_tokens_total"),
        effective_output_tokens_total=metrics.get("effective_output_tokens_total"),
        estimated_total_cost_usd=metrics.get("estimated_total_cost_usd"),
        context_window_utilization_pct=metrics.get("context_window_utilization_pct"),
        output_window_utilization_pct=metrics.get("output_window_utilization_pct"),
        levels=levels,
        review_pages=review_pages,
        page_review_references=page_review_references,
        decision=decision,
        timestamp=record["timestamp"],
    )


@app.get(
    "/api/judge/diagnostics/{pdf_id}",
    tags=["Metrics"],
)
async def get_judge_diagnostics(pdf_id: str):
    """Return LLM judge diagnostics for the latest metrics record of a PDF id."""
    record = get_latest_ocr_metrics(pdf_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"No metrics found for pdf_id={pdf_id}")

    decision_data = record.get("decision") or {}
    metrics_data = record.get("metrics") or {}

    return {
        "pdf_id": record["pdf_id"],
        "file_name": record["file_name"],
        "timestamp": record["timestamp"],
        "judge_mode": decision_data.get("judge_mode"),
        "judge_model": decision_data.get("judge_model") or metrics_data.get("judge_model"),
        "run_trigger": decision_data.get("run_trigger"),
        "decision": {
            "verdict": decision_data.get("verdict"),
            "semaphore": decision_data.get("semaphore"),
            "reason": decision_data.get("reason"),
        },
        "diagnostics": decision_data.get("judge_diagnostics"),
    }


@app.delete(
    "/api/cache",
    tags=["History"],
)
async def clear_server_cache(include_metrics: bool = True):
    """Clear PDF cache and optionally OCR metrics cache."""
    result = clear_cache(delete_metrics=include_metrics)
    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=f"Failed to clear cache: {result.get('error', 'unknown error')}",
        )

    return {
        "status": "ok",
        "deleted_pdfs": result["deleted_pdfs"],
        "deleted_metrics": result["deleted_metrics"],
        "include_metrics": include_metrics,
    }


@app.get(
    "/api/history",
    response_model=PDFHistoryResponse,
    response_description="History retrieved successfully",
    tags=["History"],
)
async def get_pdf_history():
    """
    Retrieve the history of processed PDFs.

    Returns a list of all PDFs that have been processed and cached.

    **Returns:**
    - **total_pdfs**: Total number of PDFs in cache
    - **history**: List of cached PDFs with their metadata

    **Error Cases:**
    - 500: Database error
    """
    try:
        history = get_history()
        history_items = [PDFHistoryItem(**item) for item in history]

        return PDFHistoryResponse(
            total_pdfs=len(history_items),
            history=history_items,
        )
    except Exception as e:
        logger.error(f"Error retrieving history: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve history: {str(e)}",
        )


@app.get(
    "/api/convert/{pdf_id}",
    response_model=PDFConvertResponse,
    response_description="Cached PDF retrieved successfully",
    tags=["History"],
)
async def get_cached_pdf(pdf_id: str):
    """
    Retrieve a previously converted PDF from cache.

    **Parameters:**
    - **pdf_id**: SHA256 hash identifier of the PDF

    **Returns:**
    - Cached Markdown content with original metadata

    **Error Cases:**
    - 404: PDF not found in cache
    - 500: Database error
    """
    try:
        history = get_history()
        pdf_entry = next((item for item in history if item["pdf_id"] == pdf_id), None)

        if not pdf_entry:
            raise HTTPException(
                status_code=404,
                detail=f"PDF with id {pdf_id} not found in cache",
            )

        # Retrieve full content from database
        from cache.database import SessionLocal, PDFCache

        db = SessionLocal()
        cached_pdf = db.query(PDFCache).filter_by(pdf_id=pdf_id).first()
        db.close()

        if not cached_pdf:
            raise HTTPException(
                status_code=404,
                detail="PDF data not found",
            )

        return PDFConvertResponse(
            pdf_id=cached_pdf.pdf_id,
            file_name=cached_pdf.file_name,
            markdown_content=cached_pdf.markdown_content,
            pages_processed=cached_pdf.pages_processed,
            is_cached=True,
            timestamp=cached_pdf.timestamp,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving cached PDF: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve cached PDF: {str(e)}",
        )


@app.get("/", tags=["Root"])
async def root():
    """
    Root endpoint with API information.

    Provides links to documentation and status.
    """
    return {
        "service": "PDF to Markdown Converter",
        "version": "1.0.0",
        "status": "running",
        "documentation": "/docs",
        "openapi": "/openapi.json",
        "health": "/health",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )
