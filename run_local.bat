@echo off
title DigiGarment Local Server
echo ========================================================
echo   Starting DigiGarment Local Development Server
echo ========================================================
echo.

IF NOT EXIST ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment .venv not found.
    echo Creating .venv and installing requirements...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
) ELSE (
    call .venv\Scripts\activate.bat
)

echo.
echo Local server running at: http://127.0.0.1:8000
echo Jobs Portal:            http://127.0.0.1:8000/jobs
echo Admin Dashboard:        http://127.0.0.1:8000/admin
echo API Health Check:       http://127.0.0.1:8000/health
echo.
echo Press Ctrl+C to stop the server.
echo.

uvicorn app:app --host 127.0.0.1 --port 8000 --reload

pause
