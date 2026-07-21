#!/bin/bash
# ══════════════════════════════════════════════════════════════
# 18_SETUP_CONNECTIONS.sh
# Buat Airflow Connections ke source & target DB.
# Bisa juga dibuat manual via UI (Admin > Connections).
# Usage: bash 18_SETUP_CONNECTIONS.sh
# ══════════════════════════════════════════════════════════════

set -e

PROJECT_DIR="${HOME}/airflow-archpurge"
cd "${PROJECT_DIR}"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Step 5: Setup Database Connections"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Pilih cara setup:"
echo "  [1] Interactive CLI (guided)"
echo "  [2] Skip — setup manual via Airflow UI nanti"
echo ""
read -p "  Pilihan (1/2): " CHOICE

if [ "$CHOICE" != "1" ]; then
    echo ""
    echo "  → Skip. Setup manual di:"
    echo "    http://localhost:5300 → Admin → Connections → Add"
    echo ""
    exit 0
fi

# ── Source DB ──
echo ""
echo "  ─── SOURCE DATABASE ───"
echo "  DB Type:"
echo "    [1] PostgreSQL"
echo "    [2] MySQL"
echo "    [3] Oracle"
read -p "  Pilih (1/2/3): " SRC_TYPE

case $SRC_TYPE in
    1) SRC_CONN_TYPE="postgres"; SRC_DEFAULT_PORT=5432 ;;
    2) SRC_CONN_TYPE="mysql";    SRC_DEFAULT_PORT=3306 ;;
    3) SRC_CONN_TYPE="oracle";   SRC_DEFAULT_PORT=1521 ;;
    *) echo "  ❌ Invalid"; exit 1 ;;
esac

read -p "  Connection ID (default: ${SRC_CONN_TYPE}_source): " SRC_CONN_ID
SRC_CONN_ID=${SRC_CONN_ID:-${SRC_CONN_TYPE}_source}

read -p "  Host         : " SRC_HOST
read -p "  Port (default: ${SRC_DEFAULT_PORT}): " SRC_PORT
SRC_PORT=${SRC_PORT:-$SRC_DEFAULT_PORT}
read -p "  Database/SID : " SRC_DB
read -p "  Username     : " SRC_USER
read -sp "  Password     : " SRC_PASS
echo ""

docker compose exec webserver airflow connections add "${SRC_CONN_ID}" \
    --conn-type "${SRC_CONN_TYPE}" \
    --conn-host "${SRC_HOST}" \
    --conn-port "${SRC_PORT}" \
    --conn-schema "${SRC_DB}" \
    --conn-login "${SRC_USER}" \
    --conn-password "${SRC_PASS}" 2>/dev/null || \
docker compose exec webserver airflow connections delete "${SRC_CONN_ID}" && \
docker compose exec webserver airflow connections add "${SRC_CONN_ID}" \
    --conn-type "${SRC_CONN_TYPE}" \
    --conn-host "${SRC_HOST}" \
    --conn-port "${SRC_PORT}" \
    --conn-schema "${SRC_DB}" \
    --conn-login "${SRC_USER}" \
    --conn-password "${SRC_PASS}"

echo "  ✅ Source connection '${SRC_CONN_ID}' created"

# ── Target DB ──
echo ""
echo "  ─── TARGET DATABASE ───"
echo "  DB Type:"
echo "    [1] PostgreSQL"
echo "    [2] MySQL"
echo "    [3] Oracle"
read -p "  Pilih (1/2/3): " TGT_TYPE

case $TGT_TYPE in
    1) TGT_CONN_TYPE="postgres"; TGT_DEFAULT_PORT=5432 ;;
    2) TGT_CONN_TYPE="mysql";    TGT_DEFAULT_PORT=3306 ;;
    3) TGT_CONN_TYPE="oracle";   TGT_DEFAULT_PORT=1521 ;;
    *) echo "  ❌ Invalid"; exit 1 ;;
esac

read -p "  Connection ID (default: ${TGT_CONN_TYPE}_target): " TGT_CONN_ID
TGT_CONN_ID=${TGT_CONN_ID:-${TGT_CONN_TYPE}_target}

read -p "  Host         : " TGT_HOST
read -p "  Port (default: ${TGT_DEFAULT_PORT}): " TGT_PORT
TGT_PORT=${TGT_PORT:-$TGT_DEFAULT_PORT}
read -p "  Database/SID : " TGT_DB
read -p "  Username     : " TGT_USER
read -sp "  Password     : " TGT_PASS
echo ""

docker compose exec webserver airflow connections add "${TGT_CONN_ID}" \
    --conn-type "${TGT_CONN_TYPE}" \
    --conn-host "${TGT_HOST}" \
    --conn-port "${TGT_PORT}" \
    --conn-schema "${TGT_DB}" \
    --conn-login "${TGT_USER}" \
    --conn-password "${TGT_PASS}" 2>/dev/null || \
docker compose exec webserver airflow connections delete "${TGT_CONN_ID}" && \
docker compose exec webserver airflow connections add "${TGT_CONN_ID}" \
    --conn-type "${TGT_CONN_TYPE}" \
    --conn-host "${TGT_HOST}" \
    --conn-port "${TGT_PORT}" \
    --conn-schema "${TGT_DB}" \
    --conn-login "${TGT_USER}" \
    --conn-password "${TGT_PASS}"

echo "  ✅ Target connection '${TGT_CONN_ID}' created"

echo ""
echo "  ╔═══════════════════════════════════════════╗"
echo "  ║  Source : ${SRC_CONN_ID}"
echo "  ║  Target : ${TGT_CONN_ID}"
echo "  ╚═══════════════════════════════════════════╝"
echo ""
echo "  ⚠️  Update YAML configs di dags/configs/ "
echo "     dengan conn_id yang sama!"
echo ""
echo "  Lanjut: bash 19_VERIFY.sh"
echo ""
