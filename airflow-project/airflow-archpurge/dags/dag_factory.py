"""
dag_factory.py — Mesin utama.

Cara kerja:
  1. Scan semua file configs/*.yaml (kecuali yang berawalan '_')
  2. Baca isinya
  3. dag_type: "copy"   -> bikin DAG 4 task (count, check, transfer, verify)
     dag_type: "delete" -> bikin DAG 4 task (cutoff, verify_match, delete, verify_zero)
  4. Register ke Airflow

SAFETY DEFAULTS (hardcoded, tidak bisa dioverride via YAML):
  - schedule_interval = None        -> TIDAK PERNAH jalan otomatis
  - is_paused_upon_creation = True  -> DAG baru selalu PAUSED
  - max_active_runs = 1             -> tidak bisa double-run barengan
  - email_on_failure = True         -> alert tiap task gagal
"""

import os
import sys
import glob
import logging

import yaml
from datetime import timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator

# pastikan folder dags/ ada di path supaya helpers/ & tasks/ bisa diimport
DAGS_DIR = os.path.dirname(os.path.abspath(__file__))
if DAGS_DIR not in sys.path:
    sys.path.insert(0, DAGS_DIR)

from tasks import copy_tasks, delete_tasks          # noqa: E402
from helpers.email_alert import parse_emails        # noqa: E402

log = logging.getLogger(__name__)

CONFIG_DIR = os.path.join(DAGS_DIR, "configs")

REQUIRED_KEYS = [
    "dag_id", "dag_type", "source_conn", "target_conn",
    "source_table", "target_table", "date_column", "retention_days",
]


def _load_configs():
    configs = []
    for path in sorted(glob.glob(os.path.join(CONFIG_DIR, "*.yaml"))):
        if os.path.basename(path).startswith("_"):
            continue  # skip template
        try:
            with open(path) as f:
                cfg = yaml.safe_load(f)
            missing = [k for k in REQUIRED_KEYS if k not in cfg]
            if missing:
                log.error("Config %s SKIP — key kurang: %s", path, missing)
                continue
            if cfg["dag_type"] not in ("copy", "delete"):
                log.error("Config %s SKIP — dag_type harus copy/delete", path)
                continue
            configs.append(cfg)
        except Exception as e:  # noqa
            log.error("Config %s SKIP — gagal parse: %s", path, e)
    return configs


def _build_dag(cfg):
    default_args = {
        "owner": "dba",
        "email": parse_emails(cfg.get("alert_email")),
        "email_on_failure": True,
        "email_on_retry": False,
        "retries": 0,  # data ops: JANGAN auto-retry, biar manusia yang cek
        "execution_timeout": timedelta(
            hours=int(cfg.get("timeout_hours", 6))),
    }

    dag = DAG(
        dag_id=cfg["dag_id"],
        description=(
            f"[{cfg['dag_type'].upper()}] "
            f"{cfg['source_table']} -> {cfg['target_table']} "
            f"(retention {cfg['retention_days']}d)"
        ),
        # ── SAFETY: manual-only + selalu paused saat dibuat ──
        schedule_interval=None,
        is_paused_upon_creation=True,
        max_active_runs=1,
        catchup=False,
        default_args=default_args,
        tags=["archpurge", cfg["dag_type"]],
    )

    with dag:
        if cfg["dag_type"] == "copy":
            t1 = PythonOperator(
                task_id="1_count_source",
                python_callable=copy_tasks.t1_count_source,
                op_kwargs={"config": cfg})
            t2 = PythonOperator(
                task_id="2_check_target_window_empty",
                python_callable=copy_tasks.t2_check_target,
                op_kwargs={"config": cfg})
            t3 = PythonOperator(
                task_id="3_transfer_data",
                python_callable=copy_tasks.t3_transfer,
                op_kwargs={"config": cfg})
            t4 = PythonOperator(
                task_id="4_verify_copy_count",
                python_callable=copy_tasks.t4_verify,
                op_kwargs={"config": cfg})
            t1 >> t2 >> t3 >> t4

        else:  # delete
            t1 = PythonOperator(
                task_id="1_compute_cutoff",
                python_callable=delete_tasks.t1_compute_cutoff,
                op_kwargs={"config": cfg})
            t2 = PythonOperator(
                task_id="2_SAFETY_verify_source_equals_target",
                python_callable=delete_tasks.t2_verify_match,
                op_kwargs={"config": cfg})
            t3 = PythonOperator(
                task_id="3_batch_delete_source",
                python_callable=delete_tasks.t3_delete,
                op_kwargs={"config": cfg})
            t4 = PythonOperator(
                task_id="4_verify_range_empty",
                python_callable=delete_tasks.t4_verify_zero,
                op_kwargs={"config": cfg})
            t1 >> t2 >> t3 >> t4

    return dag


# ─────────────────────────────────────────────
# FACTORY LOOP — 1 YAML = 1 DAG
# ─────────────────────────────────────────────
for _cfg in _load_configs():
    globals()[_cfg["dag_id"]] = _build_dag(_cfg)
