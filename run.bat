@echo off
REM Startup script for PDF to Markdown Converter
REM Starts both FastAPI backend and Gradio frontend

echo.
echo ========================================
echo PDF to Markdown Converter - Startup
echo ========================================
echo.

REM Check if .env file exists
if not exist ".env" (
    echo ⚠️  WARNING: .env file not found!
    echo Please create a .env file based on .env.example
    echo.
    echo Example:
    echo   copy .env.example .env
    echo   [Edit .env with your GEMINI_API_KEY]
    echo.
    pause
    exit /b 1
)

REM Check if venv is activated
if not defined VIRTUAL_ENV (
    echo Activating virtual environment...
    call .venv\Scripts\activate.bat
)

echo ✓ Environment activated
echo.

REM Start FastAPI server in background
echo Starting FastAPI server on http://127.0.0.1:8000...
start cmd /k "uv run uvicorn api.main:app --reload --host 127.0.0.1 --port 8000"

REM Wait a bit for API to start
timeout /t 2 /nobreak

REM Start Gradio server
echo Starting Gradio interface (preferred port: http://127.0.0.1:7860)...
echo Note: if 7860 is busy, web/app.py will auto-select the next available port.
start cmd /k "uv run python web/app.py"

echo.
echo ========================================
echo Servers starting...
echo FastAPI Swagger: http://localhost:8000/docs
echo Gradio Interface: check the Gradio terminal for the final URL/port
echo ========================================
echo.

pause
