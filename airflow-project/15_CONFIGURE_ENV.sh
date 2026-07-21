#!/bin/bash
# ══════════════════════════════════════════════════════════════
# 15_CONFIGURE_ENV.sh
# Buat file .env — edit password sesuai environment kamu.
# Usage: bash 15_CONFIGURE_ENV.sh
# ══════════════════════════════════════════════════════════════

set -e

PROJECT_DIR="${HOME}/airflow-archpurge"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Step 2: Configure Environment"
echo "═══════════════════════════════════════════════════"
echo ""

ENV_FILE="${PROJECT_DIR}/.env"

if [ -f "${ENV_FILE}" ]; then
    echo "  ⚠️  .env sudah ada. Overwrite? (yes/no)"
    read -r ans
    if [ "$ans" != "yes" ]; then
        echo "  → Skip. Edit manual: nano ${ENV_FILE}"
        exit 0
    fi
fi

cat > "${ENV_FILE}" << 'EOF'
# ══════════════════════════════════════════
# Archpurge Airflow — Environment Config
# EDIT PASSWORD DI BAWAH INI!
# ══════════════════════════════════════════

# Airflow metadata DB (internal, bukan source/target kamu)
POSTGRES_PASSWORD=airflow_secure_2026

# SMTP untuk email alert (isi sesuai mail server kantor)
SMTP_HOST=smtp.company.com
SMTP_PORT=587
SMTP_USER=airflow@company.com
SMTP_PASSWORD=changeme
SMTP_MAIL_FROM=airflow@company.com
EOF

chmod 600 "${ENV_FILE}"

echo "  ✅ .env created: ${ENV_FILE}"
echo "  ⚠️  EDIT password sekarang:"
echo ""
echo "     nano ${ENV_FILE}"
echo ""
echo "  Setelah edit, lanjut: bash 16_BUILD_AND_START.sh"
echo ""
