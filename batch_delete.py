#!/usr/bin/env python3
"""
Batch Delete Script
Deletes rows in controlled batches to avoid long table locks.

Modes:
  Interactive : python3 batch_delete.py
  Config      : python3 batch_delete.py --config job.yaml
  Dry Run     : python3 batch_delete.py --config job.yaml --dry-run
"""

import pymysql
import csv
import time
import sys
import os
import getpass
import logging
import argparse
import yaml
from datetime import datetime, timedelta


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
    logger = logging.getLogger(f"batch_delete.{os.getpid()}")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(logfile)
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


def resolve_threshold(target_cfg):
    if "retention_days" in target_cfg and "threshold" in target_cfg:
        raise ValueError("Config error: specify either 'retention_days' or 'threshold', not both.")
    if "retention_days" in target_cfg:
        days = int(target_cfg["retention_days"])
        return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    if "threshold" in target_cfg:
        return str(target_cfg["threshold"])
    raise ValueError("Config error: 'retention_days' or 'threshold' is required in target section.")


def get_min_max(conn, db, table, column):
    with conn.cursor() as cur:
        sql = f"SELECT MIN(`{column}`), MAX(`{column}`) FROM `{db}`.`{table}`"
        cur.execute(sql)
        return cur.fetchone()


def export_to_csv(host, port, user, password, db, table, column, threshold, csv_path, logger, fetch_size=10000):
    logger.info(f"BACKUP | Exporting rows WHERE `{column}` < {threshold} to {csv_path}")
    export_start = datetime.now()

    conn = get_connection(host, port, user, password, db)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT column_name FROM information_schema.columns "
                f"WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
                (db, table),
            )
            columns = [row[0] for row in cur.fetchall()]

        with conn.cursor(pymysql.cursors.SSCursor) as cur:
            sql = f"SELECT * FROM `{db}`.`{table}` WHERE `{column}` < %s"
            cur.execute(sql, (threshold,))

            total_rows = 0
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(columns)

                while True:
                    rows = cur.fetchmany(fetch_size)
                    if not rows:
                        break
                    writer.writerows(rows)
                    total_rows += len(rows)
                    if total_rows % 100000 == 0:
                        logger.info(f"BACKUP | Exported {total_rows:,} rows so far...")

    finally:
        conn.close()

    export_end = datetime.now()
    file_size = os.path.getsize(csv_path)
    file_size_mb = file_size / (1024 * 1024)
    logger.info(
        f"BACKUP | Export complete: {total_rows:,} rows, {file_size_mb:.1f} MB "
        f"| start={export_start:%Y-%m-%d %H:%M:%S} end={export_end:%Y-%m-%d %H:%M:%S}"
    )
    return total_rows, file_size


def upload_to_gcs(local_path, bucket_name, gcs_prefix, credentials_file, logger):
    try:
        from google.cloud import storage
    except ImportError:
        logger.error("BACKUP | google-cloud-storage not installed. Run: pip install google-cloud-storage")
        return False

    filename = os.path.basename(local_path)
    blob_path = f"{gcs_prefix.rstrip('/')}/{filename}" if gcs_prefix else filename

    logger.info(f"BACKUP | Uploading {filename} to gs://{bucket_name}/{blob_path}")
    upload_start = datetime.now()

    try:
        client = storage.Client.from_service_account_json(credentials_file)
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        blob.upload_from_filename(local_path)
    except Exception as e:
        logger.error(f"BACKUP | GCS upload failed: {e}")
        return False

    upload_end = datetime.now()
    logger.info(
        f"BACKUP | Upload complete: gs://{bucket_name}/{blob_path} "
        f"| start={upload_start:%Y-%m-%d %H:%M:%S} end={upload_end:%Y-%m-%d %H:%M:%S}"
    )
    return True


