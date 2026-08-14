import os
import sqlite3
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import create_engine, text


BASE_DIR = Path(__file__).resolve().parent
SQLITE_DB_PATH = BASE_DIR / "app.db"

load_dotenv()

DB_SERVER = os.getenv("DB_SERVER", "")
DB_NAME = os.getenv("DB_NAME", "MedrikSupportAssistant")
DB_DRIVER = os.getenv("DB_DRIVER", "ODBC Driver 17 for SQL Server")
DB_TRUSTED_CONNECTION = os.getenv("DB_TRUSTED_CONNECTION", "no").lower()
DB_USER = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")


TABLES_IN_ORDER = [
    "users",
    "auth_audit",
    "answer_feedback",
    "unanswered_questions",
    "knowledge_base",
    "activity_logs",
]


TABLES_REVERSE_ORDER = list(reversed(TABLES_IN_ORDER))


def make_sqlserver_engine():
    if DB_TRUSTED_CONNECTION == "yes":
        connection_string = (
            f"DRIVER={{{DB_DRIVER}}};"
            f"SERVER={DB_SERVER};"
            f"DATABASE={DB_NAME};"
            "Trusted_Connection=yes;"
            "TrustServerCertificate=yes;"
            "Connection Timeout=10;"
        )
    else:
        connection_string = (
            f"DRIVER={{{DB_DRIVER}}};"
            f"SERVER={DB_SERVER};"
            f"DATABASE={DB_NAME};"
            f"UID={DB_USER};"
            f"PWD={DB_PASSWORD};"
            "TrustServerCertificate=yes;"
            "Connection Timeout=10;"
        )

    connection_url = f"mssql+pyodbc:///?odbc_connect={quote_plus(connection_string)}"
    return create_engine(connection_url, echo=False, future=True)


def sqlite_table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,),
    ).fetchone()

    return row is not None


def get_sqlite_columns(conn: sqlite3.Connection, table_name: str):
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [row[1] for row in rows]


def get_sqlite_rows(conn: sqlite3.Connection, table_name: str):
    conn.row_factory = sqlite3.Row

    if not sqlite_table_exists(conn, table_name):
        return []

    rows = conn.execute(f"SELECT * FROM {table_name} ORDER BY id ASC").fetchall()
    return [dict(row) for row in rows]


def clear_sqlserver_tables(sql_conn):
    print("پاک‌سازی جدول‌های SQL Server...")

    for table_name in TABLES_REVERSE_ORDER:
        sql_conn.execute(text(f"DELETE FROM dbo.{table_name};"))

    for table_name in TABLES_IN_ORDER:
        sql_conn.execute(text(f"DBCC CHECKIDENT ('dbo.{table_name}', RESEED, 0);"))

    print("پاک‌سازی انجام شد.")


def insert_rows(sql_conn, table_name: str, rows: list[dict]):
    if not rows:
        print(f"{table_name}: داده‌ای برای انتقال ندارد.")
        return

    columns = list(rows[0].keys())

    column_sql = ", ".join(f"[{col}]" for col in columns)
    value_sql = ", ".join(f":{col}" for col in columns)

    insert_sql = text(
        f"""
        INSERT INTO dbo.{table_name} ({column_sql})
        VALUES ({value_sql})
        """
    )

    print(f"{table_name}: شروع انتقال {len(rows)} رکورد...")

    sql_conn.execute(text(f"SET IDENTITY_INSERT dbo.{table_name} ON;"))
    sql_conn.execute(insert_sql, rows)
    sql_conn.execute(text(f"SET IDENTITY_INSERT dbo.{table_name} OFF;"))

    print(f"{table_name}: انتقال انجام شد.")


def count_sqlserver_rows(sql_conn, table_name: str) -> int:
    row = sql_conn.execute(text(f"SELECT COUNT(*) AS total FROM dbo.{table_name};")).fetchone()
    return int(row.total or 0)


def main():
    if not SQLITE_DB_PATH.exists():
        raise FileNotFoundError(f"فایل SQLite پیدا نشد: {SQLITE_DB_PATH}")

    print("SQLite:", SQLITE_DB_PATH)
    print("SQL Server:", DB_SERVER)
    print("Database:", DB_NAME)

    sqlite_conn = sqlite3.connect(SQLITE_DB_PATH)
    sqlite_conn.row_factory = sqlite3.Row

    engine = make_sqlserver_engine()

    with engine.begin() as sql_conn:
        clear_sqlserver_tables(sql_conn)

        for table_name in TABLES_IN_ORDER:
            if not sqlite_table_exists(sqlite_conn, table_name):
                print(f"{table_name}: در SQLite وجود ندارد، رد شد.")
                continue

            rows = get_sqlite_rows(sqlite_conn, table_name)
            insert_rows(sql_conn, table_name, rows)

        print("\nخلاصه تعداد رکوردها در SQL Server:")
        for table_name in TABLES_IN_ORDER:
            total = count_sqlserver_rows(sql_conn, table_name)
            print(f"{table_name}: {total}")

    sqlite_conn.close()

    print("\nانتقال داده‌ها با موفقیت تمام شد.")


if __name__ == "__main__":
    main()
    