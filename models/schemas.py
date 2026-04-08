"""
Pydantic schemas for API request/response validation.
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class PDFConvertRequest(BaseModel):
    """Request schema for PDF conversion endpoint."""

    file_name: str = Field(..., description="Name of the PDF file")
    file_content: bytes = Field(..., description="PDF file content as bytes")


class PDFConvertResponse(BaseModel):
    """Response schema for PDF conversion endpoint."""

    pdf_id: str = Field(..., description="Unique identifier for the PDF (hash)")
    file_name: str = Field(..., description="Name of the PDF file")
    markdown_content: str = Field(..., description="Converted Markdown content")
    pages_processed: int = Field(..., description="Number of pages processed")
    is_cached: bool = Field(
        ...,
        description="Whether the result was retrieved from cache (True) or newly generated (False)",
    )
    timestamp: datetime = Field(..., description="Timestamp of processing")


class PDFHistoryItem(BaseModel):
    """Schema for a single item in the history list."""

    pdf_id: str = Field(..., description="Unique identifier for the PDF")
    file_name: str = Field(..., description="Name of the PDF file")
    timestamp: datetime = Field(..., description="Timestamp of processing")
    pages_processed: int = Field(..., description="Number of pages in the PDF")
    is_cached: bool = Field(..., description="Whether this is in cache")


class PDFHistoryResponse(BaseModel):
    """Response schema for history endpoint."""

    total_pdfs: int = Field(..., description="Total number of PDFs processed")
    history: list[PDFHistoryItem] = Field(..., description="List of processed PDFs")


class ErrorResponse(BaseModel):
    """Schema for error responses."""

    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Additional error details")


class MetricLevelSummary(BaseModel):
    """Severity classification for a single score."""

    score_name: str = Field(..., description="Metric name")
    value: Optional[float] = Field(None, description="Metric value")
    level: str = Field(..., description="GREEN, AMBER, or RED")
    threshold_note: str = Field(..., description="Threshold rule used")


class JudgeDecision(BaseModel):
    """Judge decision and trigger metadata."""

    verdict: str = Field(..., description="Decision result")
    semaphore: str = Field(..., description="GREEN, AMBER, or RED")
    reason: str = Field(..., description="Short reason for decision")
    run_trigger: str = Field(..., description="Why judge ran or skipped")
    judge_model: Optional[str] = Field(None, description="Gemini model used by judge")
    judge_mode: Optional[str] = Field(None, description="llm, rules, or rules_fallback")


class PageReviewReference(BaseModel):
    """Actionable page-level review hint for humans."""

    page_num: int = Field(..., description="Page number to review in original PDF")
    similarity: Optional[float] = Field(None, description="Page-level similarity score")
    severity: str = Field(..., description="AMBER or RED")
    why: str = Field(..., description="Reason this page should be reviewed")
    source_excerpt: Optional[str] = Field(None, description="Short source text excerpt from the flagged page")


class OCRMetricsResponse(BaseModel):
    """API response for stored OCR and judge metrics."""

    pdf_id: str
    file_name: str
    is_cached: bool
    token_count_method: Optional[str] = None
    similarity: Optional[float] = None
    cer_estimate: Optional[float] = None
    wer_estimate: Optional[float] = None
    latency_ms_total: Optional[float] = None
    input_tokens_total: Optional[int] = None
    output_tokens_total: Optional[int] = None
    effective_input_tokens_total: Optional[int] = None
    effective_output_tokens_total: Optional[int] = None
    estimated_total_cost_usd: Optional[float] = None
    context_window_utilization_pct: Optional[float] = None
    output_window_utilization_pct: Optional[float] = None
    levels: list[MetricLevelSummary] = Field(default_factory=list)
    review_pages: list[int] = Field(default_factory=list)
    page_review_references: list[PageReviewReference] = Field(default_factory=list)
    decision: Optional[JudgeDecision] = None
    timestamp: datetime


# OAuth2 schemas (prepared for future use)
class TokenRequest(BaseModel):
    """Request schema for token generation (OAuth2 prepared)."""

    username: str
    password: str


class TokenResponse(BaseModel):
    """Response schema for token (OAuth2 prepared)."""

    access_token: str
    token_type: str = "bearer"
