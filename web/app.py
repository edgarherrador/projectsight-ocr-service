"""
Gradio web interface for PDF to Markdown conversion.
Provides a user-friendly web UI that consumes the FastAPI backend.
"""
import gradio as gr
import requests
from pathlib import Path
from datetime import datetime
from config.settings import settings

# API base URL
API_BASE_URL = f"http://{settings.api_host}:{settings.api_port}"

# Global state for UI
class AppState:
    """Application state management."""
    last_result = None
    processing = False


INDICATOR_LABELS = {
    "similarity": "Text similarity",
    "cer_estimate": "Estimated character error rate (CER)",
    "structural_fidelity_proxy": "Document structure fidelity (proxy)",
}


INDICATOR_HELP = {
    "similarity": "Compares OCR output vs extracted source text. Higher is better.",
    "cer_estimate": "Approximate character-level error ratio. Lower is better.",
    "structural_fidelity_proxy": "Proxy signal for preserving lists, headers and layout. Higher is better.",
}


def _pretty_indicator_name(raw_name: str) -> str:
    """Convert internal metric keys into user-friendly labels."""
    return INDICATOR_LABELS.get(raw_name, raw_name.replace("_", " ").title())


def _format_duration_mmss(latency_ms: float | int | None) -> str:
    """Format milliseconds to mm:ss string."""
    if latency_ms is None:
        return "N/A"

    try:
        total_seconds = max(0, int(round(float(latency_ms) / 1000.0)))
    except (TypeError, ValueError):
        return "N/A"

    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:02d}"


def _format_timestamp(value: str | None) -> str:
    """Format API timestamp in a stable human-readable UTC form."""
    if not value:
        return "N/A"

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%Y-%m-%d %H:%M:%S UTC")
    except ValueError:
        return value


def _format_quality_summary(metrics_payload: dict | None) -> str:
    """Build a human-readable quality summary with critical levels."""
    if not metrics_payload:
        return "Quality summary unavailable for this document."

    decision = metrics_payload.get("decision")
    if not decision:
        return "Judge not executed for this document based on current policy."

    semaphore = decision.get("semaphore", "AMBER")
    icon = {"GREEN": "🟢", "AMBER": "🟠", "RED": "🔴"}.get(semaphore, "🟠")

    levels = metrics_payload.get("levels", [])
    level_lines: list[str] = []
    level_icon = {"GREEN": "🟢", "AMBER": "🟠", "RED": "🔴"}
    for item in levels:
        name = item.get("score_name", "unknown")
        severity = item.get("level", "AMBER")
        value = item.get("value")
        pretty_name = _pretty_indicator_name(name)
        level_lines.append(
            f"- {level_icon.get(severity, '🟠')} **{pretty_name}**: {value} ({severity})"
        )

    details = "\n".join(level_lines) if level_lines else "- No per-metric levels available"

    indicator_help_lines: list[str] = []
    for key in ["similarity", "cer_estimate", "structural_fidelity_proxy"]:
        indicator_help_lines.append(
            f"- **{_pretty_indicator_name(key)}**: {INDICATOR_HELP[key]}"
        )
    indicator_help_text = "\n".join(indicator_help_lines)

    page_references = metrics_payload.get("page_review_references", [])
    reference_lines: list[str] = []
    for item in page_references:
        page_num = item.get("page_num")
        severity = item.get("severity", "AMBER")
        similarity = item.get("similarity")
        why = item.get("why", "Review suggested")
        excerpt = item.get("source_excerpt")
        excerpt_suffix = f"\n  Excerpt: \"{excerpt}\"" if excerpt else ""
        reference_lines.append(
            f"- **Page {page_num}** ({severity}, similarity={similarity}): {why}{excerpt_suffix}"
        )

    references_text = (
        "\n".join(reference_lines)
        if reference_lines
        else "- No specific page references available"
    )

    return (
        f"{icon} **Quality Verdict: {decision.get('verdict', 'REVIEW_MANUAL')}**\n"
        f"- **Reason**: {decision.get('reason', 'No reason provided')}\n"
        f"- **Trigger**: {decision.get('run_trigger', 'unknown')}\n"
        f"- **Critical Indicators**:\n{details}"
        f"\n- **What each indicator means**:\n{indicator_help_text}"
        f"\n- **Where to review in PDF**:\n{references_text}"
    )


