"""
delete_tasks.py — Task untuk DAG DELETE (archdelete_*)

PRINSIP UTAMA (safety net wajib):
  DATA DI SOURCE TIDAK AKAN PERNAH TERHAPUS SEBELUM
  TERBUKTI SUDAH ADA DI TARGET, DIBUKTIKAN DENGAN COUNT YANG SAMA.

Alur:
  t1_compute_cutoff : hitung cutoff (retention_days / override manual)
  t2_verify_match   : count source vs count target — HARUS SAMA
                      (dengan auto-adjust ke batas data terakhir di target,
                       untuk kasus DAG delete dijalankan beberapa hari
                       setelah DAG copy)
  t3_delete         : batch delete + sleep, HANYA range yang terverifikasi
  t4_verify_zero    : pastikan range yang dihapus benar-benar 0 di source

Kenapa ada "auto-adjust"?
  Copy jalan hari Minggu (cutoff = 14 April).
  Delete jalan hari Rabu  (cutoff = 17 April).
  Source punya data 14-17 April yang BELUM dicopy.
  Tanpa adjust -> count pasti mismatch -> selalu STOP.
  Dengan adjust -> batas delete diturunkan ke MAX(date) yang benar-benar
  sudah ada di target. Data 14-17 April TIDAK disentuh. Aman.
"""

import logging
from datetime import datetime, timedelta

from helpers.db_connector import get_conn
from helpers import db_operations as ops
from helpers.email_alert import send_custom_alert, parse_emails

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# TASK 1 — Hitung cutoff
# ─────────────────────────────────────────────
def t1_compute_cutoff(config, **context):
    # Override manual via "Trigger DAG w/ config":
    #   {"cutoff_date": "2026-04-14T00:00:00"}
    conf = (context.get("dag_run").conf or {}) if context.get("dag_run") else {}
    if conf.get("cutoff_date"):
        cutoff = datetime.fromisoformat(conf["cutoff_date"])
        log.info("Cutoff OVERRIDE dari trigger config: %s", cutoff)
    else:
        cutoff = datetime.now() - timedelta(days=int(config["retention_days"]))
        log.info("Cutoff dari retention_days (%s hari): %s",
                 config["retention_days"], cutoff)

    context["ti"].xcom_push(key="cutoff", value=cutoff.isoformat())


# ─────────────────────────────────────────────
# TASK 2 — SAFETY NET: count source == count target
# ─────────────────────────────────────────────
def t2_verify_match(config, **context):
    ti = context["ti"]
    cutoff = datetime.fromisoformat(ti.xcom_pull(key="cutoff"))
    emails = parse_emails(config.get("alert_email"))

    src_conn, src_type = get_conn(config["source_conn"])
    tgt_conn, tgt_type = get_conn(config["target_conn"])
    try:
        # ── Percobaan 1: full range < cutoff ──
        src_count = ops.count_rows(
            src_conn, src_type,
            config["source_table"], config["date_column"], upper=cutoff)
        tgt_count = ops.count_rows(
            tgt_conn, tgt_type,
            config["target_table"], config["date_column"], upper=cutoff)

        log.info("Count @ cutoff %s → source=%s | target=%s",
                 cutoff, src_count, tgt_count)

        if src_count == tgt_count:
            if src_count == 0:
                log.info("Tidak ada data pada range ini. Delete akan no-op.")
            ti.xcom_push(key="delete_upper", value=cutoff.isoformat())
            ti.xcom_push(key="delete_inclusive", value=False)  # pakai <
            ti.xcom_push(key="expected_delete", value=src_count)
            log.info("✅ MATCH. Range delete: %s < %s",
                     config["date_column"], cutoff)
            return

        # ── Percobaan 2: auto-adjust ke batas data terakhir di target ──
        log.warning("Mismatch pada cutoff penuh. "
                    "Mencoba adjust ke MAX(date) di target...")
        max_target = ops.get_max_date(
            tgt_conn, tgt_type,
            config["target_table"], config["date_column"], upper=cutoff)

        if max_target is None:
            _fail(config, emails, cutoff, src_count, tgt_count,
                  reason="Target KOSONG pada range ini — kemungkinan "
                         "DAG copy belum pernah jalan / belum sukses.")

        src_adj = ops.count_rows(
            src_conn, src_type,
            config["source_table"], config["date_column"],
            upper=max_target, upper_inclusive=True)
        tgt_adj = ops.count_rows(
            tgt_conn, tgt_type,
            config["target_table"], config["date_column"],
            upper=max_target, upper_inclusive=True)

        log.info("Count @ adjusted <= %s → source=%s | target=%s",
                 max_target, src_adj, tgt_adj)

        if src_adj == tgt_adj and src_adj > 0:
            ti.xcom_push(key="delete_upper", value=max_target.isoformat())
            ti.xcom_push(key="delete_inclusive", value=True)  # pakai <=
            ti.xcom_push(key="expected_delete", value=src_adj)
            log.info("✅ MATCH (adjusted). Range delete: %s <= %s. "
                     "Data setelah batas ini TIDAK disentuh "
                     "(belum dicopy).", config["date_column"], max_target)
            return

        _fail(config, emails, cutoff, src_adj, tgt_adj,
              reason=f"Mismatch bahkan setelah adjust ke {max_target}. "
                     f"Kemungkinan copy parsial / data berubah. "
                     f"Investigasi manual diperlukan.")
    finally:
        src_conn.close()
        tgt_conn.close()


