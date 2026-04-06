"""
PDF processing utilities for extracting content and validating file size.
"""
import io
from pathlib import Path
from pypdf import PdfReader
from config.settings import settings


def validate_pdf_size(file_content: bytes) -> tuple[bool, str]:
    """
    Validate that PDF file size is within acceptable limits.

    Args:
        file_content: PDF file content as bytes

    Returns:
        Tuple of (is_valid, message)
    """
    file_size_mb = len(file_content) / (1024 * 1024)

    if file_size_mb > settings.max_file_size_mb:
        return False, (
            f"File size {file_size_mb:.2f} MB exceeds maximum "
            f"allowed size of {settings.max_file_size_mb} MB"
        )

    return True, "File size is valid"


def extract_pdf_text(file_content: bytes) -> tuple[bool, str | list[str], str]:
    """
    Extract text from PDF file, page by page.

    Args:
        file_content: PDF file content as bytes

    Returns:
        Tuple of (success, pages_or_error, message)
        If success is True, returns list of text strings (one per page)
        If success is False, returns error message as string
    """
    try:
        # Validate file size first
        is_valid, size_message = validate_pdf_size(file_content)
        if not is_valid:
            return False, size_message, "File validation failed"

        # Parse PDF
        pdf_file = io.BytesIO(file_content)
        pdf_reader = PdfReader(pdf_file)

        # Extract text from each page
        pages = []
        total_pages = len(pdf_reader.pages)

        for page_num, page in enumerate(pdf_reader.pages):
            text = page.extract_text()
            pages.append(text)

        if not pages:
            return False, "No text could be extracted from PDF", "Empty PDF"

        return True, pages, f"Successfully extracted {total_pages} pages"

    except Exception as e:
        return False, f"Error extracting PDF: {str(e)}", "Extraction failed"


def get_pdf_page_count(file_content: bytes) -> tuple[bool, int, str]:
    """
    Get the total number of pages in a PDF file.

    Args:
        file_content: PDF file content as bytes

    Returns:
        Tuple of (success, page_count, message)
    """
    try:
        pdf_file = io.BytesIO(file_content)
        pdf_reader = PdfReader(pdf_file)
        page_count = len(pdf_reader.pages)
        return True, page_count, f"PDF has {page_count} pages"
    except Exception as e:
        return False, 0, f"Error reading PDF: {str(e)}"
