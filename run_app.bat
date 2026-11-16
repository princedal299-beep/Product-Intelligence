@echo off
cd /d "%~dp0"
echo ========================================================
echo Starting Product Intelligence Assistant Services...
echo ========================================================

:: Activate virtual environment if present
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

echo [1/3] Launching FastAPI Backend on port 8000...
start "FastAPI Backend (Port 8000)" cmd /k "uvicorn api.app:app --host 127.0.0.1 --port 8000 --reload"
timeout /t 2 /nobreak >nul

echo [2/3] Launching MCP Tool Server on port 8001...
start "MCP Server (Port 8001)" cmd /k "python mcp_service/tools.py"
timeout /t 2 /nobreak >nul

echo [3/3] Launching Streamlit UI on port 8501...
start "Streamlit UI (Port 8501)" cmd /k "streamlit run main.py"

echo ========================================================
echo All 3 services launched successfully!
echo   - Streamlit UI:  http://localhost:8501
echo   - FastAPI API:   http://localhost:8000
echo   - MCP Server:    http://localhost:8001
echo ========================================================
echo Note: Keep the 3 terminal windows open while using the app.
