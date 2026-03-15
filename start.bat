@echo off
REM PP1 — ProdPlan ONE — Launch Script (Windows)
REM Incompol Demo — Março 2026

echo ========================================
echo   PP1 — ProdPlan ONE
echo   NIKUFRA.AI . Demo Incompol
echo ========================================
echo.

REM Check API key
if "%OPENAI_API_KEY%"=="" (
    echo [AVISO] OPENAI_API_KEY nao definida.
    echo    O planeamento funciona, mas o chat AI fica desactivado.
    echo.
    echo    Para activar: set OPENAI_API_KEY=sk-...
    echo.
)

REM Install dependencies
echo A instalar dependencias...
pip install -r requirements.txt -q

REM Launch
echo.
echo A iniciar PP1...
echo    Abrir: http://localhost:8000
echo.
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
