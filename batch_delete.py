#!/usr/bin/env python3
"""
Batch Delete Script — Interactive Mode
Deletes rows in controlled batches to avoid long table locks.
"""

import pymysql
import time
import sys
import os
import getpass
import logging
from datetime import datetime


def get_connection(host, port, user, password, db):
    return pymysql.connect(
        host=host,
        port=int(port),
        user=user,
        password=password,
        database=db,
        autocommit=False,
    )


def pre_check(conn, db, table, column, threshold):
    with conn.cursor() as cur:
        sql = f"SELECT COUNT(*) FROM `{db}`.`{table}` WHERE `{column}` < %s"
        cur.execute(sql, (threshold,))
        return cur.fetchone()[0]


def table_exists(conn, db, table):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = %s",
            (db, table),
        )
        return cur.fetchone()[0] > 0


def column_exists(conn, db, table, column):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s AND column_name = %s",
            (db, table, column),
        )
        return cur.fetchone()[0] > 0


def setup_logger(logfile):
    logger = logging.getLogger("batch_delete")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(logfile)
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


def batch_delete(host, port, user, password, db, table, column, threshold, batch_size, sleep_sec, logfile):
    logger = setup_logger(logfile)
    logger.info(f"START | DELETE FROM `{db}`.`{table}` WHERE `{column}` < {threshold} | batch={batch_size} sleep={sleep_sec}s")

    total_deleted = 0
    iteration = 0

    while True:
        iteration += 1
        batch_start = datetime.now()
        try:
            conn = get_connection(host, port, user, password, db)
            with conn.cursor() as cur:
                sql = f"DELETE FROM `{db}`.`{table}` WHERE `{column}` < %s LIMIT %s"
                cur.execute(sql, (threshold, batch_size))
                affected = cur.rowcount
            conn.commit()
            conn.close()
        except Exception as e:
            batch_end = datetime.now()
            logger.error(f"[Batch {iteration}] ERROR: {e} | start={batch_start:%Y-%m-%d %H:%M:%S} end={batch_end:%Y-%m-%d %H:%M:%S}")
            break

        batch_end = datetime.now()
        total_deleted += affected
        logger.info(
            f"[Batch {iteration}] Deleted: {affected} | Total so far: {total_deleted:,} "
            f"| start={batch_start:%Y-%m-%d %H:%M:%S} end={batch_end:%Y-%m-%d %H:%M:%S}"
        )

        if affected == 0:
            break

        if sleep_sec > 0:
            time.sleep(sleep_sec)

    logger.info(f"FINISHED | Total deleted: {total_deleted:,}")
    return total_deleted


def main():
    print("=" * 55)
    print("  BATCH DELETE — Interactive Mode")
    print("=" * 55)

    # --- Connection Info ---
    print("\n[ Connection Setup ]")
    host     = input("  Host / IP        : ").strip()
    port     = input("  Port     [3306]  : ").strip() or "3306"
    db       = input("  Database name    : ").strip()
    user     = input("  Username         : ").strip()
    password = getpass.getpass("  Password         : ").strip()

    # --- Connect ---
    print("\n  Connecting for pre-check...")
    try:
        conn = get_connection(host, port, user, password, db)
    except Exception as e:
        print(f"  [ERROR] Connection failed: {e}")
        sys.exit(1)

    # --- Target Info with validation loop ---
    print("\n[ Delete Target ]")
    while True:
        table = input("  Table name       : ").strip()
        if not table_exists(conn, db, table):
            print(f"  [WARNING] Table `{table}` not found in database `{db}`. Please try again.")
            continue
        break

    while True:
        column = input("  Column name      : ").strip()
        if not column_exists(conn, db, table, column):
            print(f"  [WARNING] Column `{column}` not found in table `{db}`.`{table}`. Please try again.")
            continue
        break

    # --- Pre-check: MIN / MAX ---
    with conn.cursor() as cur:
        sql = f"SELECT MIN(`{column}`), MAX(`{column}`), COUNT(*) FROM `{db}`.`{table}`"
        cur.execute(sql)
        col_min, col_max, total_table = cur.fetchone()

    print(f"\n[ Pre-Check: Column `{column}` ]")
    print(f"  MIN value   : {col_min}")
    print(f"  MAX value   : {col_max}")
    print(f"  Total rows  : {total_table:,}")

    # --- User sets threshold ---
    print()
    threshold = input(f"  Delete where `{column}` < ? : ").strip()

    # --- Count affected rows ---
    total_rows = pre_check(conn, db, table, column, threshold)
    conn.close()

    print(f"\n[ Scope Summary ]")
    print(f"  Column      : `{column}`")
    print(f"  MIN value   : {col_min}")
    print(f"  MAX value   : {col_max}")
    print(f"  Threshold   : < {threshold}")
    print(f"  Rows to del : {total_rows:,}")

    if total_rows == 0:
        print("\n  Nothing to delete. Exiting.")
        return

    # --- Batch Config ---
    print("\n[ Batch Config ]")
    batch_size = input(f"  Batch size (rows per delete) [1000] : ").strip() or "1000"
    batch_size = int(batch_size)
    sleep_sec  = input(f"  Sleep between batches (sec)  [0.5]  : ").strip() or "0.5"
    sleep_sec  = float(sleep_sec)

    est_batches = (total_rows + batch_size - 1) // batch_size
    est_time    = est_batches * sleep_sec
    print(f"\n  Estimated: ~{est_batches:,} batches, ~{est_time:.0f}s minimum runtime")

    # --- Final Confirmation ---
    print("\n" + "=" * 55)
    print(f"  DELETE FROM `{db}`.`{table}`")
    print(f"  WHERE `{column}` < {threshold}")
    print(f"  LIMIT {batch_size} per batch | sleep {sleep_sec}s")
    print(f"  Scope: {total_rows:,} rows")
    print("=" * 55)
    confirm = input("\n  Type 'YES' to execute, anything else to abort: ").strip()

    if confirm != "YES":
        print("  Aborted.")
        return

    # --- Execute in background (fully detached) ---
    script_dir = os.path.dirname(os.path.abspath(__file__))
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    logfile    = os.path.join(script_dir, f"batch_delete_{db}_{table}_{timestamp}.log")

    pid = os.fork()

    if pid > 0:
        # Parent — print info and exit immediately
        print(f"\n[ Running in background ]")
        print(f"  PID     : {pid}")
        print(f"  Logfile : {logfile}")
        print(f"\n  Monitor : tail -f {logfile}")
        print(f"  Stop    : kill {pid}")
        print(f"\n  Terminal aman ditutup.")
        sys.exit(0)

    # Child — detach fully
    os.setsid()
    sys.stdin.close()
    sys.stdout = open(os.devnull, "w")
    sys.stderr = open(os.devnull, "w")

    batch_delete(host, port, user, password, db, table, column, threshold, batch_size, sleep_sec, logfile)


if __name__ == "__main__":
    main()
