import os
import re
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

from dotenv import load_dotenv
from flask import Flask, flash, g, jsonify, redirect, render_template, request, session, url_for
from rapidfuzz import fuzz
from sqlalchemy import create_engine, text
from werkzeug.security import check_password_hash, generate_password_hash

from accounting_qa_data import accounting_qa_data, greetings, quick_replies


BASE_DIR = Path(__file__).resolve().parent

load_dotenv()

app = Flask(__name__, template_folder="templates")
app.secret_key = os.getenv("APP_SECRET_KEY", "change-this-in-production")

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)

DB_SERVER = os.getenv("DB_SERVER", "")
DB_NAME = os.getenv("DB_NAME", "MedrikSupportAssistant")
DB_DRIVER = os.getenv("DB_DRIVER", "ODBC Driver 17 for SQL Server")
DB_TRUSTED_CONNECTION = os.getenv("DB_TRUSTED_CONNECTION", "no").lower()
DB_USER = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "ChangeMe123!")
DEFAULT_ADMIN_EMAIL = os.getenv("DEFAULT_ADMIN_EMAIL", "admin@example.com")
DEFAULT_ADMIN_NAME = os.getenv("DEFAULT_ADMIN_NAME", "مدیر سیستم")

MAX_FAILED_LOGIN_ATTEMPTS = int(os.getenv("MAX_FAILED_LOGIN_ATTEMPTS", "5"))
LOGIN_LOCK_MINUTES = int(os.getenv("LOGIN_LOCK_MINUTES", "15"))

UNANSWERED_SIMILARITY_THRESHOLD = 88

USER_ROLE_LABELS = {
    "admin": "مدیر سیستم",
    "support_manager": "مدیر پشتیبانی",
    "support_agent": "کارشناس پشتیبانی",
}

UNANSWERED_STATUS_LABELS = {
    "new": "جدید",
    "reviewed": "بررسی شد",
    "add_to_faq": "اضافه شود به پایگاه دانش",
    "duplicate": "تکراری / بی‌ارزش",
    "resolved": "حل شد",
}

FEEDBACK_REASON_LABELS = {
    "": "-",
    "wrong_answer": "پاسخ اشتباه بود",
    "incomplete_answer": "پاسخ کامل نبود",
    "misunderstood_question": "سؤال من را درست متوجه نشد",
    "wrong_path": "مسیر گفته‌شده در نرم‌افزار درست نبود",
    "other": "سایر موارد",
    "no_reason": "بدون دلیل ثبت‌شده",
}

ACTIVITY_ACTION_LABELS = {
    "keyword_group_created": "ثبت گروه کلیدواژه",
    "keyword_group_updated": "ویرایش گروه کلیدواژه",
    "keyword_group_toggled": "فعال/غیرفعال کردن گروه کلیدواژه",
    "unanswered_status_updated": "تغییر وضعیت سؤال بی‌پاسخ",
    "faq_created": "ثبت پاسخ در پایگاه دانش",
    "faq_updated": "ویرایش پاسخ پایگاه دانش",
    "faq_toggled": "فعال/غیرفعال کردن پاسخ پایگاه دانش",
    "user_created": "ایجاد کاربر جدید",
    "user_updated": "ویرایش اطلاعات کاربر",
    "user_toggled": "فعال/غیرفعال کردن کاربر",
    "user_password_reset": "تغییر رمز عبور کاربر",
}

ACTIVITY_ENTITY_LABELS = {
    "keyword_group": "گروه کلیدواژه",
    "unanswered_question": "سؤال بی‌پاسخ",
    "knowledge_base": "پایگاه دانش",
    "user": "کاربر",
}

CHAR_MAP = str.maketrans(
    {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ة": "ه",
        "أ": "ا",
        "إ": "ا",
        "ؤ": "و",
        "ئ": "ی",
        "ۀ": "ه",
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
    }
)

PRIORITY_BONUS = {
    "high": 5,
    "medium": 2,
    "low": 0,
}

GREETING_ANSWER = "سلام! خوشحالم می‌بینمت. چطور می‌توانم کمکتان کنم؟"


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

    return create_engine(
        connection_url,
        echo=False,
        future=True,
        pool_pre_ping=True,
    )


engine = make_sqlserver_engine()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def from_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None

    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def format_datetime(value: Optional[str]) -> str:
    if not value:
        return "-"

    try:
        dt = datetime.fromisoformat(str(value))
        return dt.strftime("%Y/%m/%d - %H:%M")
    except Exception:
        return str(value)


def normalize_text(text_value: Any) -> str:
    text_value = str(text_value or "").strip().lower().translate(CHAR_MAP)
    text_value = re.sub(r"[\u200c\u200f\u200e]", " ", text_value)
    text_value = re.sub(r"[^\w\s؟?]", " ", text_value, flags=re.UNICODE)
    text_value = re.sub(r"[؟?]", " ", text_value)
    text_value = re.sub(r"\s+", " ", text_value).strip()
    return text_value


def token_count(text_value: str) -> int:
    return len(text_value.split()) if text_value else 0


def get_db():
    if "db" not in g:
        g.db = engine.connect()

    return g.db


@app.teardown_appcontext
def close_db(_error: Optional[BaseException]) -> None:
    db = g.pop("db", None)

    if db is not None:
        db.close()


def db_fetchone(sql: str, params: Optional[Dict[str, Any]] = None):
    return get_db().execute(text(sql), params or {}).mappings().fetchone()


def db_fetchall(sql: str, params: Optional[Dict[str, Any]] = None):
    return get_db().execute(text(sql), params or {}).mappings().fetchall()


def db_execute(sql: str, params: Optional[Dict[str, Any]] = None):
    return get_db().execute(text(sql), params or {})


def db_commit() -> None:
    get_db().commit()


