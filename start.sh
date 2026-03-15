#!/bin/bash
# PP1 — ProdPlan ONE — Launch Script
# Incompol Demo — Março 2026

set -e

echo "╔══════════════════════════════════════╗"
echo "║  PP1 — ProdPlan ONE                  ║"
echo "║  NIKUFRA.AI · Demo Incompol          ║"
echo "╚══════════════════════════════════════╝"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 não encontrado. Instale Python 3.10+"
    exit 1
fi

# Check API key
if [ -z "$OPENAI_API_KEY" ]; then
    echo "⚠️  OPENAI_API_KEY não definida."
    echo "   O planeamento funciona, mas o chat AI fica desactivado."
    echo ""
    echo "   Para activar: export OPENAI_API_KEY=\"sk-...\""
    echo ""
fi

# Install dependencies
echo "📦 A instalar dependências..."
pip install -r requirements.txt -q

# Copy ISOP if provided
if [ -n "$1" ]; then
    echo "📄 A copiar ISOP: $1"
    cp "$1" backend/isop_default.xlsx
fi

# Launch
echo ""
echo "🚀 A iniciar PP1..."
echo "   Abrir: http://localhost:8000"
echo ""
cd backend
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
