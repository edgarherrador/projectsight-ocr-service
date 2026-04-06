"""
Google Generative AI (Gemini) service for converting PDF text to Markdown.
Handles page-by-page processing and result concatenation.
"""
from google import genai
from config.settings import settings
from utils.pdf_processor import extract_pdf_text


# Configure Gemini API client
gemini_client = genai.Client(api_key=settings.gemini_api_key)


def _normalize_model_name(model_name: str) -> str:
    """Normalize model names for comparisons and API calls."""
    cleaned = model_name.strip()
    if cleaned.startswith("models/"):
        cleaned = cleaned[len("models/") :]
    return cleaned


def _is_model_not_found_error(error: Exception) -> bool:
    """Detect model-not-found errors from Gemini responses."""
    error_text = str(error).lower()
    return (
        "404" in error_text
        and "model" in error_text
        and "not found" in error_text
    )


def _supports_generate_content(model: object) -> bool:
    """Check whether a model supports generateContent."""
    raw_methods = (
        getattr(model, "supported_generation_methods", None)
        or getattr(model, "supported_actions", None)
        or []
    )

    for method in raw_methods:
        normalized = str(method).replace(" ", "").lower()
        if normalized.endswith("generatecontent"):
            return True

    return False


def _generate_page_markdown(prompt: str) -> tuple[bool, str, str, str]:
    """
    Generate Markdown for a page trying configured model candidates.

    Returns:
        (success, markdown, used_model, error_message)
    """
    candidate_models = settings.get_candidate_models()
    last_error_message = ""

    for model_name in candidate_models:
        normalized_model = _normalize_model_name(model_name)
        try:
            response = gemini_client.models.generate_content(
                model=normalized_model,
                contents=prompt,
            )
            response_text = response.text.strip() if response.text else ""
            if response_text:
                return True, response_text, normalized_model, ""

            last_error_message = (
                f"Model '{normalized_model}' returned an empty response"
            )
        except Exception as error:
            if _is_model_not_found_error(error):
                last_error_message = (
                    f"Model '{normalized_model}' unavailable: {str(error)}"
                )
                continue

            return False, "", normalized_model, str(error)

    if not candidate_models:
        return False, "", "", "No candidate models configured"

    return False, "", "", last_error_message or "No model produced content"


def list_available_models_for_generate_content() -> tuple[bool, list[str], str]:
    """
    List models accessible by the API key that support generateContent.

    Returns:
        Tuple of (success, models, message)
    """
    try:
        available_models: list[str] = []

        for model in gemini_client.models.list():
            model_name = getattr(model, "name", "")
            if not model_name:
                continue

            if _supports_generate_content(model):
                normalized_name = _normalize_model_name(model_name)
                if normalized_name not in available_models:
                    available_models.append(normalized_name)

        available_models.sort()

        if not available_models:
            return False, [], "No models with generateContent support found"

        return (
            True,
            available_models,
            f"Found {len(available_models)} models supporting generateContent",
        )
    except Exception as error:
        return False, [], f"Failed to list models: {str(error)}"


def process_pdf_with_gemini(file_content: bytes) -> tuple[bool, str, str]:
    """
    Convert PDF content to Markdown using Gemini 3.1 Pro, processing page by page.

    Args:
        file_content: PDF file content as bytes

    Returns:
        Tuple of (success, markdown_content, message)
    """
    try:
        system_prompt_text = settings.get_system_prompt_text()

        # Extract PDF text page by page
        success, pages_or_error, extraction_message = extract_pdf_text(file_content)

        if not success:
            return False, "", f"PDF extraction failed: {pages_or_error}"

        pages = pages_or_error
        page_count = len(pages)

        # Process pages individually and collect successful conversions.
        markdown_parts: list[str] = []
        page_errors: list[str] = []
        used_models: set[str] = set()
        non_empty_pages = 0

        for page_num, page_text in enumerate(pages, 1):
            if not page_text.strip():
                # Skip empty pages
                continue

            non_empty_pages += 1

            try:
                # Create prompt for this page
                prompt = f"""Using the following system instruction:
{system_prompt_text}

Convert the following PDF page ({page_num} of {page_count}) to high-quality Markdown.
Preserve all formatting, structure, lists, and hierarchy. Use appropriate Markdown syntax.

---
{page_text}
---

Provide ONLY the Markdown output, no additional commentary."""

                page_success, markdown_text, used_model, page_error = (
                    _generate_page_markdown(prompt)
                )
                if page_success:
                    markdown_parts.append(markdown_text)
                    used_models.add(used_model)
                else:
                    page_errors.append(
                        f"Page {page_num}: {page_error}"
                    )

            except Exception as e:
                print(f"Error processing page {page_num}: {str(e)}")
                page_errors.append(f"Page {page_num}: {str(e)}")

        if non_empty_pages == 0:
            return False, "", "No non-empty pages found in PDF"

        # Concatenate all pages
        full_markdown = "\n\n---\n\n".join(markdown_parts)

        if not full_markdown.strip():
            if page_errors:
                return (
                    False,
                    "",
                    "No pages were converted successfully. " + "; ".join(page_errors[:3]),
                )
            return False, "", "No Markdown content was generated"

        successful_pages = len(markdown_parts)
        model_info = ", ".join(sorted(used_models)) if used_models else "unknown"
        message = (
            f"Successfully converted {successful_pages}/{non_empty_pages} non-empty "
            f"pages to Markdown using: {model_info}"
        )

        if page_errors:
            message += f". Skipped {len(page_errors)} pages with errors"

        return True, full_markdown, message

    except Exception as e:
        return False, "", f"Error during Gemini processing: {str(e)}"


def process_single_page(page_text: str, page_num: int, total_pages: int) -> str:
    """
    Process a single PDF page with Gemini.

    Args:
        page_text: Extracted text from the page
        page_num: Current page number
        total_pages: Total number of pages

    Returns:
        Markdown-formatted page content
    """
    try:
        system_prompt_text = settings.get_system_prompt_text()

        prompt = f"""Using the following system instruction:
    {system_prompt_text}

Convert the following PDF page ({page_num} of {total_pages}) to high-quality Markdown.
Preserve all formatting, structure, lists, and hierarchy. Use appropriate Markdown syntax.

---
{page_text}
---

Provide ONLY the Markdown output, no additional commentary."""

        success, markdown_text, _, error_message = _generate_page_markdown(prompt)
        if success:
            return markdown_text

        return f"\n[Error processing page {page_num}: {error_message}]\n"

    except Exception as e:
        print(f"Error processing page {page_num}: {str(e)}")
        return f"\n[Error processing page {page_num}: {str(e)}]\n"