def _build_metrics_table(metrics_payload: dict | None) -> list[list[str]]:
    """Create 2-column table rows for display in Gradio Dataframe."""
    if not metrics_payload:
        return [["status", "no_metrics"]]

    rows: list[list[str]] = []

    keys = [
        "similarity",
        "cer_estimate",
        "wer_estimate",
        "latency_ms_total",
        "effective_input_tokens_total",
        "effective_output_tokens_total",
        "estimated_total_cost_usd",
        "context_window_utilization_pct",
        "output_window_utilization_pct",
    ]
    for key in keys:
        if key == "latency_ms_total":
            rows.append([key, str(metrics_payload.get(key))])
            rows.append(["latency_mmss", _format_duration_mmss(metrics_payload.get(key))])
            continue
        rows.append([key, str(metrics_payload.get(key))])

    review_pages = metrics_payload.get("review_pages", [])
    if review_pages:
        rows.append(["review_pages", ", ".join(str(page) for page in review_pages)])

    levels = metrics_payload.get("levels", [])
    for level in levels:
        name = level.get("score_name", "unknown")
        value = level.get("value")
        severity = level.get("level", "AMBER")
        rows.append([f"level:{_pretty_indicator_name(name)}", f"{severity} ({value})"])

    return rows


def convert_pdf(pdf_file, judge_mode):
    """
    Convert a PDF file by sending it to the FastAPI backend.

    Args:
        pdf_file: Uploaded PDF file from Gradio.
        judge_mode: Selected evaluation mode used by the backend when
            generating quality assessment results.

    Returns:
        Tuple containing:
            - markdown_content: Converted Markdown output.
            - status_message: User-facing status or error message.
            - quality_summary: Formatted summary of quality metrics.
            - metrics_table: 2-column metrics data for Gradio Dataframe display.
    """
    if pdf_file is None:
        return "", "❌ Please upload a PDF file", "", [["status", "no_file"]]

    try:
        AppState.processing = True

        # Read file bytes
        with open(pdf_file, "rb") as f:
            pdf_content = f.read()

        file_size_mb = len(pdf_content) / (1024 * 1024)
        if file_size_mb > settings.max_file_size_mb:
            return (
                "",
                (
                    f"❌ **Error**: File size {file_size_mb:.2f} MB exceeds "
                    f"maximum allowed size of {settings.max_file_size_mb} MB"
                ),
                "",
                [["status", "size_limit_exceeded"]],
            )

        # Send to API
        files = {
            "file": (Path(pdf_file).name, pdf_content, "application/pdf")
        }
        response = requests.post(
            f"{API_BASE_URL}/api/convert",
            files=files,
            params={"judge_mode": judge_mode},
        )

        if response.status_code == 200:
            result = response.json()
            AppState.last_result = result

            # Build status message
                f"- **Converted At**: {_format_timestamp(result.get('timestamp'))}"
            status_msg = (
                f"✨ **Conversion Successful** {cached_marker}\n"
                f"- **PDF**: {result['file_name']}\n"
                f"- **Pages**: {result['pages_processed']}\n"
                f"- **ID**: `{result['pdf_id'][:16]}...`\n"
                f"- **Processed At**: {_format_timestamp(result.get('timestamp'))}"
            )

            quality_summary = "Quality summary unavailable."
            metrics_rows = [["status", "not_loaded"]]
            try:
                metrics_response = requests.get(
                    f"{API_BASE_URL}/api/metrics/{result['pdf_id']}",
                    timeout=10,
                )
                if metrics_response.status_code == 200:
                    metrics_payload = metrics_response.json()
                    quality_summary = _format_quality_summary(metrics_payload)
                    metrics_rows = _build_metrics_table(metrics_payload)
                    status_msg += (
                        f"\n- **Processing Time (mm:ss)**: "
                        f"{_format_duration_mmss(metrics_payload.get('latency_ms_total'))}"
                    )
                else:
                    quality_summary = "No metrics found for this PDF yet."
                    metrics_rows = [["status", "no_metrics_record"]]
            except Exception as metric_error:
                quality_summary = f"Metrics lookup failed: {str(metric_error)}"
                metrics_rows = [["status", "metrics_lookup_failed"]]

            return result["markdown_content"], status_msg, quality_summary, metrics_rows

        else:
            error_data = response.json()
            error_msg = error_data.get("detail", error_data.get("error", "Unknown error"))
            return "", f"❌ **Error**: {error_msg}", "", [["status", "api_error"]]

    except requests.exceptions.ConnectionError:
        return "", (
            f"❌ **Connection Error**: Cannot reach API at {API_BASE_URL}\n"
            f"Make sure FastAPI server is running: `uvicorn api.main:app --reload`"
        ), "", [["status", "connection_error"]]
    except Exception as e:
        return "", f"❌ **Error**: {str(e)}", "", [["status", "unexpected_error"]]
    finally:
        AppState.processing = False


def copy_markdown(markdown_text):
    """Copy markdown to clipboard (client-side handled by Gradio)."""
    if markdown_text:
        return "✅ Markdown copied to clipboard!"
    return "❌ No markdown to copy"


def load_history():
    """Load processing history from API."""
    try:
        response = requests.get(f"{API_BASE_URL}/api/history")

        if response.status_code == 200:
            data = response.json()
            history = data.get("history", [])

            if not history:
                return "No PDFs processed yet."

            # Format history as markdown table
            history_md = "| File Name | Pages | Date | Status |\n|-----------|-------|------|--------|\n"

            for item in history:
                file_name = item["file_name"]
                pages = item["pages_processed"]
                timestamp = item["timestamp"]
                status = "📦 Cached"

                history_md += f"| {file_name} | {pages} | {timestamp} | {status} |\n"

            return history_md

        else:
            return "❌ Failed to load history"

def clear_server_cache():
        return f"❌ Cannot reach API at {API_BASE_URL}"
    except Exception as e:
        return f"❌ Error loading history: {str(e)}"


def clear_history():
    """Clear server cache and metrics from API."""
    try:
        response = requests.delete(
            f"{API_BASE_URL}/api/cache",
            params={"include_metrics": True},
            timeout=15,
        )
        if response.status_code == 200:
            payload = response.json()
            return (
                "✅ Cache cleared successfully\n"
                f"- PDFs removed: {payload.get('deleted_pdfs', 0)}\n"
                f"- Metrics removed: {payload.get('deleted_metrics', 0)}"
            )

        error_data = response.json()
        error_msg = error_data.get("detail", "Unknown error")
        return f"❌ Failed to clear cache: {error_msg}"
    except requests.exceptions.ConnectionError:
        return f"❌ Cannot reach API at {API_BASE_URL}"
    except Exception as e:
        return f"❌ Error clearing cache: {str(e)}"


def check_api_status():
    """Check if API is running."""
    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=2)
        if response.status_code == 200:
            return "🟢 API is running"
        else:
            return "🔴 API returned unexpected status"
    except requests.exceptions.ConnectionError:
        return f"🔴 Cannot connect to API at {API_BASE_URL}"
    except requests.exceptions.Timeout:
        return "🟡 API timeout"
    except Exception as e:
        return f"🔴 Error: {str(e)}"


