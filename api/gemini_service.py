"""
Google Generative AI (Gemini) service for converting PDF text to Markdown.
Handles page-by-page processing and result concatenation.
"""
import time
from google import genai
from config.settings import settings
from utils.pdf_processor import extract_pdf_text
from utils.text_similarity import calculate_similarity_score


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


def _extract_usage_tokens(response: object) -> tuple[int | None, int | None, int | None]:
    """Extract token usage from response across SDK field variants."""

    def _as_int(value: object) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    usage_metadata = getattr(response, "usage_metadata", None)
    if usage_metadata is not None:
        prompt_tokens = _as_int(
            getattr(usage_metadata, "prompt_token_count", None)
            or getattr(usage_metadata, "input_tokens", None)
        )
        output_tokens = _as_int(
            getattr(usage_metadata, "candidates_token_count", None)
            or getattr(usage_metadata, "output_tokens", None)
        )
        total_tokens = _as_int(
            getattr(usage_metadata, "total_token_count", None)
            or getattr(usage_metadata, "total_tokens", None)
        )
        return prompt_tokens, output_tokens, total_tokens

    usage = getattr(response, "usage", None)
    if usage is not None:
        prompt_tokens = _as_int(
            getattr(usage, "prompt_tokens", None)
            or getattr(usage, "input_tokens", None)
        )
        output_tokens = _as_int(
            getattr(usage, "completion_tokens", None)
            or getattr(usage, "output_tokens", None)
            or getattr(usage, "candidates_tokens", None)
        )
        total_tokens = _as_int(
            getattr(usage, "total_tokens", None)
            or getattr(usage, "total_token_count", None)
        )
        return prompt_tokens, output_tokens, total_tokens

    return None, None, None


