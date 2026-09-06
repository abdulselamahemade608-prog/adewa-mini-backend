import os
import json
import time
import hmac
import hashlib
import sqlite3
from urllib.parse import parse_qsl

from flask import Flask, request, jsonify
from flask_cors import CORS


# =========================================================
# APP
# =========================================================

app = Flask(__name__)

CORS(
    app,
    resources={
        r"/api/*": {
            "origins": "*"
        }
    }
)


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Telegram recommends rejecting old initData.
# 86400 seconds = 24 hours.
INIT_DATA_MAX_AGE = 86400

DATABASE = "/tmp/adewa.db"


# =========================================================
# DATABASE
# =========================================================

def get_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def init_database():

    db = get_db()

    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            first_name TEXT DEFAULT '',
            last_name TEXT DEFAULT '',
            username TEXT DEFAULT '',
            balance REAL DEFAULT 0,
            referral_count INTEGER DEFAULT 0,
            tasks_completed INTEGER DEFAULT 0,
            verified INTEGER DEFAULT 0,
            invited_by INTEGER,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
    """)

    db.commit()
    db.close()


# Initialize when the function starts.
init_database()


# =========================================================
# TELEGRAM INIT DATA VALIDATION
# =========================================================

def validate_init_data(init_data):

    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable is missing")

    if not init_data:
        raise ValueError("Missing Telegram initData")

    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        raise ValueError("Invalid initData format")

    received_hash = parsed.pop("hash", None)

    if not received_hash:
        raise ValueError("Missing initData hash")

    # ---------------------------------------------
    # Check auth_date
    # ---------------------------------------------

    auth_date = parsed.get("auth_date")

    if not auth_date:
        raise ValueError("Missing auth_date")

    try:
        auth_timestamp = int(auth_date)
    except ValueError:
        raise ValueError("Invalid auth_date")

    current_time = int(time.time())

    if current_time - auth_timestamp > INIT_DATA_MAX_AGE:
        raise ValueError("Telegram initData has expired")

    if auth_timestamp > current_time + 60:
        raise ValueError("Invalid auth_date")

    # ---------------------------------------------
    # Build Telegram data-check-string
    # ---------------------------------------------

    data_check_string = "\n".join(
        f"{key}={value}"
        for key, value in sorted(parsed.items())
    )

    # ---------------------------------------------
    # Telegram secret key
    # ---------------------------------------------

    secret_key = hmac.new(
        b"WebAppData",
        BOT_TOKEN.encode(),
        hashlib.sha256
    ).digest()

    # ---------------------------------------------
    # Calculate expected hash
    # ---------------------------------------------

    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256
    ).hexdigest()

    # ---------------------------------------------
    # Constant-time comparison
    # ---------------------------------------------

    if not hmac.compare_digest(
        calculated_hash,
        received_hash
    ):
        raise ValueError("Invalid Telegram initData signature")

    # ---------------------------------------------
    # Parse Telegram user
    # ---------------------------------------------

    user_json = parsed.get("user")

    if not user_json:
        raise ValueError("Telegram user data missing")

    try:
        user = json.loads(user_json)
    except Exception:
        raise ValueError("Invalid Telegram user data")

    telegram_id = user.get("id")

    if not telegram_id:
        raise ValueError("Telegram user ID missing")

    return user


# =========================================================
# CREATE / UPDATE USER
# =========================================================

def get_or_create_user(user):

    telegram_id = int(user["id"])

    first_name = user.get("first_name", "")
    last_name = user.get("last_name", "")
    username = user.get("username", "")

    now = int(time.time())

    db = get_db()

    existing = db.execute(
        """
        SELECT *
        FROM users
        WHERE telegram_id = ?
        """,
        (telegram_id,)
    ).fetchone()

    if existing:

        db.execute(
            """
            UPDATE users
            SET
                first_name = ?,
                last_name = ?,
                username = ?,
                updated_at = ?
            WHERE telegram_id = ?
            """,
            (
                first_name,
                last_name,
                username,
                now,
                telegram_id
            )
        )

    else:

        db.execute(
            """
            INSERT INTO users (
                telegram_id,
                first_name,
                last_name,
                username,
                balance,
                referral_count,
                tasks_completed,
                verified,
                invited_by,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, 0, 0, 0, 0, NULL, ?, ?)
            """,
            (
                telegram_id,
                first_name,
                last_name,
                username,
                now,
                now
            )
        )

    db.commit()

    row = db.execute(
        """
        SELECT *
        FROM users
        WHERE telegram_id = ?
        """,
        (telegram_id,)
    ).fetchone()

    db.close()

    return row


# =========================================================
# SERIALIZE USER
# =========================================================

def user_to_json(user):

    return {
        "telegram_id": user["telegram_id"],
        "first_name": user["first_name"],
        "last_name": user["last_name"],
        "username": user["username"],
        "balance": round(float(user["balance"]), 2),
        "referral_count": int(user["referral_count"]),
        "tasks_completed": int(user["tasks_completed"]),
        "verified": bool(user["verified"])
    }


# =========================================================
# HEALTH CHECK
# =========================================================

@app.get("/")
def home():

    return jsonify({
        "success": True,
        "service": "ADEWA Mini Bot API",
        "status": "running"
    })


@app.get("/api/health")
def health():

    return jsonify({
        "success": True,
        "status": "online"
    })


# =========================================================
# CURRENT USER
# =========================================================

@app.post("/api/me")
def me():

    try:

        data = request.get_json(silent=True) or {}

        init_data = data.get("initData")

        if not init_data:
            return jsonify({
                "success": False,
                "error": "Missing initData"
            }), 400

        # ---------------------------------------------
        # Validate Telegram authentication
        # ---------------------------------------------

        telegram_user = validate_init_data(
            init_data
        )

        # ---------------------------------------------
        # Create/update database user
        # ---------------------------------------------

        user = get_or_create_user(
            telegram_user
        )

        return jsonify({
            "success": True,
            "user": user_to_json(user)
        })

    except ValueError as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 401

    except Exception as error:

        print("ME ERROR:", error)

        return jsonify({
            "success": False,
            "error": "Internal server error"
        }), 500


# =========================================================
# RUN LOCALLY
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
  )
