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


# OAuth2 schemas (prepared for future use)
class TokenRequest(BaseModel):
    """Request schema for token generation (OAuth2 prepared)."""

    username: str
    password: str


class TokenResponse(BaseModel):
    """Response schema for token (OAuth2 prepared)."""

    access_token: str
    token_type: str = "bearer"
