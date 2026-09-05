# DigiGarment Local Development Server Launcher
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "   Starting DigiGarment Local Development Server        " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

$VenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "[INFO] Creating virtual environment .venv..." -ForegroundColor Yellow
    python -m venv .venv
    & ".venv\Scripts\pip.exe" install -r requirements.txt
}

Write-Host ""
Write-Host "Local server running at: http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "Jobs Portal:            http://127.0.0.1:8000/jobs" -ForegroundColor Green
Write-Host "Admin Dashboard:        http://127.0.0.1:8000/admin" -ForegroundColor Green
Write-Host "API Health Check:       http://127.0.0.1:8000/health" -ForegroundColor Green
Write-Host ""
Write-Host "Press Ctrl+C to stop the server." -ForegroundColor Gray
Write-Host ""

& $VenvPython -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload
