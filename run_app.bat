@echo off
setlocal
cd /d "%~dp0" || (
    echo ERROR: Could not change to the application directory.
    exit /b 1
)

echo ========================================================
echo Starting Product Intelligence Assistant Services...
echo ========================================================

if exist "venv\Scripts\python.exe" (
    set "PYTHON=%CD%\venv\Scripts\python.exe"
) else if exist ".venv\Scripts\python.exe" (
    set "PYTHON=%CD%\.venv\Scripts\python.exe"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo ERROR: Python was not found. Install Python or create a project venv.
        exit /b 1
    )
    set "PYTHON=python"
)

echo Using Python:
"%PYTHON%" --version
if errorlevel 1 exit /b 1

echo Checking application imports before starting services...
"%PYTHON%" -c "import streamlit, fastapi, mcp; import api.app; import mcp_service.tools"
if errorlevel 1 (
    echo.
    echo ERROR: Startup checks failed; no services were started.
    echo If the error says Windows Application Control blocked a DLL or module,
    echo ask your IT administrator to review/authorize the trusted Python dependency.
    echo This launcher cannot override Windows security policy.
    exit /b 1
)

echo [1/3] Launching FastAPI Backend on port 8000...
start "FastAPI Backend (Port 8000)" cmd.exe /k ""%PYTHON%" -m uvicorn api.app:app --host 127.0.0.1 --port 8000 --reload"
timeout /t 2 /nobreak >nul

echo [2/3] Launching MCP Tool Server on port 8001...
start "MCP Server (Port 8001)" cmd.exe /k ""%PYTHON%" -m mcp_service.tools"
timeout /t 2 /nobreak >nul

echo [3/3] Launching Streamlit UI on port 8501...
start "Streamlit UI (Port 8501)" cmd.exe /k ""%PYTHON%" -m streamlit run main.py --server.address=127.0.0.1"

echo ========================================================
echo Startup commands sent. Check each service terminal for errors.
echo   - Streamlit UI:  http://localhost:8501
echo   - FastAPI API:   http://localhost:8000
echo   - MCP Server:    http://localhost:8001
echo ========================================================
echo Note: Keep the 3 terminal windows open while using the app.
