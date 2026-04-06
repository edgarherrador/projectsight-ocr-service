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
