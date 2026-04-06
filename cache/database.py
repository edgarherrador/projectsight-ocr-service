"""
Database setup and management for caching PDF processing results.
Uses SQLite for local persistent storage.
"""
import hashlib
from datetime import datetime
from pathlib import Path
from sqlalchemy import create_engine, Column, String, Integer, DateTime, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from config.settings import settings

# Database setup
Base = declarative_base()

# Ensure cache directory exists
cache_dir = Path(settings.database_path).parent
cache_dir.mkdir(exist_ok=True)

# Create database engine
engine = create_engine(f"sqlite:///{settings.database_path}", echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class PDFCache(Base):
    """SQLAlchemy model for cached PDF conversions."""

    __tablename__ = "pdf_cache"

    pdf_id = Column(String, primary_key=True, index=True)
    file_name = Column(String, index=True)
    content_hash = Column(String, unique=True, index=True)
    markdown_content = Column(String)
    pages_processed = Column(Integer)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    is_cached = Column(Boolean, default=False)


# Create all tables
Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency for FastAPI to get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def calculate_file_hash(file_content: bytes) -> str:
    """Calculate SHA256 hash of file content."""
    return hashlib.sha256(file_content).hexdigest()


def get_cached_result(file_content: bytes) -> dict | None:
    """
    Retrieve cached result if PDF has been processed before.

    Args:
        file_content: PDF file content as bytes

    Returns:
        Dictionary with cached result or None if not found
    """
    try:
        content_hash = calculate_file_hash(file_content)
        db = SessionLocal()
        cached = db.query(PDFCache).filter_by(content_hash=content_hash).first()
        db.close()

        if cached:
            return {
                "pdf_id": cached.pdf_id,
                "markdown_content": cached.markdown_content,
                "pages_processed": cached.pages_processed,
                "timestamp": cached.timestamp,
                "is_cached": True,
            }
        return None
    except SQLAlchemyError as e:
        print(f"Database error while retrieving cache: {e}")
        return None


def save_to_cache(
    pdf_id: str,
    file_name: str,
    file_content: bytes,
    markdown_content: str,
    pages_processed: int,
) -> bool:
    """
    Save PDF conversion result to cache.

    Args:
        pdf_id: Unique identifier for the PDF
        file_name: Original file name
        file_content: PDF content as bytes
        markdown_content: Converted Markdown
        pages_processed: Number of pages processed

    Returns:
        True if saved successfully, False otherwise
    """
    try:
        content_hash = calculate_file_hash(file_content)
        db = SessionLocal()

        # Check if already exists
        existing = db.query(PDFCache).filter_by(content_hash=content_hash).first()
        if existing:
            db.close()
            return True

        cache_entry = PDFCache(
            pdf_id=pdf_id,
            file_name=file_name,
            content_hash=content_hash,
            markdown_content=markdown_content,
            pages_processed=pages_processed,
            timestamp=datetime.utcnow(),
            is_cached=False,
        )
        db.add(cache_entry)
        db.commit()
        db.close()
        return True
    except SQLAlchemyError as e:
        print(f"Database error while saving to cache: {e}")
        return False


def get_history() -> list[dict]:
    """
    Retrieve all cached PDFs from history.

    Returns:
        List of dictionaries containing PDF cache entries
    """
    try:
        db = SessionLocal()
        cached_pdfs = (
            db.query(PDFCache).order_by(PDFCache.timestamp.desc()).all()
        )
        db.close()

        return [
            {
                "pdf_id": pdf.pdf_id,
                "file_name": pdf.file_name,
                "timestamp": pdf.timestamp,
                "pages_processed": pdf.pages_processed,
                "is_cached": True,
            }
            for pdf in cached_pdfs
        ]
    except SQLAlchemyError as e:
        print(f"Database error while retrieving history: {e}")
        return []
