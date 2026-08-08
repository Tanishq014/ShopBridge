@echo off
echo Starting ShopBridge Server...
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
pause
