"""
email_alert.py
Email alert on failure.

Mekanisme utama: default_args email_on_failure=True (di dag_factory.py).
Airflow otomatis kirim email tiap task gagal — dengan syarat SMTP
sudah dikonfigurasi di airflow.cfg (lihat README).

File ini menyediakan helper tambahan untuk kirim email custom
(misal: laporan sukses / mismatch dengan detail angka).
"""

import logging
from airflow.utils.email import send_email

log = logging.getLogger(__name__)


def send_custom_alert(to_emails, subject, html_body):
    """
    Kirim email custom. Gagal kirim email TIDAK menghentikan DAG
    (email itu pelengkap, bukan bagian dari safety chain).
    """
    if not to_emails:
        log.warning("alert_email kosong, skip email.")
        return
    try:
        send_email(to=to_emails, subject=subject, html_content=html_body)
        log.info("Email alert terkirim ke %s", to_emails)
    except Exception as e:  # noqa
        log.error("Gagal kirim email (DAG tetap lanjut): %s", e)


def parse_emails(raw):
    """'a@x.com,b@x.com' -> ['a@x.com', 'b@x.com']"""
    if not raw:
        return []
    return [e.strip() for e in str(raw).split(",") if e.strip()]
