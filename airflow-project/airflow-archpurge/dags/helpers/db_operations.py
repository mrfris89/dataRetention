"""
db_operations.py
Operasi SQL yang aware perbedaan dialect PG / MySQL / Oracle:
  - Placeholder : PG/MySQL pakai %s, Oracle pakai :1 :2 :3
  - Batch delete: PG pakai ctid+LIMIT, MySQL pakai LIMIT, Oracle pakai ROWNUM
  - Semua write di-commit PER BATCH agar tidak locking lama.

Semua fungsi menerima (conn, db_type, ...) hasil dari db_connector.get_conn().
"""

import time
import logging

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Placeholder helper
# ─────────────────────────────────────────────
def _ph(db_type: str, n: int) -> str:
    """Placeholder untuk n parameter. PG/MySQL: %s,%s  Oracle: :1,:2"""
    if db_type == "oracle":
        return ",".join(f":{i + 1}" for i in range(n))
    return ",".join(["%s"] * n)


def _ph1(db_type: str, idx: int = 1) -> str:
    """Placeholder tunggal."""
    return f":{idx}" if db_type == "oracle" else "%s"


# ─────────────────────────────────────────────
# COUNT
# ─────────────────────────────────────────────
def count_rows(conn, db_type, table, date_col,
               upper, upper_inclusive=False,
               lower=None):
    """
    COUNT(*) WHERE date_col <  upper   (default)
                atau date_col <= upper   (upper_inclusive=True)
    Optional: AND date_col > lower  (untuk window incremental).
    """
    op = "<=" if upper_inclusive else "<"
    sql = f"SELECT COUNT(*) FROM {table} WHERE {date_col} {op} {_ph1(db_type, 1)}"
    params = [upper]
    if lower is not None:
        sql += f" AND {date_col} > {_ph1(db_type, 2)}"
        params.append(lower)

    cur = conn.cursor()
    cur.execute(sql, params)
    result = cur.fetchone()[0]
    cur.close()
    return int(result)


def get_max_date(conn, db_type, table, date_col, upper=None):
    """
    MAX(date_col) — dipakai untuk cari 'batas terakhir data yang
    sudah masuk target'. Return None kalau tabel/range kosong.
    """
    sql = f"SELECT MAX({date_col}) FROM {table}"
    params = []
    if upper is not None:
        sql += f" WHERE {date_col} < {_ph1(db_type, 1)}"
        params.append(upper)

    cur = conn.cursor()
    cur.execute(sql, params)
    result = cur.fetchone()[0]
    cur.close()
    return result


# ─────────────────────────────────────────────
# FETCH (source) — streaming per batch
# ─────────────────────────────────────────────
def fetch_batches(conn, db_type, table, date_col,
                  upper, lower=None, batch_size=5000):
    """
    Generator: yield (columns, rows) per batch.
    ORDER BY date_col WAJIB — supaya kalau copy gagal di tengah,
    batas data yang sudah masuk target jelas (MAX date di target),
    dan re-run bisa dianalisis dengan aman.
    """
    sql = f"SELECT * FROM {table} WHERE {date_col} < {_ph1(db_type, 1)}"
    params = [upper]
    if lower is not None:
        sql += f" AND {date_col} > {_ph1(db_type, 2)}"
        params.append(lower)
    sql += f" ORDER BY {date_col}"

    cur = conn.cursor()
    cur.arraysize = batch_size  # hint untuk Oracle
    cur.execute(sql, params)

    columns = [d[0] for d in cur.description]

    while True:
        rows = cur.fetchmany(batch_size)
        if not rows:
            break
        yield columns, rows

    cur.close()


# ─────────────────────────────────────────────
# INSERT (target) — batch append
# ─────────────────────────────────────────────
def insert_batch(conn, db_type, table, columns, rows):
    """
    Batch INSERT + COMMIT. Append only — TIDAK PERNAH truncate/replace.
    """
    col_list = ",".join(columns)
    placeholders = _ph(db_type, len(columns))
    sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"

    cur = conn.cursor()
    cur.executemany(sql, [tuple(r) for r in rows])
    conn.commit()
    cur.close()
    return len(rows)


# ─────────────────────────────────────────────
# BATCH DELETE (source) — pelan-pelan, commit per batch
# ─────────────────────────────────────────────
def batch_delete(conn, db_type, table, date_col,
                 upper, upper_inclusive=True,
                 batch_size=5000, sleep_sec=0.5):
    """
    Hapus per batch + jeda (sleep) supaya DB operasional tetap nafas.
    Analogi: keluarkan penonton 5000 orang per gelombang,
    bukan sekaligus 5 juta yang bikin pintu macet.

    Return total row terhapus.
    """
    op = "<=" if upper_inclusive else "<"
    ph = _ph1(db_type, 1)

    if db_type == "postgres":
        sql = (
            f"DELETE FROM {table} WHERE ctid IN ("
            f"  SELECT ctid FROM {table} "
            f"  WHERE {date_col} {op} {ph} LIMIT {int(batch_size)}"
            f")"
        )
    elif db_type == "mysql":
        sql = (
            f"DELETE FROM {table} "
            f"WHERE {date_col} {op} {ph} LIMIT {int(batch_size)}"
        )
    elif db_type == "oracle":
        sql = (
            f"DELETE FROM {table} "
            f"WHERE {date_col} {op} {ph} AND ROWNUM <= {int(batch_size)}"
        )
    else:
        raise ValueError(f"db_type '{db_type}' tidak disupport")

    total = 0
    batch_no = 0
    while True:
        cur = conn.cursor()
        cur.execute(sql, [upper])
        deleted = cur.rowcount
        conn.commit()
        cur.close()

        if deleted == 0:
            break

        total += deleted
        batch_no += 1
        log.info("DELETE batch #%s: %s rows (total: %s)", batch_no, deleted, total)
        time.sleep(sleep_sec)

    return total
