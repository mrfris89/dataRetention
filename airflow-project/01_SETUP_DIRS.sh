#!/bin/bash
# ══════════════════════════════════════════════════════════════
# 01_SETUP_DIRS.sh
# Buat folder structure & extract packages.
# Usage: bash 01_SETUP_DIRS.sh
# ══════════════════════════════════════════════════════════════

set -e

PROJECT_DIR="${HOME}/airflow-archpurge"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Step 1: Setup Directory Structure"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Project dir: ${PROJECT_DIR}"
echo ""

# Create dirs
mkdir -p "${PROJECT_DIR}"/{dags/helpers,dags/tasks,dags/configs,logs,plugins}

# Copy deploy files ke project dir
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cp "${SCRIPT_DIR}/02_Dockerfile"          "${PROJECT_DIR}/Dockerfile"
cp "${SCRIPT_DIR}/03_requirements.txt"    "${PROJECT_DIR}/requirements.txt"
cp "${SCRIPT_DIR}/04_docker-compose.yml"  "${PROJECT_DIR}/docker-compose.yml"

# Copy archpurge code
cp "${SCRIPT_DIR}"/05_dag_factory.py         "${PROJECT_DIR}/dags/dag_factory.py"
cp "${SCRIPT_DIR}"/06_db_connector.py        "${PROJECT_DIR}/dags/helpers/db_connector.py"
cp "${SCRIPT_DIR}"/07_db_operations.py       "${PROJECT_DIR}/dags/helpers/db_operations.py"
cp "${SCRIPT_DIR}"/08_email_alert.py         "${PROJECT_DIR}/dags/helpers/email_alert.py"
cp "${SCRIPT_DIR}"/09_copy_tasks.py          "${PROJECT_DIR}/dags/tasks/copy_tasks.py"
cp "${SCRIPT_DIR}"/10_delete_tasks.py        "${PROJECT_DIR}/dags/tasks/delete_tasks.py"
touch "${PROJECT_DIR}/dags/helpers/__init__.py"
touch "${PROJECT_DIR}/dags/tasks/__init__.py"

# Copy YAML configs
cp "${SCRIPT_DIR}"/11_template_copy.yaml     "${PROJECT_DIR}/dags/configs/_template_copy.yaml"
cp "${SCRIPT_DIR}"/12_template_delete.yaml   "${PROJECT_DIR}/dags/configs/_template_delete.yaml"
cp "${SCRIPT_DIR}"/13_sales_copy.yaml        "${PROJECT_DIR}/dags/configs/sales_copy.yaml"
cp "${SCRIPT_DIR}"/14_sales_delete.yaml      "${PROJECT_DIR}/dags/configs/sales_delete.yaml"

echo "  ✅ Directory structure:"
echo ""
find "${PROJECT_DIR}" -maxdepth 4 -not -path '*/\.*' | sed "s|${PROJECT_DIR}|  .|" | head -30
echo ""
echo "  🎉 Done! Lanjut: bash 15_CONFIGURE_ENV.sh"
echo ""
