import os
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import create_engine, text


load_dotenv()

DB_SERVER = os.getenv("DB_SERVER", "")
DB_NAME = os.getenv("DB_NAME", "MedrikSupportAssistant")
DB_DRIVER = os.getenv("DB_DRIVER", "ODBC Driver 17 for SQL Server")
DB_TRUSTED_CONNECTION = os.getenv("DB_TRUSTED_CONNECTION", "no").lower()
DB_USER = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")


def make_engine():
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


def main():
    engine = make_engine()

    with engine.begin() as conn:
        print("در حال اصلاح ساختار SQL Server...")
        print("Server:", DB_SERVER)
        print("Database:", DB_NAME)

        conn.execute(
            text(
                """
                IF COL_LENGTH('dbo.users', 'must_change_password') IS NULL
                BEGIN
                    ALTER TABLE dbo.users
                    ADD must_change_password BIT NOT NULL
                        CONSTRAINT DF_users_must_change_password DEFAULT 0;
                END
                """
            )
        )

        result = conn.execute(
            text(
                """
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_NAME = 'users'
                ORDER BY ORDINAL_POSITION;
                """
            )
        )

        columns = [row.COLUMN_NAME for row in result.fetchall()]

        print("ستون‌های جدول users:")
        for col in columns:
            print("-", col)

        if "must_change_password" in columns:
            print("اصلاح انجام شد. ستون must_change_password وجود دارد.")
        else:
            print("خطا: ستون must_change_password هنوز ساخته نشده است.")


if __name__ == "__main__":
    main()
    