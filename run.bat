@echo off
echo ============================================
echo  DeepFakeHybrid — Starting All Services
echo ============================================

echo [1/3] Activating virtual environment...
call venv\Scripts\activate

echo [2/3] Starting Flask Deepfake Analyzer (port 5000)...
start "DeepFake Analyzer" cmd /k "cd /d %~dp0server && python server.py"
timeout /t 3 >nul

echo [3/3] Starting Identity Manager (port 7000)...
start "Identity Manager" cmd /k "cd /d %~dp0server && python identity_manager.py"
timeout /t 3 >nul

echo [4/4] Starting Ingest Relay Server (port 8765)...
start "Ingest Server" cmd /k "cd /d %~dp0server && python ingest_server.py"
timeout /t 3 >nul

echo.
echo ============================================
echo  All 3 servers launched in separate windows.
echo  Now load the Chrome extension from: extension/
echo ============================================
echo.
echo Press any key to also run the desktop client (optional)...
pause >nul

cd /d %~dp0client
python client.py
pause
