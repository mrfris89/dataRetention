#!/bin/bash
# ══════════════════════════════════════════════════════════════
# 20_OPERATIONS.sh
# Cheatsheet — jalankan dengan argument.
#
# Usage:
#   bash 20_OPERATIONS.sh status      → cek semua container
#   bash 20_OPERATIONS.sh logs        → view logs
#   bash 20_OPERATIONS.sh start       → start services
#   bash 20_OPERATIONS.sh stop        → stop services
#   bash 20_OPERATIONS.sh restart     → restart services
#   bash 20_OPERATIONS.sh shell       → bash ke webserver
#   bash 20_OPERATIONS.sh dags        → list DAGs
#   bash 20_OPERATIONS.sh errors      → cek DAG import errors
#   bash 20_OPERATIONS.sh backup      → backup metadata DB
#   bash 20_OPERATIONS.sh help        → tampilkan semua command
# ══════════════════════════════════════════════════════════════

PROJECT_DIR="${HOME}/airflow-archpurge"
cd "${PROJECT_DIR}" 2>/dev/null || { echo "❌ ${PROJECT_DIR} not found"; exit 1; }

case "${1}" in
    status)
        docker compose ps
        ;;
    logs)
        SERVICE="${2:-webserver}"
        LINES="${3:-50}"
        docker compose logs --tail="${LINES}" -f "${SERVICE}"
        ;;
    start)
        docker compose up -d
        docker compose ps
        ;;
    stop)
        docker compose down
        ;;
    restart)
        SERVICE="${2}"
        if [ -n "$SERVICE" ]; then
            docker compose restart "$SERVICE"
        else
            docker compose restart
        fi
        docker compose ps
        ;;
    shell)
        docker compose exec webserver bash
        ;;
    dags)
        docker compose exec webserver airflow dags list
        ;;
    errors)
        docker compose exec webserver airflow dags list-import-errors
        ;;
    conns)
        docker compose exec webserver airflow connections list
        ;;
    backup)
        BACKUP_FILE="backup_$(date +%Y%m%d_%H%M%S).sql"
        docker compose exec -T postgres pg_dump -U airflow airflow > "${BACKUP_FILE}"
        echo "✅ Backup saved: ${BACKUP_FILE}"
        ;;
    help|*)
        echo ""
        echo "  Usage: bash 20_OPERATIONS.sh <command>"
        echo ""
        echo "  Commands:"
        echo "    status    — Container status"
        echo "    logs      — View logs (default: webserver)"
        echo "              — bash 20_OPERATIONS.sh logs scheduler 100"
        echo "    start     — Start all containers"
        echo "    stop      — Stop all containers"
        echo "    restart   — Restart (all or specific)"
        echo "              — bash 20_OPERATIONS.sh restart scheduler"
        echo "    shell     — Bash shell ke webserver container"
        echo "    dags      — List DAGs"
        echo "    errors    — Cek DAG import errors"
        echo "    conns     — List connections"
        echo "    backup    — Backup Airflow metadata DB"
        echo "    help      — Tampilkan help ini"
        echo ""
        ;;
esac
