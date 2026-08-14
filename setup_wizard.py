#!/usr/bin/env python3
"""
Setup Wizard — Data Retention Scheduler
Generates YAML config files, crontab entries, and runs dry-run validation.
"""

import os
import sys
import yaml
import getpass
import subprocess
from datetime import datetime


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.path.join(SCRIPT_DIR, "jobs")
ENV_FILE = os.path.join(SCRIPT_DIR, ".env")
BATCH_SCRIPT = os.path.join(SCRIPT_DIR, "batch_delete.py")


def ask(prompt, default=None, required=True):
    suffix = f" [{default}]" if default else ""
    while True:
        val = input(f"  {prompt}{suffix} : ").strip()
        if not val and default:
            return default
        if not val and required:
            print("  [!] Value is required. Try again.")
            continue
        return val


def ask_int(prompt, default=None):
    while True:
        val = ask(prompt, default=str(default) if default else None)
        try:
            return int(val)
        except ValueError:
            print("  [!] Must be a number. Try again.")


def ask_float(prompt, default=None):
    while True:
        val = ask(prompt, default=str(default) if default else None)
        try:
            return float(val)
        except ValueError:
            print("  [!] Must be a number. Try again.")


def ask_choice(prompt, choices):
    labels = " / ".join(f"{i+1}) {c}" for i, c in enumerate(choices))
    while True:
        val = ask(f"{prompt} ({labels})")
        if val in [str(i+1) for i in range(len(choices))]:
            return choices[int(val) - 1]
        if val in choices:
            return val
        print(f"  [!] Choose: {labels}")


def ask_cron():
    print("\n  [ Schedule / Cron ]")
    print("  Quick presets:")
    print("    1) Every day at a specific hour")
    print("    2) Every week on a specific day")
    print("    3) Every month on a specific date")
    print("    4) Custom cron expression")
    choice = ask("Pick preset", default="1")

    if choice == "1":
        hour = ask_int("Hour (0-23)", default=2)
        minute = ask_int("Minute (0-59)", default=0)
        return f"{minute} {hour} * * *"

    if choice == "2":
        day_map = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 0}
        day = ask("Day of week (mon/tue/wed/thu/fri/sat/sun)", default="mon").lower()
        dow = day_map.get(day, day)
        hour = ask_int("Hour (0-23)", default=2)
        minute = ask_int("Minute (0-59)", default=0)
        return f"{minute} {hour} * * {dow}"

    if choice == "3":
        dom = ask_int("Day of month (1-28)", default=1)
        hour = ask_int("Hour (0-23)", default=2)
        minute = ask_int("Minute (0-59)", default=0)
        return f"{minute} {hour} {dom} * *"

    return ask("Cron expression (min hour dom month dow)")


def describe_cron(expr):
    parts = expr.split()
    if len(parts) != 5:
        return expr
    minute, hour, dom, month, dow = parts
    dow_names = {"0": "Sun", "1": "Mon", "2": "Tue", "3": "Wed", "4": "Thu", "5": "Fri", "6": "Sat", "7": "Sun"}
    time_str = f"{hour.zfill(2)}:{minute.zfill(2)}"
    if dom == "*" and month == "*" and dow == "*":
        return f"Every day at {time_str}"
    if dom == "*" and month == "*" and dow != "*":
        day = dow_names.get(dow, dow)
        return f"Every {day} at {time_str}"
    if dom != "*" and month == "*" and dow == "*":
        return f"Every month on day {dom} at {time_str}"
    return expr


def safe_filename(text):
    return "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in text)


def create_job():
    print("\n" + "=" * 55)
    print("  NEW RETENTION JOB")
    print("=" * 55)

    print("\n  [ Connection ]")
    host = ask("Host / IP")
    port = ask_int("Port", default=3306)
    user = ask("DB Username")
    password = getpass.getpass("  DB Password      : ").strip()
    password_env = "RETENTION_PWD_" + safe_filename(host).upper()
    print(f"  [OK] Password will be saved as {password_env} in .env")

    print("\n  [ Target Table ]")
    db = ask("Database name")
    table = ask("Table name")
    column = ask("Date/time column name")

    print("\n  [ Retention Policy ]")
    mode = ask_choice("Mode", ["retention_days", "fixed_threshold"])
    if mode == "retention_days":
        days = ask_int("Delete data older than N days")
        target_section = {"db": db, "table": table, "column": column, "retention_days": days}
    else:
        threshold = ask("Fixed threshold value (e.g. 2025-01-01)")
        target_section = {"db": db, "table": table, "column": column, "threshold": threshold}

    print("\n  [ Batch Config ]")
    batch_size = ask_int("Batch size (rows per DELETE)", default=1000)
    sleep_sec = ask_float("Sleep between batches (sec)", default=0.5)

    cron_expr = ask_cron()

    config = {
        "connection": {
            "host": host,
            "port": port,
            "user": user,
            "password_env": password_env,
        },
        "target": target_section,
        "batch": {
            "size": batch_size,
            "sleep": sleep_sec,
        },
    }

    filename = f"{safe_filename(host)}_{safe_filename(db)}_{safe_filename(table)}.yaml"
    return config, cron_expr, filename, password_env, password


