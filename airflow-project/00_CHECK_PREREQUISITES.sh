#!/bin/bash
# ══════════════════════════════════════════════════════════════
# 00_CHECK_PREREQUISITES.sh
# Cek semua syarat sebelum deploy. Jalankan PERTAMA.
# Usage: bash 00_CHECK_PREREQUISITES.sh
# ══════════════════════════════════════════════════════════════

echo "═══════════════════════════════════════════════════"
echo "  Archpurge Airflow — Prerequisites Check (OEL 9)"
echo "═══════════════════════════════════════════════════"
echo ""

PASS=0
FAIL=0

check() {
    if eval "$2" > /dev/null 2>&1; then
        echo "  ✅  $1"
        ((PASS++))
    else
        echo "  ❌  $1 — $3"
        ((FAIL++))
    fi
}

# OS
check "OS: Oracle Linux / RHEL" \
    "grep -qiE 'oracle|rhel|red hat' /etc/os-release" \
    "Script ini untuk OEL/RHEL 9"

# Docker
check "Docker Engine installed" \
    "docker --version" \
    "Install: dnf install -y docker-ce docker-ce-cli containerd.io"

check "Docker daemon running" \
    "docker info" \
    "Start: systemctl start docker && systemctl enable docker"

check "Docker Compose plugin" \
    "docker compose version" \
    "Install: dnf install -y docker-compose-plugin"

# User
check "Current user in docker group" \
    "groups | grep -q docker" \
    "Fix: usermod -aG docker \$USER && newgrp docker"

# Port
check "Port 5300 available" \
    "! ss -tlnp | grep -q ':5300 '" \
    "Port 5300 sudah dipakai. Cek: ss -tlnp | grep 5300"

# Firewall
if systemctl is-active firewalld > /dev/null 2>&1; then
    check "Firewall: port 5300 open" \
        "firewall-cmd --list-ports | grep -q 5300" \
        "Fix: firewall-cmd --add-port=5300/tcp --permanent && firewall-cmd --reload"
else
    echo "  ℹ️  Firewall: firewalld not active (skip)"
fi

# Disk
AVAIL=$(df -BG /var/lib/docker 2>/dev/null | tail -1 | awk '{print $4}' | tr -d 'G')
if [ "${AVAIL:-0}" -ge 10 ]; then
    echo "  ✅  Disk space: ${AVAIL}G available (min 10G)"
    ((PASS++))
else
    echo "  ❌  Disk space: ${AVAIL:-?}G — minimum 10G di /var/lib/docker"
    ((FAIL++))
fi

# Memory
MEM=$(free -g | awk '/Mem:/{print $2}')
if [ "${MEM:-0}" -ge 4 ]; then
    echo "  ✅  Memory: ${MEM}G available (min 4G)"
    ((PASS++))
else
    echo "  ❌  Memory: ${MEM:-?}G — minimum 4G RAM"
    ((FAIL++))
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Result: ${PASS} passed, ${FAIL} failed"
echo "═══════════════════════════════════════════════════"

if [ $FAIL -gt 0 ]; then
    echo ""
    echo "  ⚠️  Fix semua ❌ di atas sebelum lanjut ke step berikutnya."
    echo ""
    exit 1
else
    echo ""
    echo "  🎉 Semua OK! Lanjut: bash 01_SETUP_DIRS.sh"
    echo ""
    exit 0
fi