def _estimate_tokens_from_chars(char_count: int) -> int:
    """Approximate token count using a simple chars-per-token heuristic."""
    if char_count <= 0:
        return 0
    # Quick heuristic for mixed technical text: ~4 chars/token.
    return max(1, (char_count + 3) // 4)


def _compact_excerpt(text: str, max_len: int = 180) -> str:
    """Return a normalized short excerpt for UI-level references."""
    normalized = " ".join((text or "").split())
    if len(normalized) <= max_len:
        return normalized
    truncated = normalized[:max_len].rstrip()
    whole_word = truncated.rsplit(" ", 1)[0] if " " in truncated else truncated
    return whole_word + "..."


def _generate_page_markdown_with_metrics(
    prompt: str,
    candidate_models: list[str] | None = None,
) -> tuple[bool, str, str, str, dict]:
    """
    Generate Markdown for a page and collect latency/token metrics.

    Returns:
        (success, markdown, used_model, error_message, metrics)
    """
    models_to_try = candidate_models if candidate_models is not None else settings.get_candidate_models()
    last_error_message = ""

    for model_name in models_to_try:
        normalized_model = _normalize_model_name(model_name)
        start_time = time.perf_counter()
        try:
            response = gemini_client.models.generate_content(
                model=normalized_model,
                contents=prompt,
            )
            latency_ms = (time.perf_counter() - start_time) * 1000
            prompt_tokens, output_tokens, total_tokens = _extract_usage_tokens(response)
            response_text = response.text.strip() if response.text else ""

            metrics = {
                "latency_ms": latency_ms,
                "input_tokens": prompt_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "model": normalized_model,
            }

            if response_text:
                return True, response_text, normalized_model, "", metrics

            last_error_message = (
                f"Model '{normalized_model}' returned an empty response"
            )

        except Exception as error:
            latency_ms = (time.perf_counter() - start_time) * 1000

            if _is_model_not_found_error(error):
                last_error_message = (
                    f"Model '{normalized_model}' unavailable: {str(error)}"
                )
                continue

            return (
                False,
                "",
                normalized_model,
                str(error),
                {
                    "latency_ms": latency_ms,
                    "input_tokens": None,
                    "output_tokens": None,
                    "total_tokens": None,
                    "model": normalized_model,
                },
            )

    if not models_to_try:
        return (
            False,
            "",
            "",
            "No candidate models configured",
            {
                "latency_ms": 0.0,
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
                "model": "",
            },
        )

    return (
        False,
        "",
        "",
        last_error_message or "No model produced content",
        {
            "latency_ms": 0.0,
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "model": "",
        },
    )


def _generate_page_markdown(prompt: str) -> tuple[bool, str, str, str]:
    """
    Generate Markdown for a page trying configured model candidates.

    Returns:
        (success, markdown, used_model, error_message)
    """
    success, markdown, used_model, error_message, _ = _generate_page_markdown_with_metrics(
        prompt
    )
    return success, markdown, used_model, error_message


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
        success, markdown_content, message, _ = process_pdf_with_gemini_with_metrics(
            file_content=file_content
        )
        return success, markdown_content, message

    except Exception as e:
        return False, "", f"Error during Gemini processing: {str(e)}"


def process_pdf_with_gemini_with_metrics(
    file_content: bytes,
    model_override: str | None = None,
    candidate_models_override: list[str] | None = None,
    max_pages: int | None = None,
    ignore_size_limit: bool = False,
    max_chars_per_page: int | None = None,
) -> tuple[bool, str, str, dict]:
    """
    Convert PDF content to Markdown and return detailed benchmark metrics.

    Returns:
        Tuple of (success, markdown_content, message, metrics)
    """
    system_prompt_text = settings.get_system_prompt_text()
    if candidate_models_override:
        requested_models = [
            _normalize_model_name(model_name)
            for model_name in candidate_models_override
            if (model_name or "").strip()
        ]
    elif model_override:
        requested_models = [_normalize_model_name(model_override)]
    else:
        requested_models = settings.get_candidate_models()

    extraction_limit = None
    if ignore_size_limit:
        extraction_limit = settings.benchmark_max_file_size_mb

    success, pages_or_error, extraction_message = extract_pdf_text(
        file_content,
        max_file_size_mb=extraction_limit,
    )

    if not success:
        return False, "", f"PDF extraction failed: {pages_or_error}", {
            "error": str(pages_or_error),
            "extraction_message": extraction_message,
            "requested_model": requested_models[0] if requested_models else None,
            "candidate_models": requested_models,
            "page_metrics": [],
        }

    pages = pages_or_error
    if max_pages is not None and max_pages > 0:
        pages = pages[:max_pages]

    page_count = len(pages)
    markdown_parts: list[str] = []
    page_errors: list[str] = []
    used_models: set[str] = set()
    non_empty_pages = 0
    page_metrics: list[dict] = []

    for page_num, page_text in enumerate(pages, 1):
        if not page_text.strip():
            page_metrics.append(
                {
                    "page_num": page_num,
                    "success": False,
                    "skipped_empty": True,
                    "used_model": "",
                    "error": "Empty page",
                    "latency_ms": 0.0,
                    "input_tokens": None,
                    "output_tokens": None,
                    "total_tokens": None,
                    "similarity": None,
                    "input_chars": 0,
                    "output_chars": 0,
                    "estimated_input_tokens": 0,
                    "estimated_output_tokens": 0,
                    "token_count_method": "none",
                }
            )
            continue

        non_empty_pages += 1
        page_text_for_prompt = page_text
        if max_chars_per_page is not None and max_chars_per_page > 0:
            page_text_for_prompt = page_text[:max_chars_per_page]

        try:
            prompt = f"""Using the following system instruction:
{system_prompt_text}

Convert the following PDF page ({page_num} of {page_count}) to high-quality Markdown.
Preserve all formatting, structure, lists, and hierarchy. Use appropriate Markdown syntax.

---
{page_text_for_prompt}
---

Provide ONLY the Markdown output, no additional commentary."""

            page_success, markdown_text, used_model, page_error, page_usage = (
                _generate_page_markdown_with_metrics(prompt, requested_models)
            )

            if page_success:
                markdown_parts.append(markdown_text)
                used_models.add(used_model)
                similarity = calculate_similarity_score(page_text_for_prompt, markdown_text)
            else:
                similarity = 0.0
                page_errors.append(f"Page {page_num}: {page_error}")

            estimated_input_tokens = _estimate_tokens_from_chars(len(prompt))
            estimated_output_tokens = _estimate_tokens_from_chars(len(markdown_text))
            token_count_method = (
                "api" if page_usage.get("input_tokens") is not None else "estimated_chars"
            )

            page_metrics.append(
                {
                    "page_num": page_num,
                    "success": page_success,
                    "skipped_empty": False,
                    "used_model": used_model,
                    "error": page_error if not page_success else "",
                    "latency_ms": page_usage.get("latency_ms", 0.0),
                    "input_tokens": page_usage.get("input_tokens"),
                    "output_tokens": page_usage.get("output_tokens"),
                    "total_tokens": page_usage.get("total_tokens"),
                    "similarity": similarity,
                    "input_chars": len(page_text_for_prompt),
                    "output_chars": len(markdown_text),
                    "truncated_input": len(page_text_for_prompt) < len(page_text),
                    "estimated_input_tokens": estimated_input_tokens,
                    "estimated_output_tokens": estimated_output_tokens,
                    "token_count_method": token_count_method,
                    "source_excerpt": _compact_excerpt(page_text_for_prompt),
                    "output_excerpt": _compact_excerpt(markdown_text),
                }
            )

        except Exception as error:
            page_errors.append(f"Page {page_num}: {str(error)}")
            page_metrics.append(
                {
                    "page_num": page_num,
                    "success": False,
                    "skipped_empty": False,
                    "used_model": "",
                    "error": str(error),
                    "latency_ms": 0.0,
                    "input_tokens": None,
                    "output_tokens": None,
                    "total_tokens": None,
                    "similarity": 0.0,
                    "input_chars": len(page_text_for_prompt),
                    "output_chars": 0,
                    "truncated_input": len(page_text_for_prompt) < len(page_text),
                    "estimated_input_tokens": _estimate_tokens_from_chars(len(page_text_for_prompt)),
                    "estimated_output_tokens": 0,
                    "token_count_method": "estimated_chars",
                    "source_excerpt": _compact_excerpt(page_text_for_prompt),
                    "output_excerpt": "",
                }
            )

    if non_empty_pages == 0:
        return False, "", "No non-empty pages found in PDF", {
            "requested_model": requested_models[0] if requested_models else None,
            "candidate_models": requested_models,
            "page_metrics": page_metrics,
            "extraction_message": extraction_message,
            "total_pages": page_count,
        }

    full_markdown = "\n\n---\n\n".join(markdown_parts)

    if not full_markdown.strip():
        if page_errors:
            return (
                False,
                "",
                "No pages were converted successfully. " + "; ".join(page_errors[:3]),
                {
                    "requested_model": requested_models[0] if requested_models else None,
                    "candidate_models": requested_models,
                    "page_metrics": page_metrics,
                    "extraction_message": extraction_message,
                    "total_pages": page_count,
                },
            )
        return False, "", "No Markdown content was generated", {
            "requested_model": requested_models[0] if requested_models else None,
            "candidate_models": requested_models,
            "page_metrics": page_metrics,
            "extraction_message": extraction_message,
            "total_pages": page_count,
        }

    successful_pages = len(markdown_parts)
    model_info = ", ".join(sorted(used_models)) if used_models else "unknown"
    message = (
        f"Successfully converted {successful_pages}/{non_empty_pages} non-empty "
        f"pages to Markdown using: {model_info}"
    )

    if page_errors:
        message += f". Skipped {len(page_errors)} pages with errors"

    similarity_values = [
        metric["similarity"]
        for metric in page_metrics
        if metric.get("similarity") is not None and not metric.get("skipped_empty")
    ]
    avg_similarity = (
        sum(similarity_values) / len(similarity_values) if similarity_values else 0.0
    )

    latencies = [
        float(metric["latency_ms"])
        for metric in page_metrics
        if not metric.get("skipped_empty")
    ]
    total_latency_ms = sum(latencies)

    input_tokens_values = [
        metric["input_tokens"]
        for metric in page_metrics
        if isinstance(metric.get("input_tokens"), int)
    ]
    output_tokens_values = [
        metric["output_tokens"]
        for metric in page_metrics
        if isinstance(metric.get("output_tokens"), int)
    ]
    total_tokens_values = [
        metric["total_tokens"]
        for metric in page_metrics
        if isinstance(metric.get("total_tokens"), int)
    ]
    estimated_input_tokens_values = [
        int(metric.get("estimated_input_tokens", 0))
        for metric in page_metrics
        if not metric.get("skipped_empty")
    ]
    estimated_output_tokens_values = [
        int(metric.get("estimated_output_tokens", 0))
        for metric in page_metrics
        if not metric.get("skipped_empty")
    ]

    input_tokens_total = sum(input_tokens_values) if input_tokens_values else None
    output_tokens_total = sum(output_tokens_values) if output_tokens_values else None
    total_tokens_total = sum(total_tokens_values) if total_tokens_values else None
    estimated_input_tokens_total = sum(estimated_input_tokens_values)
    estimated_output_tokens_total = sum(estimated_output_tokens_values)

    effective_input_tokens_total = (
        input_tokens_total if input_tokens_total is not None else estimated_input_tokens_total
    )
    effective_output_tokens_total = (
        output_tokens_total if output_tokens_total is not None else estimated_output_tokens_total
    )
    effective_total_tokens_total = effective_input_tokens_total + effective_output_tokens_total

    metrics = {
        "requested_model": requested_models[0] if requested_models else None,
        "candidate_models": requested_models,
        "used_models": sorted(used_models),
        "extraction_message": extraction_message,
        "total_pages": page_count,
        "non_empty_pages": non_empty_pages,
        "successful_pages": successful_pages,
        "failed_pages": len(page_errors),
        "average_similarity": avg_similarity,
        "total_latency_ms": total_latency_ms,
        "input_tokens_total": input_tokens_total,
        "output_tokens_total": output_tokens_total,
        "total_tokens_total": total_tokens_total,
        "estimated_input_tokens_total": estimated_input_tokens_total,
        "estimated_output_tokens_total": estimated_output_tokens_total,
        "effective_input_tokens_total": effective_input_tokens_total,
        "effective_output_tokens_total": effective_output_tokens_total,
        "effective_total_tokens_total": effective_total_tokens_total,
        "token_count_method": (
            "api" if input_tokens_total is not None and output_tokens_total is not None else "estimated_chars"
        ),
        "token_usage_available": bool(input_tokens_values or output_tokens_values),
        "page_metrics": page_metrics,
        "errors": page_errors,
        "internal_context_window_tokens": None,
    }

    return True, full_markdown, message, metrics


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