def write_yaml(config, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def save_env_password(password_env, password):
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE) as f:
            content = f.read()
        if password_env in content:
            return
    with open(ENV_FILE, "a") as f:
        escaped = password.replace("'", "'\\''")
        f.write(f"export {password_env}='{escaped}'\n")
    os.chmod(ENV_FILE, 0o600)


def build_cron_line(cron_expr, yaml_path):
    return (
        f"{cron_expr} /bin/bash -c "
        f"'source {ENV_FILE} && "
        f"/usr/bin/python3 {BATCH_SCRIPT} --config {yaml_path}'"
    )


def load_env_file():
    env = os.environ.copy()
    if not os.path.exists(ENV_FILE):
        return env
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line.startswith("export ") and "=" in line:
                parts = line[len("export "):].split("=", 1)
                key = parts[0].strip()
                val = parts[1].strip().strip("'\"")
                env[key] = val
    return env


def run_dry_run(yaml_path):
    print(f"\n  [ Dry Run: {os.path.basename(yaml_path)} ]")
    env = load_env_file()

    result = subprocess.run(
        [sys.executable, BATCH_SCRIPT, "--config", yaml_path, "--dry-run"],
        env=env,
        capture_output=False,
    )
    return result.returncode == 0


def show_summary(jobs):
    print("\n" + "=" * 55)
    print("  SETUP SUMMARY")
    print("=" * 55)

    print(f"\n  Generated files:")
    for job in jobs:
        print(f"    - {job['yaml_path']}")
    if os.path.exists(ENV_FILE):
        print(f"    - {ENV_FILE}")

    print(f"\n  Crontab entries (copy-paste to 'crontab -e'):")
    print(f"  {'─' * 50}")
    for job in jobs:
        schedule_desc = describe_cron(job["cron_expr"])
        tgt = job["config"]["target"]
        print(f"  # {tgt['db']}.{tgt['table']} — {schedule_desc}")
        print(f"  {job['cron_line']}")
        print()

    print(f"  {'─' * 50}")
    print(f"  Passwords saved in : {ENV_FILE} (chmod 600)")
    print(f"  Log output dir     : {os.path.join(JOBS_DIR, 'logs/')}")
    print(f"\n  Next steps:")
    print(f"    1. crontab -e → paste the entries above")
    print(f"    2. Verify logs after first scheduled run")


def main():
    print("=" * 55)
    print("  DATA RETENTION — Scheduler Setup Wizard")
    print("=" * 55)

    jobs = []

    while True:
        config, cron_expr, filename, password_env, password = create_job()
        yaml_path = os.path.join(JOBS_DIR, filename)
        cron_line = build_cron_line(cron_expr, yaml_path)

        jobs.append({
            "config": config,
            "cron_expr": cron_expr,
            "cron_line": cron_line,
            "yaml_path": yaml_path,
            "password_env": password_env,
            "password": password,
        })

        print(f"\n  [OK] Job #{len(jobs)} configured: {filename}")
        another = input("\n  Add another job? (y/n) [n] : ").strip().lower()
        if another != "y":
            break

    print(f"\n{'=' * 55}")
    print(f"  WRITING CONFIG FILES...")
    print(f"{'=' * 55}")

    for job in jobs:
        write_yaml(job["config"], job["yaml_path"])
        print(f"  [OK] {job['yaml_path']}")
        save_env_password(job["password_env"], job["password"])
        print(f"  [OK] Password saved as {job['password_env']} in .env")

    if os.path.exists(ENV_FILE):
        print(f"  [OK] {ENV_FILE}")

    print(f"\n{'=' * 55}")
    print(f"  DRY RUN VALIDATION")
    print(f"{'=' * 55}")

    run_it = input("\n  Run dry-run now to validate? (y/n) [y] : ").strip().lower()
    if run_it != "n":
        all_ok = True
        for job in jobs:
            ok = run_dry_run(job["yaml_path"])
            if ok:
                print(f"  [PASS] {os.path.basename(job['yaml_path'])}")
            else:
                print(f"  [FAIL] {os.path.basename(job['yaml_path'])}")
                all_ok = False

        if all_ok:
            print(f"\n  All dry runs passed!")
        else:
            print(f"\n  [!] Some dry runs failed. Fix the issues before installing to crontab.")

    show_summary(jobs)


if __name__ == "__main__":
    main()