def run_backup(host, port, user, password, db, table, column, threshold, backup_cfg, logger):
    local_dir = backup_cfg.get("local_dir", "/tmp")
    os.makedirs(local_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_filename = f"backup_{db}_{table}_{timestamp}.csv"
    csv_path = os.path.join(local_dir, csv_filename)

    total_rows, file_size = export_to_csv(
        host, port, user, password, db, table, column, threshold, csv_path, logger
    )

    if total_rows == 0:
        logger.info("BACKUP | No rows to backup, skipping.")
        if os.path.exists(csv_path):
            os.remove(csv_path)
        return True

    gcs_cfg = backup_cfg.get("gcs")
    if gcs_cfg and gcs_cfg.get("bucket"):
        credentials_file = gcs_cfg.get("credentials_file", "")
        if not credentials_file or not os.path.exists(credentials_file):
            logger.error(f"BACKUP | GCS credentials file not found: {credentials_file}")
            return False

        ok = upload_to_gcs(csv_path, gcs_cfg["bucket"], gcs_cfg.get("prefix", ""), credentials_file, logger)
        if not ok:
            return False

        if backup_cfg.get("delete_local_after_upload", True):
            os.remove(csv_path)
            logger.info(f"BACKUP | Local file removed after upload: {csv_path}")
    else:
        logger.info(f"BACKUP | CSV saved locally: {csv_path}")

    return True


def batch_delete(host, port, user, password, db, table, column, threshold, batch_size, sleep_sec, logfile, max_runtime_sec=0, backup_cfg=None):
    logger = setup_logger(logfile)
    logger.info(f"START | DELETE FROM `{db}`.`{table}` WHERE `{column}` < {threshold} | batch={batch_size} sleep={sleep_sec}s max_runtime={max_runtime_sec}s")

    try:
        conn = get_connection(host, port, user, password, db)
        min_before, max_before = get_min_max(conn, db, table, column)
        conn.close()
        logger.info(f"BEFORE | MIN={min_before} | MAX={max_before}")
    except Exception as e:
        logger.error(f"Failed to get BEFORE min/max: {e}")

    if backup_cfg and backup_cfg.get("enabled"):
        ok = run_backup(host, port, user, password, db, table, column, threshold, backup_cfg, logger)
        if not ok:
            logger.error("BACKUP FAILED | Aborting deletion. Fix backup issue and retry.")
            return 0

    total_deleted = 0
    iteration = 0
    run_start = time.monotonic()
    terminated_by_timeout = False

    while True:
        if max_runtime_sec > 0:
            elapsed = time.monotonic() - run_start
            if elapsed >= max_runtime_sec:
                logger.warning(
                    f"TERMINATED | Exceeding the time — elapsed={elapsed:.0f}s "
                    f"max_runtime={max_runtime_sec}s | deleted so far: {total_deleted:,}"
                )
                terminated_by_timeout = True
                break

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

    try:
        conn = get_connection(host, port, user, password, db)
        min_after, max_after = get_min_max(conn, db, table, column)
        conn.close()
        logger.info(f"AFTER  | MIN={min_after} | MAX={max_after}")
    except Exception as e:
        logger.error(f"Failed to get AFTER min/max: {e}")

    status = "TERMINATED (timeout)" if terminated_by_timeout else "FINISHED"
    logger.info(f"{status} | Total deleted: {total_deleted:,}")
    return total_deleted


def run_config_mode(config_path, dry_run=False):
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    conn_cfg = cfg["connection"]
    target_cfg = cfg["target"]
    batch_cfg = cfg.get("batch", {})
    backup_cfg = cfg.get("backup")

    host = conn_cfg["host"]
    port = conn_cfg.get("port", 3306)
    user = conn_cfg["user"]
    db = target_cfg["db"]
    table = target_cfg["table"]
    column = target_cfg["column"]
    batch_size = batch_cfg.get("size", 1000)
    sleep_sec = batch_cfg.get("sleep", 0.5)
    max_runtime_sec = int(batch_cfg.get("max_runtime_sec", 0))

    password_env = conn_cfg.get("password_env", "")
    if password_env:
        password = os.environ.get(password_env)
        if not password:
            print(f"[ERROR] Environment variable '{password_env}' is not set or empty.")
            sys.exit(1)
    elif "password" in conn_cfg:
        password = conn_cfg["password"]
    else:
        print("[ERROR] No password configured. Set 'password_env' or 'password' in connection config.")
        sys.exit(1)

    threshold = resolve_threshold(target_cfg)

    print(f"{'=' * 55}")
    print(f"  BATCH DELETE — Config Mode {'(DRY RUN)' if dry_run else ''}")
    print(f"{'=' * 55}")
    print(f"  Config    : {config_path}")
    print(f"  Host      : {host}:{port}")
    print(f"  Database  : {db}")
    print(f"  Table     : {table}")
    print(f"  Column    : {column}")
    print(f"  Threshold : < {threshold}")
    if "retention_days" in target_cfg:
        print(f"  Retention : {target_cfg['retention_days']} days")
    print(f"  Batch     : {batch_size} rows, sleep {sleep_sec}s")
    if max_runtime_sec > 0:
        print(f"  Max runtime : {max_runtime_sec}s ({max_runtime_sec/60:.1f} min)")
    else:
        print(f"  Max runtime : unlimited")

    if backup_cfg and backup_cfg.get("enabled"):
        print(f"  Backup    : enabled → {backup_cfg.get('local_dir', '/tmp')}")
        gcs_cfg = backup_cfg.get("gcs")
        if gcs_cfg and gcs_cfg.get("bucket"):
            print(f"  GCS       : gs://{gcs_cfg['bucket']}/{gcs_cfg.get('prefix', '')}")
    else:
        print(f"  Backup    : disabled")

    print(f"\n  Connecting...")
    try:
        conn = get_connection(host, port, user, password, db)
    except Exception as e:
        print(f"  [ERROR] Connection failed: {e}")
        sys.exit(1)
    print(f"  [OK] Connected to {host}:{port}")

    if not table_exists(conn, db, table):
        print(f"  [ERROR] Table `{table}` not found in database `{db}`.")
        conn.close()
        sys.exit(1)

    if not column_exists(conn, db, table, column):
        print(f"  [ERROR] Column `{column}` not found in table `{db}`.`{table}`.")
        conn.close()
        sys.exit(1)
    print(f"  [OK] Table and column verified")

    with conn.cursor() as cur:
        sql = f"SELECT MIN(`{column}`), MAX(`{column}`), COUNT(*) FROM `{db}`.`{table}`"
        cur.execute(sql)
        col_min, col_max, total_table = cur.fetchone()

    total_rows = pre_check(conn, db, table, column, threshold)

    with conn.cursor() as cur:
        sql = f"SELECT MIN(`{column}`), MAX(`{column}`) FROM `{db}`.`{table}` WHERE `{column}` >= %s"
        cur.execute(sql, (threshold,))
        min_after, max_after = cur.fetchone()

    conn.close()

    print(f"\n  [ Column Stats — Before ]")
    print(f"  MIN value   : {col_min}")
    print(f"  MAX value   : {col_max}")
    print(f"  Total rows  : {total_table:,}")
    print(f"  Rows to del : {total_rows:,}")

    print(f"\n  [ Column Stats — After (simulated) ]")
    print(f"  MIN value   : {min_after}")
    print(f"  MAX value   : {max_after}")
    print(f"  Rows kept   : {total_table - total_rows:,}")

    if total_rows == 0:
        print(f"\n  Nothing to delete. Done.")
        return

    est_batches = (total_rows + batch_size - 1) // batch_size
    est_time = est_batches * sleep_sec
    print(f"  Est batches : ~{est_batches:,}")
    print(f"  Est time    : ~{est_time:.0f}s")

    if dry_run:
        print(f"\n  [DRY RUN] All checks passed. No rows deleted.")
        print(f"  [DRY RUN] Would delete {total_rows:,} rows in ~{est_batches:,} batches.")
        if backup_cfg and backup_cfg.get("enabled"):
            print(f"  [DRY RUN] Backup would export {total_rows:,} rows to CSV before deletion.")
            gcs_cfg = backup_cfg.get("gcs")
            if gcs_cfg and gcs_cfg.get("bucket"):
                cred = gcs_cfg.get("credentials_file", "")
                if cred and os.path.exists(cred):
                    print(f"  [DRY RUN] GCS credentials file found: {cred}")
                else:
                    print(f"  [DRY RUN] [WARNING] GCS credentials file NOT found: {cred}")
        return

    log_dir = os.path.join(os.path.dirname(os.path.abspath(config_path)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logfile = os.path.join(log_dir, f"batch_delete_{db}_{table}_{timestamp}.log")

    print(f"\n  Executing...")
    print(f"  Logfile : {logfile}")
    total = batch_delete(host, port, user, password, db, table, column, threshold, batch_size, sleep_sec, logfile, max_runtime_sec, backup_cfg)
    print(f"\n  Done. Total deleted: {total:,}")


def run_interactive_mode():
    print("=" * 55)
    print("  BATCH DELETE — Interactive Mode")
    print("=" * 55)

    print("\n[ Connection Setup ]")
    host     = input("  Host / IP        : ").strip()
    port     = input("  Port     [3306]  : ").strip() or "3306"
    db       = input("  Database name    : ").strip()
    user     = input("  Username         : ").strip()
    password = getpass.getpass("  Password         : ").strip()

    print("\n  Connecting for pre-check...")
    try:
        conn = get_connection(host, port, user, password, db)
    except Exception as e:
        print(f"  [ERROR] Connection failed: {e}")
        sys.exit(1)

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

    with conn.cursor() as cur:
        sql = f"SELECT MIN(`{column}`), MAX(`{column}`), COUNT(*) FROM `{db}`.`{table}`"
        cur.execute(sql)
        col_min, col_max, total_table = cur.fetchone()

    print(f"\n[ Pre-Check: Column `{column}` ]")
    print(f"  MIN value   : {col_min}")
    print(f"  MAX value   : {col_max}")
    print(f"  Total rows  : {total_table:,}")

    print()
    threshold = input(f"  Delete where `{column}` < ? : ").strip()

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

    print("\n[ Batch Config ]")
    batch_size = input(f"  Batch size (rows per delete) [1000] : ").strip() or "1000"
    batch_size = int(batch_size)
    sleep_sec  = input(f"  Sleep between batches (sec)  [0.5]  : ").strip() or "0.5"
    sleep_sec  = float(sleep_sec)

    est_batches = (total_rows + batch_size - 1) // batch_size
    est_time    = est_batches * sleep_sec
    print(f"\n  Estimated: ~{est_batches:,} batches, ~{est_time:.0f}s minimum runtime")

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

    script_dir = os.path.dirname(os.path.abspath(__file__))
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    logfile    = os.path.join(script_dir, f"batch_delete_{db}_{table}_{timestamp}.log")

    pid = os.fork()

    if pid > 0:
        print(f"\n[ Running in background ]")
        print(f"  PID     : {pid}")
        print(f"  Logfile : {logfile}")
        print(f"\n  Monitor : tail -f {logfile}")
        print(f"  Stop    : kill {pid}")
        print(f"\n  Terminal aman ditutup.")
        sys.exit(0)

    os.setsid()
    sys.stdin.close()
    sys.stdout = open(os.devnull, "w")
    sys.stderr = open(os.devnull, "w")

    batch_delete(host, port, user, password, db, table, column, threshold, batch_size, sleep_sec, logfile)


def main():
    parser = argparse.ArgumentParser(description="Batch Delete — controlled row deletion")
    parser.add_argument("--config", help="Path to YAML config file (non-interactive mode)")
    parser.add_argument("--dry-run", action="store_true", help="Validate config and show scope without deleting")
    args = parser.parse_args()

    if args.config:
        run_config_mode(args.config, dry_run=args.dry_run)
    else:
        if args.dry_run:
            print("[ERROR] --dry-run requires --config")
            sys.exit(1)
        run_interactive_mode()


if __name__ == "__main__":
    main()
