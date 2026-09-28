@echo off
rem VMU site viewer (future completed state): starts the local server (python on PATH) and opens the viewer.
cd /d "%~dp0"
powershell -NoProfile -Command "if (-not (Get-NetTCPConnection -LocalPort 18090 -State Listen -ErrorAction SilentlyContinue)) { Start-Process -FilePath 'python' -ArgumentList @('serve.py','18090') -WorkingDirectory '%~dp0' -WindowStyle Hidden; Start-Sleep -Seconds 2 }"
start "" "http://127.0.0.1:18090/index.html"
