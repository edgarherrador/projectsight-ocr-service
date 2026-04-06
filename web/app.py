"""
Gradio web interface for PDF to Markdown conversion.
Provides a user-friendly web UI that consumes the FastAPI backend.
"""
import gradio as gr
import requests
from pathlib import Path
from config.settings import settings

# API base URL
API_BASE_URL = f"http://{settings.api_host}:{settings.api_port}"

# Global state for UI
class AppState:
    """Application state management."""
    last_result = None
    processing = False


def convert_pdf(pdf_file):
    """
    Convert PDF file by sending to FastAPI backend.

    Args:
        pdf_file: Uploaded PDF file from Gradio

    Returns:
        Tuple of (markdown_content, status_message)
    """
    if pdf_file is None:
        return "", "❌ Please upload a PDF file"

    try:
        AppState.processing = True

        # Read file bytes
        with open(pdf_file, "rb") as f:
            pdf_content = f.read()

        # Send to API
        files = {
            "file": (Path(pdf_file).name, pdf_content, "application/pdf")
        }
        response = requests.post(f"{API_BASE_URL}/api/convert", files=files)

        if response.status_code == 200:
            result = response.json()
            AppState.last_result = result

            # Build status message
            cached_marker = "✅ (From Cache)" if result["is_cached"] else "🆕 (Newly Generated)"
            status_msg = (
                f"✨ **Conversion Successful** {cached_marker}\n"
                f"- **PDF**: {result['file_name']}\n"
                f"- **Pages**: {result['pages_processed']}\n"
                f"- **ID**: `{result['pdf_id'][:16]}...`\n"
                f"- **Time**: {result['timestamp']}"
            )

            return result["markdown_content"], status_msg

        else:
            error_data = response.json()
            error_msg = error_data.get("detail", error_data.get("error", "Unknown error"))
            return "", f"❌ **Error**: {error_msg}"

    except requests.exceptions.ConnectionError:
        return "", (
            f"❌ **Connection Error**: Cannot reach API at {API_BASE_URL}\n"
            f"Make sure FastAPI server is running: `uvicorn api.main:app --reload`"
        )
    except Exception as e:
        return "", f"❌ **Error**: {str(e)}"
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

    except requests.exceptions.ConnectionError:
        return f"❌ Cannot reach API at {API_BASE_URL}"
    except Exception as e:
        return f"❌ Error loading history: {str(e)}"


def clear_history():
    """Clear history (note: this is client-side only, database remains)."""
    return "Local history cache cleared (database remains for caching)"


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
                clear_history_btn = gr.Button("🗑️ Clear Local Cache")

        history_output = gr.Markdown(
            value="No history loaded yet.",
        )

        # Connect events
        convert_btn.click(
            convert_pdf,
            inputs=[pdf_input],
            outputs=[markdown_output, status_output],
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
