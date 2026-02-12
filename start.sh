#!/bin/bash
# ============================================================
#  GeneradorContenido — Script de arranque
#  Ejecutar: ./start.sh
# ============================================================

set -e

# Colores para mensajes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # Sin color

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

PYTHON="$DIR/.venv/bin/python3.9"

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  GeneradorContenido — Arranque${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# ── 1. Verificar Python y venv ──
echo -e "${YELLOW}[1/5]${NC} Verificando entorno..."

if [ ! -f "$PYTHON" ]; then
    echo -e "${RED}ERROR:${NC} No se encontro Python en .venv/bin/python3.9"
    echo "       Crea el entorno virtual primero:"
    echo "       python3.9 -m venv .venv"
    exit 1
fi

echo -e "  ✓ Python: $($PYTHON --version 2>&1)"

# ── 2. Instalar/actualizar dependencias ──
echo -e "${YELLOW}[2/5]${NC} Actualizando dependencias..."

if [ -f requirements.txt ]; then
    $PYTHON -m pip install -q --upgrade pip 2>/dev/null
    $PYTHON -m pip install -q -r requirements.txt 2>/dev/null
    echo -e "  ✓ Dependencias actualizadas"
else
    echo -e "  ${YELLOW}⚠ No hay requirements.txt, saltando...${NC}"
fi

# ── 3. Verificar .env ──
echo -e "${YELLOW}[3/5]${NC} Verificando configuracion..."

if [ ! -f .env ]; then
    echo -e "${RED}ERROR:${NC} No se encontro archivo .env"
    echo "       Copia .env.example a .env y rellena tus claves API"
    exit 1
fi

# Verificar clave minima (Gemini)
if grep -q "PEGA-AQUI" .env 2>/dev/null; then
    echo -e "  ${YELLOW}⚠ Hay claves sin configurar en .env (busca 'PEGA-AQUI')${NC}"
    echo -e "  ${YELLOW}  La app arrancara pero algunas funciones no estaran disponibles${NC}"
else
    echo -e "  ✓ Archivo .env configurado"
fi

# ── 4. Crear/migrar base de datos ──
echo -e "${YELLOW}[4/5]${NC} Preparando base de datos..."

$PYTHON -c "
from app.models import Base
from app.database import sync_engine
Base.metadata.create_all(sync_engine)
print('  ✓ Tablas de base de datos verificadas')
"

# Crear directorio de videos si no existe
mkdir -p storage/videos storage/thumbnails
echo -e "  ✓ Directorios de almacenamiento listos"

# ── 5. Arrancar servidor ──
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Todo listo. Arrancando servidor...${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "  URL:  ${BLUE}http://127.0.0.1:8000${NC}"
echo -e "  API:  ${BLUE}http://127.0.0.1:8000/api/health${NC}"
echo ""
echo -e "  Presiona ${YELLOW}Ctrl+C${NC} para detener"
echo ""

$PYTHON -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
