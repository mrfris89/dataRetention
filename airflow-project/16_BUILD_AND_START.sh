#!/bin/bash
# ══════════════════════════════════════════════════════════════
# 16_BUILD_AND_START.sh
# Build image & start semua container.
# Usage: bash 16_BUILD_AND_START.sh
# ══════════════════════════════════════════════════════════════

set -e

PROJECT_DIR="${HOME}/airflow-archpurge"
cd "${PROJECT_DIR}"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Step 3: Build & Start Containers"
echo "═══════════════════════════════════════════════════"
echo ""

# Check .env exists
if [ ! -f .env ]; then
    echo "  ❌ .env belum ada. Jalankan: bash 15_CONFIGURE_ENV.sh"
    exit 1
fi

echo "  [1/3] Building image (5-10 menit pertama kali)..."
docker compose build

echo ""
echo "  [2/3] Starting containers..."
docker compose up -d

echo ""
echo "  [3/3] Waiting for services to be healthy..."
sleep 10

# Check status
echo ""
echo "  Container status:"
echo "  ─────────────────────────────────────────────"
docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
echo ""

# Wait for webserver
echo "  Waiting for webserver (max 60s)..."
for i in $(seq 1 12); do
    if curl -sf http://localhost:5300/health > /dev/null 2>&1; then
        echo "  ✅ Webserver ready!"
        break
    fi
    sleep 5
    echo "  ... waiting (${i}/12)"
done

echo ""
echo "  🎉 Containers running!"
echo ""
echo "  Lanjut: bash 17_CREATE_ADMIN.sh"
echo ""
