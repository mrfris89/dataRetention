#!/bin/bash
# ══════════════════════════════════════════════════════════════
# 19_VERIFY.sh
# Final verification — cek semua sudah running & DAGs detected.
# Usage: bash 19_VERIFY.sh
# ══════════════════════════════════════════════════════════════

PROJECT_DIR="${HOME}/airflow-archpurge"
cd "${PROJECT_DIR}"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Step 6: Final Verification"
echo "═══════════════════════════════════════════════════"
echo ""

PASS=0
FAIL=0

check() {
    if eval "$2" > /dev/null 2>&1; then
        echo "  ✅  $1"
        ((PASS++))
    else
        echo "  ❌  $1"
        ((FAIL++))
    fi
}

# Container checks
echo "  ── Containers ──"
check "postgres running"  "docker compose ps postgres | grep -q 'Up'"
check "redis running"     "docker compose ps redis | grep -q 'Up'"
check "webserver running" "docker compose ps webserver | grep -q 'Up'"
check "scheduler running" "docker compose ps scheduler | grep -q 'Up'"
check "worker running"    "docker compose ps worker | grep -q 'Up'"

echo ""
echo "  ── Webserver ──"
check "UI accessible (port 5300)" "curl -sf http://localhost:5300/health"

echo ""
echo "  ── DAGs ──"
DAG_LIST=$(docker compose exec -T webserver airflow dags list 2>/dev/null)
check "DAGs loadable (no import errors)" \
    "docker compose exec -T webserver airflow dags list-import-errors 2>&1 | grep -q 'No data found'"

DAG_COUNT=$(echo "$DAG_LIST" | grep -c 'archcopy\|archdelete' || true)
if [ "$DAG_COUNT" -gt 0 ]; then
    echo "  ✅  DAGs detected: ${DAG_COUNT} archpurge DAGs"
    ((PASS++))
else
    echo "  ❌  No archpurge DAGs detected"
    ((FAIL++))
fi

echo ""
echo "  ── Connections ──"
CONN_LIST=$(docker compose exec -T webserver airflow connections list 2>/dev/null || true)
CONN_COUNT=$(echo "$CONN_LIST" | grep -cE 'postgres|mysql|oracle' || true)
echo "  ℹ️  ${CONN_COUNT} database connections found"
if [ "$CONN_COUNT" -lt 2 ]; then
    echo "  ⚠️  Minimal 2 connections diperlukan (source + target)"
    echo "     Setup via: bash 18_SETUP_CONNECTIONS.sh"
fi

echo ""
echo "  ── Python Libraries ──"
check "psycopg2 (PostgreSQL)"  "docker compose exec -T webserver python3 -c 'import psycopg2'"
check "mysql.connector (MySQL)" "docker compose exec -T webserver python3 -c 'import mysql.connector'"
check "oracledb (Oracle)"      "docker compose exec -T webserver python3 -c 'import oracledb'"
check "yaml parser"            "docker compose exec -T webserver python3 -c 'import yaml'"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Result: ${PASS} passed, ${FAIL} failed"
echo "═══════════════════════════════════════════════════"

if [ $FAIL -gt 0 ]; then
    echo ""
    echo "  ⚠️  Ada yang gagal. Cek log:"
    echo "     docker compose logs webserver | tail -30"
    echo "     docker compose logs scheduler | tail -30"
    echo ""
else
    echo ""
    echo "  🎉 SEMUA OK!"
    echo ""
    echo "  ╔═══════════════════════════════════════════════╗"
    echo "  ║                                               ║"
    echo "  ║   Airflow UI : http://localhost:5300           ║"
    echo "  ║   Status     : READY                          ║"
    echo "  ║                                               ║"
    echo "  ║   SOP:                                        ║"
    echo "  ║   1. Buka UI → DAGs                           ║"
    echo "  ║   2. Unpause archcopy_<table>                 ║"
    echo "  ║   3. Trigger manual                           ║"
    echo "  ║   4. Cek log → SUCCESS?                       ║"
    echo "  ║   5. Trigger archdelete_<table>               ║"
    echo "  ║                                               ║"
    echo "  ╚═══════════════════════════════════════════════╝"
    echo ""
    echo "  Tambah tabel baru:"
    echo "    cd ${PROJECT_DIR}/dags/configs/"
    echo "    cp _template_copy.yaml <table>_copy.yaml"
    echo "    cp _template_delete.yaml <table>_delete.yaml"
    echo "    # edit → tunggu 30 detik → DAG muncul di UI"
    echo ""
fi
