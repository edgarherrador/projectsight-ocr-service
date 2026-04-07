"""
FastAPI application for PDF to Markdown conversion API.
Provides REST endpoints and automatic Swagger documentation.
"""
import uuid
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import logging

from models.schemas import (
    PDFConvertResponse,
    PDFHistoryResponse,
    PDFHistoryItem,
    ErrorResponse,
)
from cache.database import get_cached_result, save_to_cache, get_history
from api.gemini_service import (
    process_pdf_with_gemini,
    list_available_models_for_generate_content,
)
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

    normalized_available = {
        model_name.removeprefix("models/") for model_name in available_models
    }
    normalized_candidate = [
        model_name.removeprefix("models/") for model_name in candidate_models
    ]

    configured_available = configured_model.removeprefix("models/") in normalized_available

    return {
        "configured_model": configured_model,
        "candidate_models": candidate_models,
        "available_models": available_models,
        "configured_model_available": configured_available,
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
async def convert_pdf(file: UploadFile = File(...)):
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

        # Process with Gemini
        success, markdown_content, gemini_message = process_pdf_with_gemini(
            content
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