def init_db() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                IF OBJECT_ID(N'dbo.users', N'U') IS NULL
                BEGIN
                    CREATE TABLE dbo.users (
                        id INT IDENTITY(1,1) PRIMARY KEY,
                        username NVARCHAR(100) NOT NULL,
                        full_name NVARCHAR(200) NULL,
                        email NVARCHAR(255) NULL,
                        password_hash NVARCHAR(500) NOT NULL,
                        role NVARCHAR(50) NOT NULL DEFAULT N'support_agent',
                        is_active BIT NOT NULL DEFAULT 1,
                        failed_login_attempts INT NOT NULL DEFAULT 0,
                        locked_until NVARCHAR(80) NULL,
                        must_change_password BIT NOT NULL DEFAULT 0,
                        last_login_at NVARCHAR(80) NULL,
                        created_at NVARCHAR(80) NOT NULL
                    );
                END
                """
            )
        )

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

        conn.execute(
            text(
                """
                IF OBJECT_ID(N'dbo.auth_audit', N'U') IS NULL
                BEGIN
                    CREATE TABLE dbo.auth_audit (
                        id INT IDENTITY(1,1) PRIMARY KEY,
                        user_id INT NULL,
                        username_attempted NVARCHAR(100) NULL,
                        success BIT NOT NULL,
                        event_type NVARCHAR(50) NOT NULL,
                        ip_address NVARCHAR(100) NULL,
                        user_agent NVARCHAR(500) NULL,
                        details NVARCHAR(MAX) NULL,
                        created_at NVARCHAR(80) NOT NULL,
                        CONSTRAINT FK_auth_audit_users
                            FOREIGN KEY (user_id) REFERENCES dbo.users(id)
                    );
                END
                """
            )
        )

        conn.execute(
            text(
                """
                IF OBJECT_ID(N'dbo.answer_feedback', N'U') IS NULL
                BEGIN
                    CREATE TABLE dbo.answer_feedback (
                        id INT IDENTITY(1,1) PRIMARY KEY,
                        user_id INT NULL,
                        question NVARCHAR(MAX) NOT NULL,
                        answer NVARCHAR(MAX) NOT NULL,
                        category NVARCHAR(200) NULL,
                        rating NVARCHAR(50) NOT NULL,
                        reason NVARCHAR(100) NULL,
                        comment NVARCHAR(MAX) NULL,
                        created_at NVARCHAR(80) NOT NULL,
                        CONSTRAINT FK_answer_feedback_users
                            FOREIGN KEY (user_id) REFERENCES dbo.users(id)
                    );
                END
                """
            )
        )

        conn.execute(
            text(
                """
                IF OBJECT_ID(N'dbo.unanswered_questions', N'U') IS NULL
                BEGIN
                    CREATE TABLE dbo.unanswered_questions (
                        id INT IDENTITY(1,1) PRIMARY KEY,
                        user_id INT NULL,
                        question NVARCHAR(MAX) NOT NULL,
                        normalized_question NVARCHAR(MAX) NULL,
                        suggestions_text NVARCHAR(MAX) NULL,
                        has_suggestions BIT NOT NULL DEFAULT 0,
                        status NVARCHAR(50) NOT NULL DEFAULT N'new',
                        created_at NVARCHAR(80) NOT NULL,
                        CONSTRAINT FK_unanswered_questions_users
                            FOREIGN KEY (user_id) REFERENCES dbo.users(id)
                    );
                END
                """
            )
        )

        conn.execute(
            text(
                """
                IF OBJECT_ID(N'dbo.knowledge_base', N'U') IS NULL
                BEGIN
                    CREATE TABLE dbo.knowledge_base (
                        id INT IDENTITY(1,1) PRIMARY KEY,
                        question NVARCHAR(MAX) NOT NULL,
                        answer NVARCHAR(MAX) NOT NULL,
                        category NVARCHAR(200) NULL DEFAULT N'عمومی',
                        keywords_text NVARCHAR(MAX) NULL,
                        priority NVARCHAR(50) NULL DEFAULT N'medium',
                        is_active BIT NOT NULL DEFAULT 1,
                        created_at NVARCHAR(80) NOT NULL,
                        updated_at NVARCHAR(80) NOT NULL
                    );
                END
                """
            )
        )

        conn.execute(
            text(
                """
                IF OBJECT_ID(N'dbo.activity_logs', N'U') IS NULL
                BEGIN
                    CREATE TABLE dbo.activity_logs (

                        id INT IDENTITY(1,1) PRIMARY KEY,
                        actor_user_id INT NULL,
                        actor_username NVARCHAR(100) NULL,
                        actor_role NVARCHAR(50) NULL,
                        action NVARCHAR(100) NOT NULL,
                        entity_type NVARCHAR(100) NULL,
                        entity_id INT NULL,
                        details NVARCHAR(MAX) NULL,
                        ip_address NVARCHAR(100) NULL,
                        user_agent NVARCHAR(500) NULL,
                        created_at NVARCHAR(80) NOT NULL,
                        CONSTRAINT FK_activity_logs_users
                            FOREIGN KEY (actor_user_id) REFERENCES dbo.users(id)
                    );
                END
                """
            )
        )
        conn.execute(
            text(
                """
                IF OBJECT_ID(N'dbo.keyword_groups', N'U') IS NULL
                BEGIN
                    CREATE TABLE dbo.keyword_groups (
                        id INT IDENTITY(1,1) PRIMARY KEY,
                        title NVARCHAR(200) NOT NULL,
                        category NVARCHAR(200) NULL,
                        keywords_text NVARCHAR(MAX) NOT NULL,
                        is_active BIT NOT NULL DEFAULT 1,
                        created_at NVARCHAR(80) NOT NULL,
                        updated_at NVARCHAR(80) NOT NULL
                    );
                END
                """
            )
        )

        conn.execute(
            text(
                """
                UPDATE dbo.users
                SET role = N'support_agent'
                WHERE role IS NULL
                   OR role = ''
                   OR role = N'regular_user';
                """
            )
        )

        existing_user = conn.execute(
            text("SELECT TOP 1 id FROM dbo.users ORDER BY id ASC")
        ).mappings().fetchone()

        if not existing_user:
            conn.execute(
                text(
                    """
                    INSERT INTO dbo.users (
                        username,
                        full_name,
                        email,
                        password_hash,
                        role,
                        is_active,
                        failed_login_attempts,
                        locked_until,
                        must_change_password,
                        last_login_at,
                        created_at
                    ) VALUES (
                        :username,
                        :full_name,
                        :email,
                        :password_hash,
                        :role,
                        :is_active,
                        :failed_login_attempts,
                        :locked_until,
                        :must_change_password,
                        :last_login_at,
                        :created_at
                    )
                    """
                ),
                {
                    "username": DEFAULT_ADMIN_USERNAME,
                    "full_name": DEFAULT_ADMIN_NAME,
                    "email": DEFAULT_ADMIN_EMAIL,
                    "password_hash": generate_password_hash(DEFAULT_ADMIN_PASSWORD),
                    "role": "admin",
                    "is_active": 1,
                    "failed_login_attempts": 0,
                    "locked_until": None,
                    "must_change_password": 0,
                    "last_login_at": None,
                    "created_at": to_iso(utc_now()),
                },
            )

        existing_faq_count = conn.execute(
            text("SELECT COUNT(*) AS total FROM dbo.knowledge_base")
        ).mappings().fetchone()["total"]

        if int(existing_faq_count or 0) == 0:
            now = to_iso(utc_now())

            for item in accounting_qa_data:
                question = str(item.get("question", "")).strip()
                answer = str(item.get("answer", "")).strip()

                if not question or not answer:
                    continue

                keywords = item.get("keywords", [])
                keywords_text = "\n".join(
                    str(keyword).strip()
                    for keyword in keywords
                    if str(keyword).strip()
                )

                conn.execute(
                    text(
                        """
                        INSERT INTO dbo.knowledge_base (
                            question,
                            answer,
                            category,
                            keywords_text,
                            priority,
                            is_active,
                            created_at,
                            updated_at
                        ) VALUES (
                            :question,
                            :answer,
                            :category,
                            :keywords_text,
                            :priority,
                            :is_active,
                            :created_at,
                            :updated_at
                        )
                        """
                    ),
                    {
                        "question": question,
                        "answer": answer,
                        "category": str(item.get("category", "عمومی")).strip() or "عمومی",
                        "keywords_text": keywords_text,
                        "priority": str(item.get("priority", "medium")).strip() or "medium",
                        "is_active": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                )


def extract_request_data() -> Dict[str, Any]:
    if request.is_json:
        return request.get_json(silent=True) or {}

    return request.form.to_dict() or {}


def json_response(
    answers: List[str],
    matched_questions: Optional[List[str]] = None,
    categories: Optional[List[str]] = None,
    suggestions: Optional[List[str]] = None,
    status_code: int = 200,
):
    return (
        jsonify(
            {
                "answers": answers,
                "matched_questions": matched_questions or [],
                "categories": categories or [],
                "suggestions": suggestions or [],
            }
        ),
        status_code,
    )


def login_required_page(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))

        return view_func(*args, **kwargs)

    return wrapped


def login_required_api(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return json_response(["لطفاً ابتدا وارد شوید."], status_code=401)

        return view_func(*args, **kwargs)

    return wrapped


def admin_required_page(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))

        if session.get("role") != "admin":
            flash("شما دسترسی لازم برای مشاهده این بخش را ندارید.", "error")
            return redirect(url_for("home"))

        return view_func(*args, **kwargs)

    return wrapped


def support_manager_required_page(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))

        allowed_roles = ["admin", "support_manager"]

        if session.get("role") not in allowed_roles:
            flash("شما دسترسی لازم برای مشاهده این بخش را ندارید.", "error")
            return redirect(url_for("home"))

        return view_func(*args, **kwargs)

    return wrapped


def get_user_by_username(username: str):
    return db_fetchone(
        """
        SELECT TOP 1 *
        FROM dbo.users
        WHERE LOWER(username) = LOWER(:username)
        """,
        {"username": username},
    )


def get_user_by_id(user_id: int):
    return db_fetchone(
        """
        SELECT TOP 1 *
        FROM dbo.users
        WHERE id = :user_id
        """,
        {"user_id": user_id},
    )


def current_user():
    user_id = session.get("user_id")

    if not user_id:
        return None

    return get_user_by_id(int(user_id))


@app.context_processor
def inject_user() -> Dict[str, Any]:
    return {"current_user": current_user()}


def record_auth_event(
    event_type: str,
    success: bool,
    username_attempted: Optional[str] = None,
    user_id: Optional[int] = None,
    details: Optional[str] = None,
) -> None:
    db_execute(
        """
        INSERT INTO dbo.auth_audit (
            user_id,
            username_attempted,
            success,
            event_type,
            ip_address,
            user_agent,
            details,
            created_at
        ) VALUES (
            :user_id,
            :username_attempted,
            :success,
            :event_type,
            :ip_address,
            :user_agent,
            :details,
            :created_at
        )
        """,
        {
            "user_id": user_id,
            "username_attempted": username_attempted,
            "success": 1 if success else 0,
            "event_type": event_type,
            "ip_address": request.headers.get("X-Forwarded-For", request.remote_addr),
            "user_agent": request.headers.get("User-Agent", "")[:255],
            "details": details,
            "created_at": to_iso(utc_now()),
        },
    )

    db_commit()


def record_activity(
    action: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    details: Optional[str] = None,
) -> None:
    try:
        db_execute(
            """
            INSERT INTO dbo.activity_logs (
                actor_user_id,
                actor_username,
                actor_role,
                action,
                entity_type,
                entity_id,
                details,
                ip_address,
                user_agent,
                created_at
            ) VALUES (
                :actor_user_id,
                :actor_username,
                :actor_role,
                :action,
                :entity_type,
                :entity_id,
                :details,
                :ip_address,
                :user_agent,
                :created_at
            )
            """,
            {
                "actor_user_id": int(session.get("user_id")) if session.get("user_id") else None,
                "actor_username": session.get("username"),
                "actor_role": session.get("role"),
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "details": details,
                "ip_address": request.headers.get("X-Forwarded-For", request.remote_addr),
                "user_agent": request.headers.get("User-Agent", "")[:255],
                "created_at": to_iso(utc_now()),
            },
        )

        db_commit()
    except Exception:
        pass


def is_user_locked(user) -> bool:
    locked_until = from_iso(user["locked_until"])

    if not locked_until:
        return False

    return locked_until > utc_now()


def remaining_lock_minutes(user) -> int:
    locked_until = from_iso(user["locked_until"])

    if not locked_until:
        return 0

    delta = locked_until - utc_now()

    if delta.total_seconds() <= 0:
        return 0

    return max(1, int(delta.total_seconds() // 60))


def handle_failed_login(user, username_attempted: str) -> None:
    if user is None:
        record_auth_event("login", False, username_attempted=username_attempted)
        return

    attempts = int(user["failed_login_attempts"] or 0) + 1
    locked_until = None
    details = None

    if attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
        locked_until = to_iso(utc_now() + timedelta(minutes=LOGIN_LOCK_MINUTES))
        details = f"Account locked for {LOGIN_LOCK_MINUTES} minutes"
        attempts = 0

    db_execute(
        """
        UPDATE dbo.users
        SET failed_login_attempts = :attempts,
            locked_until = :locked_until
        WHERE id = :user_id
        """,
        {
            "attempts": attempts,
            "locked_until": locked_until,
            "user_id": user["id"],
        },
    )

    db_commit()

    record_auth_event(
        "login",
        False,
        username_attempted=username_attempted,
        user_id=user["id"],
        details=details,
    )


def handle_successful_login(user) -> None:
    db_execute(
        """
        UPDATE dbo.users
        SET failed_login_attempts = 0,
            locked_until = NULL,
            last_login_at = :last_login_at
        WHERE id = :user_id
        """,
        {
            "last_login_at": to_iso(utc_now()),
            "user_id": user["id"],
        },
    )

    db_commit()

    record_auth_event(
        "login",
        True,
        username_attempted=user["username"],
        user_id=user["id"],
    )


NORMALIZED_GREETINGS = [normalize_text(item) for item in greetings]

NORMALIZED_QUICK_REPLIES = {
    normalize_text(key): value
    for key, value in quick_replies.items()
}

QA_INDEX: List[Dict[str, Any]] = []

for item in accounting_qa_data:
    QA_INDEX.append(
        {
            **item,
            "normalized_question": normalize_text(item.get("question", "")),
            "normalized_keywords": [
                normalize_text(keyword)
                for keyword in item.get("keywords", [])
            ],
        }
    )


def parse_keywords_text(keywords_text: str) -> List[str]:
    raw_parts = re.split(r"[\n,،]+", str(keywords_text or ""))
    return [part.strip() for part in raw_parts if part.strip()]
def load_active_keyword_groups() -> List[Dict[str, Any]]:
    rows = db_fetchall(
        """
        SELECT
            id,
            title,
            category,
            keywords_text
        FROM dbo.keyword_groups
        WHERE is_active = 1
        ORDER BY id ASC
        """
    )

    groups = []

    for row in rows:
        title = str(row["title"] or "").strip()
        category = str(row["category"] or "").strip()
        keywords = parse_keywords_text(row["keywords_text"] or "")

        if not title and not keywords:
            continue

        normalized_terms = []

        for value in [title, category, *keywords]:
            normalized_value = normalize_text(value)

            if normalized_value:
                normalized_terms.append(normalized_value)

        groups.append(
            {
                "id": row["id"],
                "title": title,
                "category": category,
                "keywords": keywords,
                "normalized_terms": normalized_terms,
            }
        )

    return groups


def keyword_term_matches_question(normalized_question: str, normalized_term: str) -> bool:
    if not normalized_question or not normalized_term:
        return False

    if normalized_term in normalized_question or normalized_question in normalized_term:
        return True

    if fuzz.partial_ratio(normalized_term, normalized_question) >= 88:
        return True

    if fuzz.token_set_ratio(normalized_term, normalized_question) >= 82:
        return True

    return False


def expand_question_with_keyword_groups(normalized_question: str) -> str:
    if not normalized_question:
        return normalized_question

    expanded_terms = [normalized_question]
    seen_terms = {normalized_question}

    try:
        keyword_groups = load_active_keyword_groups()
    except Exception:
        return normalized_question

    for group in keyword_groups:
        terms = group.get("normalized_terms", [])

        matched = any(
            keyword_term_matches_question(normalized_question, term)
            for term in terms
        )

        if not matched:
            continue

        for term in terms:
            if term and term not in seen_terms:
                expanded_terms.append(term)
                seen_terms.add(term)

    return " ".join(expanded_terms)


def load_active_qa_index() -> List[Dict[str, Any]]:
    rows = db_fetchall(
        """
        SELECT
            id,
            question,
            answer,
            category,
            keywords_text,
            priority
        FROM dbo.knowledge_base
        WHERE is_active = 1
        ORDER BY id ASC
        """
    )

    items: List[Dict[str, Any]] = []

    for row in rows:
        question = str(row["question"] or "").strip()
        answer = str(row["answer"] or "").strip()

        if not question or not answer:
            continue

        keywords = parse_keywords_text(row["keywords_text"] or "")

        items.append(
            {
                "id": row["id"],
                "question": question,
                "answer": answer,
                "category": row["category"] or "عمومی",
                "keywords": keywords,
                "priority": row["priority"] or "medium",
                "normalized_question": normalize_text(question),
                "normalized_keywords": [normalize_text(keyword) for keyword in keywords],
            }
        )

    if items:
        return items

    return QA_INDEX


def get_exact_or_quick_reply(normalized_question: str) -> Optional[str]:
    if not normalized_question:
        return None

    if normalized_question in NORMALIZED_QUICK_REPLIES:
        return NORMALIZED_QUICK_REPLIES[normalized_question]

    if token_count(normalized_question) <= 3:
        for key, reply in NORMALIZED_QUICK_REPLIES.items():
            if fuzz.ratio(key, normalized_question) >= 88:
                return reply

        for greeting in NORMALIZED_GREETINGS:
            if fuzz.ratio(greeting, normalized_question) >= 90:
                return GREETING_ANSWER

    return None


def score_qa_match(normalized_question: str, qa_item: Dict[str, Any]) -> float:
    qa_question = qa_item["normalized_question"]

    token_score = fuzz.token_set_ratio(normalized_question, qa_question)
    partial_score = fuzz.partial_ratio(normalized_question, qa_question)

    keyword_hits = 0
    keywords = qa_item.get("normalized_keywords", [])

    for keyword in keywords:
        if not keyword:
            continue

        if keyword in normalized_question or normalized_question in keyword:
            keyword_hits += 1
            continue

        if fuzz.partial_ratio(keyword, normalized_question) >= 88:
            keyword_hits += 1

    keyword_score = (keyword_hits / len(keywords) * 100) if keywords else 0

    final_score = (
        token_score * 0.60
        + partial_score * 0.25
        + keyword_score * 0.15
        + PRIORITY_BONUS.get(str(qa_item.get("priority", "")).lower(), 0)
    )

    return round(min(final_score, 100), 2)


def search_best_answers(normalized_question: str) -> List[Dict[str, Any]]:
    scored_items = []
    qa_items = load_active_qa_index()
    expanded_question = expand_question_with_keyword_groups(normalized_question)

    for qa_item in qa_items:
        raw_score = score_qa_match(normalized_question, qa_item)
        expanded_score = score_qa_match(expanded_question, qa_item)

        score = max(raw_score, expanded_score)

        scored_items.append({"score": score, "item": qa_item})

    scored_items.sort(key=lambda item: item["score"], reverse=True)

    if not scored_items:
        return []

    best_score = scored_items[0]["score"]

    if best_score < 68:
        return []

    selected = [scored_items[0]]

    if len(scored_items) > 1:
        second = scored_items[1]

        if second["score"] >= 68 and (best_score - second["score"]) <= 6:
            selected.append(second)

    return selected


def get_related_questions(normalized_question: str, limit: int = 3) -> List[str]:
    scored_items = []
    qa_items = load_active_qa_index()
    expanded_question = expand_question_with_keyword_groups(normalized_question)

    for qa_item in qa_items:
        raw_score = score_qa_match(normalized_question, qa_item)
        expanded_score = score_qa_match(expanded_question, qa_item)

        score = max(raw_score, expanded_score)
        question = str(qa_item.get("question", "")).strip()

        if question and score >= 35:
            scored_items.append(
                {
                    "score": score,
                    "question": question,
                }
            )

    scored_items.sort(key=lambda item: item["score"], reverse=True)

    suggestions = []
    seen_questions = set()

    for item in scored_items:
        question = item["question"]

        if question in seen_questions:
            continue

        suggestions.append(question)
        seen_questions.add(question)

        if len(suggestions) >= limit:
            break

    return suggestions


def log_unanswered_question(
    raw_question: str,
    normalized_question: str,
    suggestions: Optional[List[str]] = None,
) -> None:
    suggestions = suggestions or []
    user_id = session.get("user_id")

    db_execute(
        """
        INSERT INTO dbo.unanswered_questions (
            user_id,
            question,
            normalized_question,
            suggestions_text,
            has_suggestions,
            status,
            created_at
        ) VALUES (
            :user_id,
            :question,
            :normalized_question,
            :suggestions_text,
            :has_suggestions,
            :status,
            :created_at
        )
        """,
        {
            "user_id": int(user_id) if user_id else None,
            "question": raw_question,
            "normalized_question": normalized_question,
            "suggestions_text": "\n".join(suggestions),
            "has_suggestions": 1 if suggestions else 0,
            "status": "new",
            "created_at": to_iso(utc_now()),
        },
    )

    db_commit()


def group_unanswered_questions(rows: List[Any]) -> List[Dict[str, Any]]:
    groups: List[Dict[str, Any]] = []

    for row in rows:
        question = row["question"] or "-"
        normalized = row["normalized_question"] or normalize_text(question)
        suggestions_text = row["suggestions_text"] or "-"
        created_at = row["created_at"] or ""

        matched_group = None

        for group in groups:
            similarity_score = max(
                fuzz.ratio(normalized, group["normalized_question"]),
                fuzz.token_set_ratio(normalized, group["normalized_question"]),
            )

            if similarity_score >= UNANSWERED_SIMILARITY_THRESHOLD:
                matched_group = group
                break

        if matched_group is None:
            groups.append(
                {
                    "normalized_question": normalized,
                    "sample_question": question,
                    "total_count": 1,
                    "last_asked_at": created_at,
                    "suggestions_text": suggestions_text,
                    "suggestions_count": int(row["has_suggestions"] or 0),
                    "status_label": "جدید",
                }
            )
        else:
            matched_group["total_count"] += 1
            matched_group["suggestions_count"] += int(row["has_suggestions"] or 0)

            if created_at > matched_group["last_asked_at"]:
                matched_group["last_asked_at"] = created_at
                matched_group["sample_question"] = question

                if suggestions_text and suggestions_text != "-":
                    matched_group["suggestions_text"] = suggestions_text

    groups.sort(
        key=lambda item: (item["total_count"], item["last_asked_at"]),
        reverse=True,
    )

    result = []

    for group in groups[:100]:
        result.append(
            {
                "question": group["sample_question"] or "-",
                "total_count": int(group["total_count"] or 0),
                "last_asked_at": format_datetime(group["last_asked_at"]),
                "suggestions_text": group["suggestions_text"] or "-",
                "suggestions_count": int(group["suggestions_count"] or 0),
                "status_label": group["status_label"],
            }
        )

    return result


@app.route("/", methods=["GET"])
def root():
    session.clear()
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        data = extract_request_data()

        username = str(data.get("username", "")).strip()
        password = str(data.get("password", "")).strip()
        wants_json = request.is_json or "application/json" in request.headers.get("Accept", "")

        if not username or not password:
            message = "نام کاربری و رمز عبور الزامی است."

            if wants_json:
                return jsonify({"success": False, "message": message}), 400

            flash(message, "error")
            return render_template("login.html", username=username)

        user = get_user_by_username(username)

        if user is None:
            record_auth_event("login", False, username_attempted=username)
            message = "نام کاربری یا رمز عبور نادرست است."

            if wants_json:
                return jsonify({"success": False, "message": message}), 401

            flash(message, "error")
            return render_template("login.html", username=username)

        if not int(user["is_active"]):
            record_auth_event(
                "login",
                False,
                username_attempted=username,
                user_id=user["id"],
                details="inactive user",
            )

            message = "این حساب کاربری غیرفعال است."

            if wants_json:
                return jsonify({"success": False, "message": message}), 403

            flash(message, "error")
            return render_template("login.html", username=username)

        if is_user_locked(user):
            minutes = remaining_lock_minutes(user)

            record_auth_event(
                "login",
                False,
                username_attempted=username,
                user_id=user["id"],
                details="locked account",
            )

            message = f"حساب شما موقتاً قفل شده است. {minutes} دقیقه دیگر دوباره تلاش کنید."

            if wants_json:
                return jsonify({"success": False, "message": message}), 423

            flash(message, "error")
            return render_template("login.html", username=username)

        if not check_password_hash(user["password_hash"], password):
            handle_failed_login(user, username)

            message = "نام کاربری یا رمز عبور نادرست است."

            if wants_json:
                return jsonify({"success": False, "message": message}), 401

            flash(message, "error")
            return render_template("login.html", username=username)

        session.clear()
        session["logged_in"] = True
        session["user_id"] = int(user["id"])
        session["username"] = str(user["username"])
        session["role"] = str(user["role"])
        session.permanent = True

        handle_successful_login(user)

        if wants_json:
            return jsonify({"success": True, "redirect": url_for("home")}), 200

        return redirect(url_for("home"))

    return render_template("login.html", username="")


@app.route("/logout", methods=["GET", "POST"])
def logout():
    user = current_user()

    if user is not None:
        record_auth_event(
            "logout",
            True,
            username_attempted=user["username"],
            user_id=user["id"],
        )

    session.clear()
    return redirect(url_for("login"))


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    flash("بازیابی رمز عبور هنوز فعال نشده است. لطفاً با مدیر سیستم تماس بگیرید.", "warning")
    return redirect(url_for("login"))


@app.route("/change-password", methods=["GET", "POST"])
@login_required_page
def change_password():
    flash("بخش تغییر رمز عبور در مرحله بعدی فعال می‌شود.", "warning")
    return redirect(url_for("home"))


@app.route("/home", methods=["GET"])
@login_required_page
def home():
    return render_template("index.html")


@app.route("/ask", methods=["POST"])
@login_required_api
def ask():
    data = extract_request_data()
    raw_question = str(data.get("question", "")).strip()

    if not raw_question:
        return json_response(["متن سؤال خالی است."], status_code=400)

    normalized_question = normalize_text(raw_question)

    if not normalized_question:
        return json_response(["متن سؤال خالی است."], status_code=400)

    quick_answer = get_exact_or_quick_reply(normalized_question)

    if quick_answer:
        return json_response(
            answers=[quick_answer],
            matched_questions=[raw_question],
            categories=["عمومی"],
        )

    best_matches = search_best_answers(normalized_question)

    if not best_matches:
        suggestions = get_related_questions(normalized_question, limit=3)

        log_unanswered_question(
            raw_question=raw_question,
            normalized_question=normalized_question,
            suggestions=suggestions,
        )

        if suggestions:
            return json_response(
                answers=[
                    "جواب دقیقی برای این سؤال پیدا نکردم، اما چند سؤال مرتبط پیدا شد که ممکن است به شما کمک کند."
                ],
                suggestions=suggestions,
            )

        return json_response(
            answers=[
                "متأسفم، جواب دقیقی برای این سؤال پیدا نکردم. لطفاً سؤال را واضح‌تر یا با جزئیات بیشتری بپرسید."
            ]
        )

    answers = []
    matched_questions = []
    categories = []
    seen_answers = set()

    for match in best_matches:
        qa_item = match["item"]
        answer = str(qa_item.get("answer", "")).strip()

        if not answer or answer in seen_answers:
            continue

        answers.append(answer)
        matched_questions.append(str(qa_item.get("question", raw_question)))
        categories.append(str(qa_item.get("category", "عمومی")))
        seen_answers.add(answer)

    if not answers:
        suggestions = get_related_questions(normalized_question, limit=3)

        log_unanswered_question(
            raw_question=raw_question,
            normalized_question=normalized_question,
            suggestions=suggestions,
        )

        return json_response(
            answers=[
                "متأسفم، جواب دقیقی برای این سؤال پیدا نکردم. لطفاً سؤال را واضح‌تر یا با جزئیات بیشتری بپرسید."
            ],
            suggestions=suggestions,
        )

    return json_response(answers, matched_questions, categories)


@app.route("/feedback", methods=["POST"])
@login_required_api
def feedback():
    data = extract_request_data()

    question = str(data.get("question", "")).strip()
    answer = str(data.get("answer", "")).strip()
    category = str(data.get("category", "")).strip()
    rating = str(data.get("rating", "")).strip()
    reason = str(data.get("reason", "")).strip()
    comment = str(data.get("comment", "")).strip()

    if rating not in ["useful", "not_useful"]:
        return jsonify({"success": False, "message": "نوع بازخورد نامعتبر است."}), 400

    if not question or not answer:
        return jsonify({"success": False, "message": "اطلاعات بازخورد کامل نیست."}), 400

    if rating == "useful":
        reason = ""
        comment = ""

    user_id = session.get("user_id")

    db_execute(
        """
        INSERT INTO dbo.answer_feedback (
            user_id,
            question,
            answer,
            category,
            rating,
            reason,
            comment,
            created_at
        ) VALUES (
            :user_id,
            :question,
            :answer,
            :category,
            :rating,
            :reason,
            :comment,
            :created_at
        )
        """,
        {
            "user_id": int(user_id) if user_id else None,
            "question": question,
            "answer": answer,
            "category": category,
            "rating": rating,
            "reason": reason,
            "comment": comment,
            "created_at": to_iso(utc_now()),
        },
    )

    db_commit()

    return jsonify({"success": True}), 200


@app.route("/admin/unanswered-question/<int:question_id>/status", methods=["POST"])
@support_manager_required_page
def update_unanswered_question_status(question_id):
    selected_status = str(request.form.get("status", "")).strip()

    if selected_status not in UNANSWERED_STATUS_LABELS:
        flash("وضعیت انتخاب‌شده معتبر نیست.", "error")
        return redirect(url_for("feedback_report"))

    db_execute(
        """
        UPDATE dbo.unanswered_questions
        SET status = :status
        WHERE id = :question_id
        """,
        {
            "status": selected_status,
            "question_id": question_id,
        },
    )

    db_commit()

    record_activity(
        action="unanswered_status_updated",
        entity_type="unanswered_question",
        entity_id=question_id,
        details=f"status={selected_status}",
    )

    flash("وضعیت سؤال بی‌پاسخ به‌روزرسانی شد.", "success")
    return redirect(url_for("feedback_report"))


@app.route("/admin/faq", methods=["GET", "POST"])
@support_manager_required_page
def admin_faq():
    if request.method == "POST":
        question = str(request.form.get("question", "")).strip()
        answer = str(request.form.get("answer", "")).strip()
        category = str(request.form.get("category", "عمومی")).strip() or "عمومی"
        keywords_text = str(request.form.get("keywords_text", "")).strip()
        priority = str(request.form.get("priority", "medium")).strip() or "medium"
        source_unanswered_id = request.form.get("source_unanswered_id", "").strip()

        if priority not in ["high", "medium", "low"]:
            priority = "medium"

        if not question or not answer:
            flash("سؤال و پاسخ الزامی هستند.", "error")
            return redirect(url_for("admin_faq"))

        now = to_iso(utc_now())

        result = db_execute(
            """
            INSERT INTO dbo.knowledge_base (
                question,
                answer,
                category,
                keywords_text,
                priority,
                is_active,
                created_at,
                updated_at
            )
            OUTPUT INSERTED.id
            VALUES (
                :question,
                :answer,
                :category,
                :keywords_text,
                :priority,
                :is_active,
                :created_at,
                :updated_at
            )
            """,
            {
                "question": question,
                "answer": answer,
                "category": category,
                "keywords_text": keywords_text,
                "priority": priority,
                "is_active": 1,
                "created_at": now,
                "updated_at": now,
            },
        )

        new_faq_id = int(result.scalar() or 0)

        if source_unanswered_id.isdigit():
            db_execute(
                """
                UPDATE dbo.unanswered_questions
                SET status = :status
                WHERE id = :source_unanswered_id
                """,
                {
                    "status": "resolved",
                    "source_unanswered_id": int(source_unanswered_id),
                },
            )

        db_commit()

        record_activity(
            action="faq_created",
            entity_type="knowledge_base",
            entity_id=new_faq_id,
            details=f"question={question[:120]}",
        )

        flash("پاسخ جدید با موفقیت در پایگاه دانش ثبت شد.", "success")
        return redirect(url_for("admin_faq"))

    source_unanswered_id = request.args.get("source_unanswered_id", type=int)
    source_question = ""

    if source_unanswered_id:
        row = db_fetchone(
            """
            SELECT TOP 1 question
            FROM dbo.unanswered_questions
            WHERE id = :source_unanswered_id
            """,
            {"source_unanswered_id": source_unanswered_id},
        )

        if row:
            source_question = row["question"] or ""

    faq_items = db_fetchall(
        """
        SELECT TOP 500
            id,
            question,
            answer,
            category,
            keywords_text,
            priority,
            is_active,
            created_at,
            updated_at
        FROM dbo.knowledge_base
        ORDER BY is_active DESC, updated_at DESC, id DESC
        """
    )

    return render_template(
        "admin_faq.html",
        faq_items=faq_items,
        source_unanswered_id=source_unanswered_id,
        source_question=source_question,
    )


@app.route("/admin/faq/<int:faq_id>/edit", methods=["POST"])
@support_manager_required_page
def edit_faq(faq_id):
    question = str(request.form.get("question", "")).strip()
    answer = str(request.form.get("answer", "")).strip()
    category = str(request.form.get("category", "عمومی")).strip() or "عمومی"
    keywords_text = str(request.form.get("keywords_text", "")).strip()
    priority = str(request.form.get("priority", "medium")).strip() or "medium"

    if priority not in ["high", "medium", "low"]:
        priority = "medium"

    if not question or not answer:
        flash("سؤال و پاسخ الزامی هستند.", "error")
        return redirect(url_for("admin_faq"))

    db_execute(
        """
        UPDATE dbo.knowledge_base
        SET
            question = :question,
            answer = :answer,
            category = :category,
            keywords_text = :keywords_text,
            priority = :priority,
            updated_at = :updated_at
        WHERE id = :faq_id
        """,
        {
            "question": question,
            "answer": answer,
            "category": category,
            "keywords_text": keywords_text,
            "priority": priority,
            "updated_at": to_iso(utc_now()),
            "faq_id": faq_id,
        },
    )

    db_commit()

    record_activity(
        action="faq_updated",
        entity_type="knowledge_base",
        entity_id=faq_id,
        details=f"question={question[:120]}",
    )

    flash("پاسخ پایگاه دانش با موفقیت ویرایش شد.", "success")
    return redirect(url_for("admin_faq"))


@app.route("/admin/faq/<int:faq_id>/toggle", methods=["POST"])
@support_manager_required_page
def toggle_faq(faq_id):
    row = db_fetchone(
        """
        SELECT TOP 1 is_active
        FROM dbo.knowledge_base
        WHERE id = :faq_id
        """,
        {"faq_id": faq_id},
    )

    if not row:
        flash("مورد موردنظر در پایگاه دانش پیدا نشد.", "error")
        return redirect(url_for("admin_faq"))

    new_status = 0 if int(row["is_active"] or 0) == 1 else 1

    db_execute(
        """
        UPDATE dbo.knowledge_base
        SET
            is_active = :is_active,
            updated_at = :updated_at
        WHERE id = :faq_id
        """,
        {
            "is_active": new_status,
            "updated_at": to_iso(utc_now()),
            "faq_id": faq_id,
        },
    )

    db_commit()

    record_activity(
        action="faq_toggled",
        entity_type="knowledge_base",
        entity_id=faq_id,
        details=f"is_active={new_status}",
    )

    flash("وضعیت پاسخ پایگاه دانش تغییر کرد.", "success")
    return redirect(url_for("admin_faq"))


@app.route("/admin/users", methods=["GET", "POST"])
@admin_required_page
def admin_users():
    if request.method == "POST":
        username = str(request.form.get("username", "")).strip()
        full_name = str(request.form.get("full_name", "")).strip()
        email = str(request.form.get("email", "")).strip()
        password = str(request.form.get("password", "")).strip()
        role = str(request.form.get("role", "support_agent")).strip()

        if role not in USER_ROLE_LABELS:
            role = "support_agent"

        if not username or not password:
            flash("نام کاربری و رمز عبور الزامی هستند.", "error")
            return redirect(url_for("admin_users"))

        if len(password) < 6:
            flash("رمز عبور باید حداقل ۶ کاراکتر باشد.", "error")
            return redirect(url_for("admin_users"))

        existing_username = db_fetchone(
            """
            SELECT TOP 1 id
            FROM dbo.users
            WHERE LOWER(username) = LOWER(:username)
            """,
            {"username": username},
        )

        if existing_username:
            flash("این نام کاربری قبلاً ثبت شده است.", "error")
            return redirect(url_for("admin_users"))

        email_value = email or None

        if email_value:
            existing_email = db_fetchone(
                """
                SELECT TOP 1 id
                FROM dbo.users
                WHERE LOWER(email) = LOWER(:email)
                """,
                {"email": email_value},
            )

            if existing_email:
                flash("این ایمیل قبلاً برای کاربر دیگری ثبت شده است.", "error")
                return redirect(url_for("admin_users"))

        result = db_execute(
            """
            INSERT INTO dbo.users (
                username,
                full_name,
                email,
                password_hash,
                role,
                is_active,
                failed_login_attempts,
                locked_until,
                must_change_password,
                last_login_at,
                created_at
            )
            OUTPUT INSERTED.id
            VALUES (
                :username,
                :full_name,
                :email,
                :password_hash,
                :role,
                :is_active,
                :failed_login_attempts,
                :locked_until,
                :must_change_password,
                :last_login_at,
                :created_at
            )
            """,
            {
                "username": username,
                "full_name": full_name or None,
                "email": email_value,
                "password_hash": generate_password_hash(password),
                "role": role,
                "is_active": 1,
                "failed_login_attempts": 0,
                "locked_until": None,
                "must_change_password": 0,
                "last_login_at": None,
                "created_at": to_iso(utc_now()),
            },
        )

        new_user_id = int(result.scalar() or 0)

        db_commit()

        record_activity(
            action="user_created",
            entity_type="user",
            entity_id=new_user_id,
            details=f"username={username}, role={role}",
        )

        flash("کاربر جدید با موفقیت ایجاد شد.", "success")
        return redirect(url_for("admin_users"))

    rows = db_fetchall(
        """
        SELECT
            id,
            username,
            full_name,
            email,
            role,
            is_active,
            failed_login_attempts,
            locked_until,
            last_login_at,
            created_at
        FROM dbo.users
        ORDER BY is_active DESC, id DESC
        """
    )

    users = []

    for row in rows:
        role = row["role"] or "support_agent"

        if role not in USER_ROLE_LABELS:
            role = "support_agent"

        users.append(
            {
                "id": row["id"],
                "username": row["username"] or "-",
                "full_name": row["full_name"] or "",
                "email": row["email"] or "",
                "role": role,
                "role_label": USER_ROLE_LABELS.get(role, "کارشناس پشتیبانی"),
                "is_active": int(row["is_active"] or 0),
                "failed_login_attempts": int(row["failed_login_attempts"] or 0),
                "locked_until": format_datetime(row["locked_until"]),
                "last_login_at": format_datetime(row["last_login_at"]),
                "created_at": format_datetime(row["created_at"]),
            }
        )

    return render_template(
        "admin_users.html",
        users=users,
        role_options=USER_ROLE_LABELS,
    )


@app.route("/admin/users/<int:user_id>/update", methods=["POST"])
@admin_required_page
def update_user(user_id):
    current_user_id = int(session.get("user_id") or 0)

    full_name = str(request.form.get("full_name", "")).strip()
    email = str(request.form.get("email", "")).strip()
    role = str(request.form.get("role", "support_agent")).strip()

    if role not in USER_ROLE_LABELS:
        role = "support_agent"

    if user_id == current_user_id and role != "admin":
        flash("نقش حساب مدیر فعلی را نمی‌توان از این بخش تغییر داد.", "error")
        return redirect(url_for("admin_users"))

    email_value = email or None

    if email_value:
        existing_email = db_fetchone(
            """
            SELECT TOP 1 id
            FROM dbo.users
            WHERE LOWER(email) = LOWER(:email)
              AND id != :user_id
            """,
            {
                "email": email_value,
                "user_id": user_id,
            },
        )

        if existing_email:
            flash("این ایمیل قبلاً برای کاربر دیگری ثبت شده است.", "error")
            return redirect(url_for("admin_users"))

    db_execute(
        """
        UPDATE dbo.users
        SET
            full_name = :full_name,
            email = :email,
            role = :role
        WHERE id = :user_id
        """,
        {
            "full_name": full_name or None,
            "email": email_value,
            "role": role,
            "user_id": user_id,
        },
    )

    db_commit()

    record_activity(
        action="user_updated",
        entity_type="user",
        entity_id=user_id,
        details=f"role={role}, email={email_value or '-'}",
    )

    flash("اطلاعات کاربر با موفقیت ویرایش شد.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
@admin_required_page
def toggle_user_status(user_id):
    current_user_id = int(session.get("user_id") or 0)

    if user_id == current_user_id:
        flash("نمی‌توانید حساب کاربری فعلی خودتان را غیرفعال کنید.", "error")
        return redirect(url_for("admin_users"))

    row = db_fetchone(
        """
        SELECT TOP 1 is_active
        FROM dbo.users
        WHERE id = :user_id
        """,
        {"user_id": user_id},
    )

    if not row:
        flash("کاربر موردنظر پیدا نشد.", "error")
        return redirect(url_for("admin_users"))

    new_status = 0 if int(row["is_active"] or 0) == 1 else 1

    db_execute(
        """
        UPDATE dbo.users
        SET
            is_active = :is_active,
            failed_login_attempts = 0,
            locked_until = NULL
        WHERE id = :user_id
        """,
        {
            "is_active": new_status,
            "user_id": user_id,
        },
    )

    db_commit()

    record_activity(
        action="user_toggled",
        entity_type="user",
        entity_id=user_id,
        details=f"is_active={new_status}",
    )

    flash("وضعیت کاربر تغییر کرد.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/reset-password", methods=["POST"])
@admin_required_page
def reset_user_password(user_id):
    new_password = str(request.form.get("new_password", "")).strip()
    confirm_password = str(request.form.get("confirm_password", "")).strip()

    if not new_password or not confirm_password:
        flash("رمز عبور جدید و تکرار آن الزامی است.", "error")
        return redirect(url_for("admin_users"))

    if new_password != confirm_password:
        flash("رمز عبور و تکرار آن یکسان نیستند.", "error")
        return redirect(url_for("admin_users"))

    if len(new_password) < 6:
        flash("رمز عبور باید حداقل ۶ کاراکتر باشد.", "error")
        return redirect(url_for("admin_users"))

    row = db_fetchone(
        """
        SELECT TOP 1 id
        FROM dbo.users
        WHERE id = :user_id
        """,
        {"user_id": user_id},
    )

    if not row:
        flash("کاربر موردنظر پیدا نشد.", "error")
        return redirect(url_for("admin_users"))

    db_execute(
        """
        UPDATE dbo.users
        SET
            password_hash = :password_hash,
            failed_login_attempts = 0,
            locked_until = NULL
        WHERE id = :user_id
        """,
        {
            "password_hash": generate_password_hash(new_password),
            "user_id": user_id,
        },
    )

    db_commit()

    record_activity(
        action="user_password_reset",
        entity_type="user",
        entity_id=user_id,
        details="password reset by admin",
    )

    flash("رمز عبور کاربر با موفقیت تغییر کرد.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/activity-log", methods=["GET"])
@admin_required_page
def admin_activity_log():
    rows = db_fetchall(
        """
        SELECT TOP 300
            id,
            actor_user_id,
            actor_username,
            actor_role,
            action,
            entity_type,
            entity_id,
            details,
            ip_address,
            created_at
        FROM dbo.activity_logs
        ORDER BY id DESC
        """
    )

    logs = []

    for row in rows:
        action = row["action"] or ""
        entity_type = row["entity_type"] or ""

        logs.append(
            {
                "id": row["id"],
                "actor_username": row["actor_username"] or "نامشخص",
                "actor_role": USER_ROLE_LABELS.get(row["actor_role"] or "", row["actor_role"] or "-"),
                "action": action,
                "action_label": ACTIVITY_ACTION_LABELS.get(action, action or "-"),
                "entity_type": entity_type,
                "entity_label": ACTIVITY_ENTITY_LABELS.get(entity_type, entity_type or "-"),
                "entity_id": row["entity_id"] or "-",
                "details": row["details"] or "-",
                "ip_address": row["ip_address"] or "-",
                "created_at": format_datetime(row["created_at"]),
            }
        )

    return render_template("admin_activity_log.html", logs=logs)


@app.route("/admin/feedback-report", methods=["GET"])
@support_manager_required_page
def feedback_report():
    total_feedback = db_fetchone(
        "SELECT COUNT(*) AS total FROM dbo.answer_feedback"
    )["total"] or 0

    useful_count = db_fetchone(
        """
        SELECT COUNT(*) AS total
        FROM dbo.answer_feedback
        WHERE rating = 'useful'
        """
    )["total"] or 0

    not_useful_count = db_fetchone(
        """
        SELECT COUNT(*) AS total
        FROM dbo.answer_feedback
        WHERE rating = 'not_useful'
        """
    )["total"] or 0

    if total_feedback > 0:
        useful_percent = round((useful_count / total_feedback) * 100, 1)
        not_useful_percent = round((not_useful_count / total_feedback) * 100, 1)
    else:
        useful_percent = 0
        not_useful_percent = 0

    stats = {
        "total_feedback": int(total_feedback),
        "useful_count": int(useful_count),
        "not_useful_count": int(not_useful_count),
        "useful_percent": useful_percent,
        "not_useful_percent": not_useful_percent,
    }

    raw_by_question = db_fetchall(
        """
        SELECT TOP 100
            question,
            category,
            COUNT(*) AS total_feedback,
            SUM(CASE WHEN rating = 'useful' THEN 1 ELSE 0 END) AS useful_count,
            SUM(CASE WHEN rating = 'not_useful' THEN 1 ELSE 0 END) AS not_useful_count
        FROM dbo.answer_feedback
        GROUP BY question, category
        ORDER BY not_useful_count DESC, total_feedback DESC
        """
    )

    by_question = []

    for row in raw_by_question:
        total = int(row["total_feedback"] or 0)
        useful = int(row["useful_count"] or 0)
        not_useful = int(row["not_useful_count"] or 0)

        if total > 0:
            row_useful_percent = round((useful / total) * 100, 1)
            row_not_useful_percent = round((not_useful / total) * 100, 1)
        else:
            row_useful_percent = 0
            row_not_useful_percent = 0

        by_question.append(
            {
                "question": row["question"] or "-",
                "category": row["category"] or "بدون دسته",
                "total_feedback": total,
                "useful_count": useful,
                "not_useful_count": not_useful,
                "useful_percent": row_useful_percent,
                "not_useful_percent": row_not_useful_percent,
            }
        )

    raw_negative_reason_summary = db_fetchall(
        """
        SELECT
            COALESCE(NULLIF(reason, ''), 'no_reason') AS reason_key,
            COUNT(*) AS total_count
        FROM dbo.answer_feedback
        WHERE rating = 'not_useful'
        GROUP BY COALESCE(NULLIF(reason, ''), 'no_reason')
        ORDER BY total_count DESC
        """
    )

    negative_reason_summary = []

    for row in raw_negative_reason_summary:
        reason_key = row["reason_key"] or "no_reason"

        negative_reason_summary.append(
            {
                "reason_key": reason_key,
                "reason_label": FEEDBACK_REASON_LABELS.get(reason_key, "نامشخص"),
                "total_count": int(row["total_count"] or 0),
            }
        )

    raw_recent_feedback = db_fetchall(
        """
        SELECT TOP 50
            af.id,
            af.question,
            af.answer,
            af.category,
            af.rating,
            af.reason,
            af.comment,
            af.created_at,
            u.username
        FROM dbo.answer_feedback af
        LEFT JOIN dbo.users u ON u.id = af.user_id
        ORDER BY af.id DESC
        """
    )

    recent_feedback = []

    for row in raw_recent_feedback:
        rating = row["rating"] or "-"
        reason_key = row["reason"] or ""

        if rating == "useful":
            rating_label = "مفید بود"
        elif rating == "not_useful":
            rating_label = "مفید نبود"
        else:
            rating_label = "نامشخص"

        recent_feedback.append(
            {
                "id": row["id"],
                "username": row["username"] or "نامشخص",
                "question": row["question"] or "-",
                "answer": row["answer"] or "-",
                "category": row["category"] or "بدون دسته",
                "rating": rating,
                "rating_label": rating_label,
                "reason": reason_key,
                "reason_label": FEEDBACK_REASON_LABELS.get(reason_key, "-"),
                "comment": row["comment"] or "-",
                "created_at": format_datetime(row["created_at"]),
            }
        )

    raw_unanswered_rows = db_fetchall(
        """
        SELECT TOP 1000
            id,
            question,
            normalized_question,
            suggestions_text,
            has_suggestions,
            status,
            created_at
        FROM dbo.unanswered_questions
        ORDER BY id DESC
        """
    )

    unanswered_summary = group_unanswered_questions(raw_unanswered_rows)

    raw_recent_unanswered = db_fetchall(
        """
        SELECT TOP 50
            uq.id,
            uq.question,
            uq.suggestions_text,
            uq.has_suggestions,
            uq.status,
            uq.created_at,
            u.username
        FROM dbo.unanswered_questions uq
        LEFT JOIN dbo.users u ON u.id = uq.user_id
        ORDER BY uq.id DESC
        """
    )

    recent_unanswered = []

    for row in raw_recent_unanswered:
        status = row["status"] or "new"

        recent_unanswered.append(
            {
                "id": row["id"],
                "username": row["username"] or "نامشخص",
                "question": row["question"] or "-",
                "suggestions_text": row["suggestions_text"] or "-",
                "has_suggestions": int(row["has_suggestions"] or 0),
                "status": status,
                "status_label": UNANSWERED_STATUS_LABELS.get(status, "جدید"),
                "created_at": format_datetime(row["created_at"]),
            }
        )

    return render_template(
        "admin_feedback_report.html",
        stats=stats,
        by_question=by_question,
        negative_reason_summary=negative_reason_summary,
        recent_feedback=recent_feedback,
        unanswered_summary=unanswered_summary,
        recent_unanswered=recent_unanswered,
    )

@app.route("/admin/keyword-groups", methods=["GET", "POST"])
@support_manager_required_page
def admin_keyword_groups():
    if request.method == "POST":
        title = str(request.form.get("title", "")).strip()
        category = str(request.form.get("category", "")).strip()
        keywords_text = str(request.form.get("keywords_text", "")).strip()

        if not title or not keywords_text:
            flash("عنوان و کلیدواژه‌ها الزامی هستند.", "error")
            return redirect(url_for("admin_keyword_groups"))

        now = to_iso(utc_now())

        result = db_execute(
            """
            INSERT INTO dbo.keyword_groups (
                title,
                category,
                keywords_text,
                is_active,
                created_at,
                updated_at
            )
            OUTPUT INSERTED.id
            VALUES (
                :title,
                :category,
                :keywords_text,
                :is_active,
                :created_at,
                :updated_at
            )
            """,
            {
                "title": title,
                "category": category or None,
                "keywords_text": keywords_text,
                "is_active": 1,
                "created_at": now,
                "updated_at": now,
            },
        )

        new_group_id = int(result.scalar() or 0)

        db_commit()

        record_activity(
            action="keyword_group_created",
            entity_type="keyword_group",
            entity_id=new_group_id,
            details=f"title={title[:120]}",
        )

        flash("گروه کلیدواژه با موفقیت ثبت شد.", "success")
        return redirect(url_for("admin_keyword_groups"))

    keyword_groups = db_fetchall(
        """
        SELECT TOP 500
            id,
            title,
            category,
            keywords_text,
            is_active,
            created_at,
            updated_at
        FROM dbo.keyword_groups
        ORDER BY is_active DESC, updated_at DESC, id DESC
        """
    )

    return render_template(
        "admin_keyword_groups.html",
        keyword_groups=keyword_groups,
    )


@app.route("/admin/keyword-groups/<int:group_id>/edit", methods=["POST"])
@support_manager_required_page
def edit_keyword_group(group_id):
    title = str(request.form.get("title", "")).strip()
    category = str(request.form.get("category", "")).strip()
    keywords_text = str(request.form.get("keywords_text", "")).strip()

    if not title or not keywords_text:
        flash("عنوان و کلیدواژه‌ها الزامی هستند.", "error")
        return redirect(url_for("admin_keyword_groups"))

    db_execute(
        """
        UPDATE dbo.keyword_groups
        SET
            title = :title,
            category = :category,
            keywords_text = :keywords_text,
            updated_at = :updated_at
        WHERE id = :group_id
        """,
        {
            "title": title,
            "category": category or None,
            "keywords_text": keywords_text,
            "updated_at": to_iso(utc_now()),
            "group_id": group_id,
        },
    )

    db_commit()

    record_activity(
        action="keyword_group_updated",
        entity_type="keyword_group",
        entity_id=group_id,
        details=f"title={title[:120]}",
    )

    flash("گروه کلیدواژه با موفقیت ویرایش شد.", "success")
    return redirect(url_for("admin_keyword_groups"))


@app.route("/admin/keyword-groups/<int:group_id>/toggle", methods=["POST"])
@support_manager_required_page
def toggle_keyword_group(group_id):
    row = db_fetchone(
        """
        SELECT TOP 1 is_active
        FROM dbo.keyword_groups
        WHERE id = :group_id
        """,
        {"group_id": group_id},
    )

    if not row:
        flash("گروه کلیدواژه موردنظر پیدا نشد.", "error")
        return redirect(url_for("admin_keyword_groups"))

    new_status = 0 if int(row["is_active"] or 0) == 1 else 1

    db_execute(
        """
        UPDATE dbo.keyword_groups
        SET
            is_active = :is_active,
            updated_at = :updated_at
        WHERE id = :group_id
        """,
        {
            "is_active": new_status,
            "updated_at": to_iso(utc_now()),
            "group_id": group_id,
        },
    )

    db_commit()

    record_activity(
        action="keyword_group_toggled",
        entity_type="keyword_group",
        entity_id=group_id,
        details=f"is_active={new_status}",
    )

    flash("وضعیت گروه کلیدواژه تغییر کرد.", "success")
    return redirect(url_for("admin_keyword_groups"))
init_db()


if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "true").lower() == "true"
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5000"))

    app.run(host=host, port=port, debug=debug_mode)
    