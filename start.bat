@echo off
cd /d "%~dp0"

echo ============================================
echo   TelBot v2 — Arrancando Backend + Frontend
echo ============================================
echo.

REM ── .env ──────────────────────────────────
if not exist ".env" (
    echo [!] No se encontro .env
    if exist ".env.example" (
        echo     Copiando .env.example -^> .env
        echo     EDITALO con tus credenciales antes de continuar.
        copy ".env.example" ".env" >nul
    ) else (
        echo     ERROR: .env.example tampoco existe.
    )
    echo.
    pause
    exit /b 1
)

REM ── node_modules ──────────────────────────
if not exist "frontend\node_modules" (
    echo [!] Dependencias frontend no instaladas. Ejecutando npm install...
    echo.
    cd frontend
    call npm install
    cd ..
    if %ERRORLEVEL% neq 0 (
        echo.
        echo ERROR: npm install fallo.
        pause
        exit /b 1
    )
    echo.
)

echo Backend API: http://localhost:8766
echo Frontend GUI: http://localhost:5175
echo.

start "TelBot v2 - Bot" cmd /k "python backend\telegram_listener.py"
start "TelBot v2 - GUI" cmd /k "cd frontend && npm run dev"

REM ── Abrir navegador ──────────────────────
echo Esperando a que el frontend este listo...
timeout /t 3 /nobreak >nul
start http://localhost:5175

echo.
echo Servidores iniciados:
echo   API  - http://localhost:8766
echo   GUI  - http://localhost:5175
echo.
pause
