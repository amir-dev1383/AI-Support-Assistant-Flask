import os
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

db_server = os.getenv("DB_SERVER", "")
db_name = os.getenv("DB_NAME", "MedrikSupportAssistant")
db_driver = os.getenv("DB_DRIVER", "ODBC Driver 17 for SQL Server")
trusted_connection = os.getenv("DB_TRUSTED_CONNECTION", "no").lower()

db_user = os.getenv("DB_USER", "")
db_password = os.getenv("DB_PASSWORD", "")

print("در حال تست اتصال...")
print("Server:", db_server)
print("Database:", db_name)
print("Driver:", db_driver)
print("Trusted:", trusted_connection)

if trusted_connection == "yes":
    connection_string = (
        f"DRIVER={{{db_driver}}};"
        f"SERVER={db_server};"
        f"DATABASE={db_name};"
        "Trusted_Connection=yes;"
        "Connection Timeout=8;"
    )
else:
    connection_string = (
        f"DRIVER={{{db_driver}}};"
        f"SERVER={db_server};"
        f"DATABASE={db_name};"
        f"UID={db_user};"
        f"PWD={db_password};"
        "TrustServerCertificate=yes;"
        "Connection Timeout=8;"
    )

connection_url = f"mssql+pyodbc:///?odbc_connect={quote_plus(connection_string)}"

engine = create_engine(connection_url, echo=False, future=True)

try:
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT @@SERVERNAME AS server_name, DB_NAME() AS current_database")
        )
        row = result.fetchone()

        print("اتصال موفق بود.")
        print("SQL Server:", row.server_name)
        print("Database:", row.current_database)

except Exception as e:
    print("اتصال ناموفق بود.")
    print(e)