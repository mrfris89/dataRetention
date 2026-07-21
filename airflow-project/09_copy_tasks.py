"""
copy_tasks.py — Task untuk DAG COPY (archcopy_*)

Alur:
  t1_count_source   : hitung window yang akan dicopy, catat row_before
  t2_check_target   : pastikan window di target masih KOSONG (anti duplikat)
  t3_transfer       : copy batch per batch (append only, commit per batch)
  t4_verify         : count target window == row_before? mismatch -> FAIL + email

KONSEP WINDOW (incremental, aman untuk run berulang):
  lower = MAX(date_col) yang SUDAH ADA di target   (None kalau target kosong)
  upper = NOW - retention_days (cutoff)
  Yang dicopy hanya: lower < date_col < upper
  -> data lama yang sudah pernah diarsip TIDAK disentuh, TIDAK diduplikat.

CATATAN PENTING:
  DAG ini TIDAK PERNAH menghapus apapun. Delete ada di DAG terpisah
  (archdelete_*) yang punya verifikasi count sendiri sebelum menghapus.
"""

import logging
from datetime import datetime, timedelta

from helpers.db_connector import get_conn
from helpers import db_operations as ops
from helpers.email_alert import send_custom_alert, parse_emails

log = logging.getLogger(__name__)


def _compute_cutoff(retention_days: int) -> datetime:
    return datetime.now() - timedelta(days=int(retention_days))


# ─────────────────────────────────────────────
# TASK 1 — Hitung window & row_before
# ─────────────────────────────────────────────
def t1_count_source(config, **context):
    cutoff = _compute_cutoff(config["retention_days"])

    src_conn, src_type = get_conn(config["source_conn"])
    tgt_conn, tgt_type = get_conn(config["target_conn"])
    try:
        # batas bawah = data terakhir yang sudah ada di target
        boundary = ops.get_max_date(
            tgt_conn, tgt_type,
            config["target_table"], config["date_column"],
            upper=cutoff,
        )

        row_before = ops.count_rows(
            src_conn, src_type,
            config["source_table"], config["date_column"],
            upper=cutoff, lower=boundary,
        )
    finally:
        src_conn.close()
        tgt_conn.close()

    ti = context["ti"]
    ti.xcom_push(key="cutoff", value=cutoff.isoformat())
    ti.xcom_push(key="boundary",
                 value=boundary.isoformat() if boundary else None)
    ti.xcom_push(key="row_before", value=row_before)

    log.info("═" * 60)
    log.info("COPY WINDOW  : (%s  <  %s  <  %s)",
             boundary or "-infinity", config["date_column"], cutoff)
    log.info("ROW BEFORE   : %s", row_before)
    log.info("═" * 60)

    if row_before == 0:
        log.info("Tidak ada data baru untuk diarsip. "
                 "Task berikutnya akan no-op.")


# ─────────────────────────────────────────────
# TASK 2 — Pastikan window di target KOSONG
# ─────────────────────────────────────────────
def t2_check_target(config, **context):
    ti = context["ti"]
    cutoff = datetime.fromisoformat(ti.xcom_pull(key="cutoff"))
    boundary_s = ti.xcom_pull(key="boundary")
    boundary = datetime.fromisoformat(boundary_s) if boundary_s else None

    tgt_conn, tgt_type = get_conn(config["target_conn"])
    try:
        existing = ops.count_rows(
            tgt_conn, tgt_type,
            config["target_table"], config["date_column"],
            upper=cutoff, lower=boundary,
        )
    finally:
        tgt_conn.close()

    if existing > 0:
        raise ValueError(
            f"STOP! Ditemukan {existing} row di target dalam window copy. "
            f"Kemungkinan sisa run sebelumnya yang gagal di tengah. "
            f"JANGAN TRUNCATE (target append-only). "
            f"Bersihkan HANYA window ini secara manual: "
            f"DELETE FROM {config['target_table']} "
            f"WHERE {config['date_column']} > '{boundary_s}' "
            f"AND {config['date_column']} < '{cutoff.isoformat()}' "
            f"— lalu re-run DAG ini."
        )
    log.info("Target window bersih (0 row). Aman untuk copy.")


# ─────────────────────────────────────────────
# TASK 3 — Transfer batch per batch (append only)
# ─────────────────────────────────────────────
def t3_transfer(config, **context):
    ti = context["ti"]
    row_before = ti.xcom_pull(key="row_before")

    if row_before == 0:
        log.info("row_before = 0, tidak ada yang ditransfer.")
        ti.xcom_push(key="row_transferred", value=0)
        return

    cutoff = datetime.fromisoformat(ti.xcom_pull(key="cutoff"))
    boundary_s = ti.xcom_pull(key="boundary")
    boundary = datetime.fromisoformat(boundary_s) if boundary_s else None
    batch_size = int(config.get("batch_size", 5000))

    src_conn, src_type = get_conn(config["source_conn"])
    tgt_conn, tgt_type = get_conn(config["target_conn"])

    total = 0
    try:
        for columns, rows in ops.fetch_batches(
            src_conn, src_type,
            config["source_table"], config["date_column"],
            upper=cutoff, lower=boundary, batch_size=batch_size,
        ):
            inserted = ops.insert_batch(
                tgt_conn, tgt_type,
                config["target_table"], columns, rows,
            )
            total += inserted
            log.info("Transferred batch: %s rows (total: %s / %s)",
                     inserted, total, row_before)
    finally:
        src_conn.close()
        tgt_conn.close()

    ti.xcom_push(key="row_transferred", value=total)
    log.info("TRANSFER SELESAI: %s rows", total)


# ─────────────────────────────────────────────
# TASK 4 — Verifikasi count
# ─────────────────────────────────────────────
def t4_verify(config, **context):
    ti = context["ti"]
    row_before = ti.xcom_pull(key="row_before")
    cutoff = datetime.fromisoformat(ti.xcom_pull(key="cutoff"))
    boundary_s = ti.xcom_pull(key="boundary")
    boundary = datetime.fromisoformat(boundary_s) if boundary_s else None
    emails = parse_emails(config.get("alert_email"))

    tgt_conn, tgt_type = get_conn(config["target_conn"])
    try:
        row_target = ops.count_rows(
            tgt_conn, tgt_type,
            config["target_table"], config["date_column"],
            upper=cutoff, lower=boundary,
        )
    finally:
        tgt_conn.close()

    log.info("═" * 60)
    log.info("VERIFY COPY  : source window = %s | target window = %s",
             row_before, row_target)
    log.info("═" * 60)

    if row_before != row_target:
        send_custom_alert(
            emails,
            subject=f"[ARCHCOPY FAILED] {config['dag_id']} count mismatch",
            html_body=(
                f"<h3>Copy verification GAGAL</h3>"
                f"<p>Table: {config['source_table']} → "
                f"{config['target_table']}</p>"
                f"<p>Source window: <b>{row_before}</b> | "
                f"Target window: <b>{row_target}</b></p>"
                f"<p>Window: ({boundary_s} , {cutoff.isoformat()})</p>"
                f"<p>Aksi: bersihkan window ini di target lalu re-run. "
                f"DELETE di source TIDAK akan berjalan.</p>"
            ),
        )
        raise ValueError(
            f"MISMATCH! source={row_before}, target={row_target}. "
            f"Copy dianggap GAGAL. Data source AMAN (tidak dihapus)."
        )

    log.info("✅ COPY SUCCESS & VERIFIED. "
             "Silakan trigger DAG delete secara manual bila sudah yakin.")