# Create Gradio interface
def create_interface():
    """Create Gradio interface blocks."""

    with gr.Blocks(
        title="PDF to Markdown Converter",
    ) as demo:

        gr.Markdown(
            """
        # 📄 PDF to Markdown Converter
        
        Convert your PDF files to beautifully formatted Markdown using AI.
        Powered by Google Gemini 3.1 Pro with intelligent caching.
        
        **Features:**
        - 🤖 AI-powered PDF text extraction and formatting
        - 💾 Intelligent caching (no re-processing of same files)
        - 📊 Page-by-page processing
        - 🚀 Fast results from cache
        - 📋 View processing history
        - 📏 Max upload size: 30 MB
        """
        )

        # API Status
        with gr.Row():
            api_status = gr.Textbox(
                label="API Status",
                value=check_api_status(),
                interactive=False,
            )
            refresh_status_btn = gr.Button("🔄 Refresh Status")
            refresh_status_btn.click(check_api_status, outputs=[api_status])

        gr.Markdown("---")

        # Main conversion area
        with gr.Row():
            with gr.Column(scale=1):
                pdf_input = gr.File(
                    label="📤 Upload PDF",
                    file_count="single",
                    file_types=[".pdf"],
                )
                convert_btn = gr.Button(
                    "🚀 Convert to Markdown",
                    variant="primary",
                    scale=1,
                )
                judge_mode_input = gr.Radio(
                    choices=["auto", "force", "skip"],
                    value="auto",
                    label="Judge Mode",
                    info="auto: policy, force: always run, skip: disable for this request",
                )

            with gr.Column(scale=2):
                status_output = gr.Markdown(
                    value="Upload a PDF and click 'Convert to Markdown' to get started.",
                )

            gr.Markdown("---")

        # Output area
        with gr.Row():
            markdown_output = gr.Textbox(
                label="📝 Markdown Output",
                lines=10,
                max_lines=30,
                interactive=True,
            )

        with gr.Row():
            quality_summary_output = gr.Markdown(
                value="Quality summary will appear after conversion.",
            )

        with gr.Row():
            metrics_table_output = gr.Dataframe(
                headers=["metric", "value"],
                value=[["status", "waiting"]],
                interactive=False,
                label="📊 OCR Quality Metrics",
                row_count=(8, "dynamic"),
                col_count=(2, "fixed"),
            )

        # Actions
        with gr.Row():
            copy_btn = gr.Button("📋 Copy Markdown")
            download_btn = gr.File(
                label="📥 Download Markdown",
                interactive=False,
            )

        gr.Markdown("---")

        # History section
        with gr.Row():
            with gr.Column():
                history_refresh_btn = gr.Button("📜 Load History")
                clear_history_btn = gr.Button("🗑️ Clear Server Cache")

        history_output = gr.Markdown(
            value="No history loaded yet.",
        )

        # Connect events
        convert_btn.click(
            convert_pdf,
            inputs=[pdf_input, judge_mode_input],
            outputs=[
                markdown_output,
                status_output,
                quality_summary_output,
                metrics_table_output,
            ],
        )

        copy_btn.click(
            copy_markdown,
            inputs=[markdown_output],
            outputs=[status_output],
        )

        history_refresh_btn.click(
            load_history,
            outputs=[history_output],
        )

        clear_history_btn.click(
            clear_history,
            outputs=[status_output],
        )

        # Footer
        gr.Markdown(
            """
        ---
        
        **📚 API Documentation:** Visit [http://localhost:8000/docs](http://localhost:8000/docs) for detailed API information.
        
        **🔗 Endpoints:**
        - `POST /api/convert` - Convert PDF to Markdown
        - `GET /api/history` - Get processing history
        - `GET /api/convert/{pdf_id}` - Retrieve cached result
        - `DELETE /api/cache` - Clear cache and metrics
        
        **Made with ❤️ by ProjectSight**
        """
        )

    return demo


if __name__ == "__main__":
    demo = create_interface()
    demo.launch(
        theme=gr.themes.Soft(),
        server_name=settings.gradio_host,
        server_port=settings.gradio_port,
        share=False,
    )
