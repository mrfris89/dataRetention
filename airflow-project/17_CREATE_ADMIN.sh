#!/bin/bash
# ══════════════════════════════════════════════════════════════
# 17_CREATE_ADMIN.sh
# Buat admin user untuk Airflow UI.
# Usage: bash 17_CREATE_ADMIN.sh
# ══════════════════════════════════════════════════════════════

set -e

PROJECT_DIR="${HOME}/airflow-archpurge"
cd "${PROJECT_DIR}"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Step 4: Create Admin User"
echo "═══════════════════════════════════════════════════"
echo ""

read -p "  Username  (default: admin): " USERNAME
USERNAME=${USERNAME:-admin}

read -p "  Email     (default: admin@company.com): " EMAIL
EMAIL=${EMAIL:-admin@company.com}

read -sp "  Password  : " PASSWORD
echo ""

if [ -z "$PASSWORD" ]; then
    echo "  ❌ Password tidak boleh kosong."
    exit 1
fi

docker compose run --rm webserver airflow users create \
    --username "${USERNAME}" \
    --firstname Admin \
    --lastname User \
    --role Admin \
    --email "${EMAIL}" \
    --password "${PASSWORD}"

echo ""
echo "  ✅ Admin user created!"
echo ""
echo "  ╔═══════════════════════════════════════════╗"
echo "  ║  URL      : http://localhost:5300         ║"
echo "  ║  Username : ${USERNAME}"
echo "  ║  Password : (yang kamu masukkan tadi)     ║"
echo "  ╚═══════════════════════════════════════════╝"
echo ""
echo "  Lanjut: bash 18_SETUP_CONNECTIONS.sh"
echo ""