def _fail(config, emails, cutoff, src_count, tgt_count, reason):
    send_custom_alert(
        emails,
        subject=f"[ARCHDELETE BLOCKED] {config['dag_id']} — delete DIBATALKAN",
        html_body=(
            f"<h3>Delete DIBATALKAN — safety net aktif</h3>"
            f"<p>Table: {config['source_table']}</p>"
            f"<p>Cutoff: {cutoff.isoformat()}</p>"
            f"<p>Source: <b>{src_count}</b> | Target: <b>{tgt_count}</b></p>"
            f"<p>Alasan: {reason}</p>"
            f"<p><b>TIDAK ADA DATA YANG DIHAPUS.</b></p>"
        ),
    )
    raise ValueError(
        f"DELETE DIBATALKAN. source={src_count}, target={tgt_count}. "
        f"{reason} — TIDAK ADA DATA YANG DIHAPUS."
    )


# ─────────────────────────────────────────────
# TASK 3 — Batch delete (hanya range terverifikasi)
# ─────────────────────────────────────────────
def t3_delete(config, **context):
    ti = context["ti"]
    expected = ti.xcom_pull(key="expected_delete")

    if expected == 0:
        log.info("Expected delete = 0. Tidak ada yang dihapus.")
        ti.xcom_push(key="row_deleted", value=0)
        return

    upper = datetime.fromisoformat(ti.xcom_pull(key="delete_upper"))
    inclusive = ti.xcom_pull(key="delete_inclusive")

    src_conn, src_type = get_conn(config["source_conn"])
    try:
        deleted = ops.batch_delete(
            src_conn, src_type,
            config["source_table"], config["date_column"],
            upper=upper, upper_inclusive=inclusive,
            batch_size=int(config.get("batch_size", 5000)),
            sleep_sec=float(config.get("delete_sleep", 0.5)),
        )
    finally:
        src_conn.close()

    ti.xcom_push(key="row_deleted", value=deleted)
    log.info("═" * 60)
    log.info("DELETED: %s rows (expected: %s)", deleted, expected)
    log.info("═" * 60)


# ─────────────────────────────────────────────
# TASK 4 — Verifikasi range sudah 0 di source
# ─────────────────────────────────────────────
def t4_verify_zero(config, **context):
    ti = context["ti"]
    expected = ti.xcom_pull(key="expected_delete")
    if expected == 0:
        log.info("No-op run. Selesai.")
        return

    upper = datetime.fromisoformat(ti.xcom_pull(key="delete_upper"))
    inclusive = ti.xcom_pull(key="delete_inclusive")
    deleted = ti.xcom_pull(key="row_deleted")
    emails = parse_emails(config.get("alert_email"))

    src_conn, src_type = get_conn(config["source_conn"])
    try:
        remaining = ops.count_rows(
            src_conn, src_type,
            config["source_table"], config["date_column"],
            upper=upper, upper_inclusive=inclusive)
    finally:
        src_conn.close()

    if remaining != 0:
        send_custom_alert(
            emails,
            subject=f"[ARCHDELETE WARNING] {config['dag_id']} — sisa row",
            html_body=(
                f"<p>Delete selesai tapi masih tersisa "
                f"<b>{remaining}</b> row pada range. "
                f"Deleted: {deleted} / expected: {expected}. "
                f"Cek apakah ada insert data historis saat delete berjalan. "
                f"Data yang tersisa AMAN di source — re-run untuk "
                f"membersihkan (verifikasi count akan diulang).</p>"
            ),
        )
        raise ValueError(
            f"Masih ada {remaining} row tersisa pada range delete. "
            f"Re-run DAG untuk verifikasi ulang & bersihkan sisa.")

    log.info("✅ DELETE SUCCESS & VERIFIED. "
             "Deleted %s rows, sisa 0 pada range.", deleted)
