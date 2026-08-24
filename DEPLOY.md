# Deployment Guide — Data Retention Tools

## Prerequisites

- Ubuntu 20.04+ / Debian 11+
- Python 3.8+
- MySQL/MariaDB client connectivity
- (Optional) GCS service account JSON for backup upload

## 1. Install System Packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

## 2. Create Directory Structure

```bash
sudo mkdir -p /opt/retention
sudo chown $(whoami):$(whoami) /opt/retention
```

## 3. Deploy Files

```bash
cd /opt/retention

# Copy scripts
cp batch_delete.py /opt/retention/
cp setup_wizard.py /opt/retention/
cp requirements.txt /opt/retention/

# Create subdirectories
mkdir -p jobs logs
```

### File Layout

```
/opt/retention/
├── batch_delete.py          # Main script (interactive + config + dry-run)
├── setup_wizard.py          # Wizard to generate YAML configs
├── requirements.txt         # Python dependencies
├── .env                     # Passwords (auto-generated, chmod 600)
├── jobs/
│   ├── *.yaml               # Job configs (1 file per table)
│   └── logs/                # Execution logs
└── venv/                    # Python virtual environment
```

## 4. Setup Virtual Environment

```bash
cd /opt/retention
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Python Modules

| Module                 | Purpose                              | Required |
|------------------------|--------------------------------------|----------|
| `PyMySQL`              | MySQL/MariaDB connection             | Yes      |
| `PyYAML`               | Read YAML config files               | Yes      |
| `google-cloud-storage` | Upload CSV backup to GCS             | Only if using GCS backup |

> `csv`, `gzip`, `argparse`, `logging`, `getpass`, `time`, `os`, `sys` are Python built-ins.

## 5. Setup Jobs via Wizard

```bash
cd /opt/retention
source venv/bin/activate
python3 setup_wizard.py
```

The wizard will:
1. Ask connection, table, retention, batch, backup, and schedule info
2. Generate YAML in `jobs/`
3. Save password to `.env` (chmod 600)
4. Run dry-run validation
5. Output crontab entries to copy-paste

## 6. Verify with Dry Run

```bash
source venv/bin/activate
source .env
python3 batch_delete.py --config jobs/YOUR_JOB.yaml --dry-run
```

## 7. Install Crontab

```bash
crontab -e
```

Paste the entries from wizard output. Use the venv python path:

```cron
# finpay.qris_reserve — Every day at 02:00
0 2 * * * /bin/bash -c 'source /opt/retention/.env && /opt/retention/venv/bin/python3 /opt/retention/batch_delete.py --config /opt/retention/jobs/YOUR_JOB.yaml'
```

> **Important:** Use `/opt/retention/venv/bin/python3` (not `/usr/bin/python3`) so cron uses the venv with all dependencies installed.

## 8. (Optional) GCS Backup Setup

1. Create a GCS bucket
2. Create a service account with `Storage Object Creator` role
3. Download the JSON key file
4. Place it on the server:

```bash
cp finnet-data-platform.json /opt/retention/
chmod 600 /opt/retention/finnet-data-platform.json
```

5. Reference the path in your YAML:

```yaml
backup:
  enabled: true
  local_dir: /opt/retention/backups
  delete_local_after_upload: true
  gcs:
    bucket: retention-mysql-bucket
    prefix: retention-backups/
    credentials_file: /opt/retention/finnet-data-platform.json
```

## 9. Monitor

```bash
# Watch live log
tail -f /opt/retention/jobs/logs/batch_delete_*.log

# Check latest log
ls -ltrh /opt/retention/jobs/logs/

# Check if cron is running
grep batch_delete /var/log/syslog
```

## 10. Quick Reference

```bash
# Activate venv
source /opt/retention/venv/bin/activate

# Run wizard
python3 /opt/retention/setup_wizard.py

# Dry run
source /opt/retention/.env && python3 /opt/retention/batch_delete.py --config /opt/retention/jobs/JOB.yaml --dry-run

# Manual run
source /opt/retention/.env && python3 /opt/retention/batch_delete.py --config /opt/retention/jobs/JOB.yaml

# Interactive mode
python3 /opt/retention/batch_delete.py
```
