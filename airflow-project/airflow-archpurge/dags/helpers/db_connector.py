"""
db_connector.py
Universal database connector: PostgreSQL / MySQL / Oracle.

Tipe DB TIDAK ditulis di YAML. Airflow Connection (Admin > Connections)
yang menentukan tipe-nya via field "Connection Type".

Return: (connection_object, db_type_string)
db_type: 'postgres' | 'mysql' | 'oracle'
"""

from airflow.hooks.base import BaseHook


def get_conn(conn_id: str):
    """
    Ambil detail koneksi dari Airflow Connection, buka koneksi DB.

    Analogi: conn_id itu nama di buku kontak. Fungsi ini yang
    menelepon nomornya, apapun operatornya (PG/MySQL/Oracle).
    """
    c = BaseHook.get_connection(conn_id)
    conn_type = (c.conn_type or "").lower()

    if conn_type in ("postgres", "postgresql"):
        import psycopg2
        conn = psycopg2.connect(
            host=c.host,
            port=c.port or 5432,
            dbname=c.schema,
            user=c.login,
            password=c.password,
        )
        return conn, "postgres"

    elif conn_type == "mysql":
        import mysql.connector
        conn = mysql.connector.connect(
            host=c.host,
            port=c.port or 3306,
            database=c.schema,
            user=c.login,
            password=c.password,
        )
        return conn, "mysql"

    elif conn_type == "oracle":
        import oracledb
        # c.schema di Airflow Connection = service name Oracle
        dsn = f"{c.host}:{c.port or 1521}/{c.schema}"
        conn = oracledb.connect(
            user=c.login,
            password=c.password,
            dsn=dsn,
        )
        return conn, "oracle"

    else:
        raise ValueError(
            f"Connection type '{conn_type}' pada conn_id '{conn_id}' "
            f"tidak disupport. Gunakan: postgres / mysql / oracle."
        )
