import os
import time
import json
import hmac
import hashlib
from urllib.parse import parse_qsl

import psycopg
from flask import Flask, request, jsonify
from flask_cors import CORS


# ==========================================
# APP
# ==========================================

app = Flask(__name__)
CORS(app)


# ==========================================
# ENVIRONMENT
# ==========================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")


if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is missing")


# ==========================================
# DATABASE
# ==========================================

def get_db():
    return psycopg.connect(DATABASE_URL)


def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id BIGINT PRIMARY KEY,
                    first_name TEXT DEFAULT '',
                    last_name TEXT DEFAULT '',
                    username TEXT DEFAULT '',
                    balance NUMERIC(18, 2) DEFAULT 0,
                    referral_count INTEGER DEFAULT 0,
                    tasks_completed INTEGER DEFAULT 0,
                    verified BOOLEAN DEFAULT FALSE,
                    invited_by BIGINT,
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
            """)

        conn.commit()


# ==========================================
# TELEGRAM MINI APP VALIDATION
# ==========================================

def validate_init_data(init_data):
    if not init_data:
        return None

    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))

        received_hash = parsed.pop("hash", None)

        if not received_hash:
            return None

        auth_date = parsed.get("auth_date")

        if not auth_date:
            return None

        # Reject data older than 24 hours
        if int(time.time()) - int(auth_date) > 86400:
            return None

        data_check_string = "\n".join(
            f"{key}={parsed[key]}"
            for key in sorted(parsed.keys())
        )

        secret_key = hmac.new(
            b"WebAppData",
            BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(
            calculated_hash,
            received_hash
        ):
            return None

        user_data = parsed.get("user")

        if not user_data:
            return None

        return json.loads(user_data)

    except Exception:
        return None


# ==========================================
# HOME
# ==========================================

@app.route("/")
def home():
    return jsonify({
        "success": True,
        "service": "ADEWA Mini Bot API",
        "status": "running"
    })


# ==========================================
# HEALTH
# ==========================================

@app.route("/api/health")
def health():
    try:
        init_db()

        return jsonify({
            "success": True,
            "status": "online",
            "database": "connected"
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "status": "offline",
            "error": str(e)
        }), 500


# ==========================================
# GET /api/me
# ==========================================

@app.route("/api/me", methods=["POST"])
def get_me():

    try:

        data = request.get_json(silent=True) or {}

        init_data = data.get("initData")

        if not init_data:
            return jsonify({
                "success": False,
                "error": "initData is required"
            }), 400


        # --------------------------------------
        # VALIDATE TELEGRAM USER
        # --------------------------------------

        telegram_user = validate_init_data(init_data)

        if not telegram_user:

            return jsonify({
                "success": False,
                "error": "Invalid or expired Telegram initData"
            }), 401


        telegram_id = int(telegram_user["id"])

        first_name = telegram_user.get(
            "first_name",
            ""
        )

        last_name = telegram_user.get(
            "last_name",
            ""
        )

        username = telegram_user.get(
            "username",
            ""
        )


        # --------------------------------------
        # DATABASE
        # --------------------------------------

        now = int(time.time())

        init_db()

        with get_db() as conn:

            with conn.cursor() as cur:

                cur.execute("""
                    SELECT
                        telegram_id,
                        first_name,
                        last_name,
                        username,
                        balance,
                        referral_count,
                        tasks_completed,
                        verified,
                        invited_by
                    FROM users
                    WHERE telegram_id = %s
                """, (telegram_id,))

                user = cur.fetchone()


                # ----------------------------------
                # CREATE USER
                # ----------------------------------

                if not user:

                    cur.execute("""
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
                        VALUES (
                            %s,
                            %s,
                            %s,
                            %s,
                            0,
                            0,
                            0,
                            FALSE,
                            NULL,
                            %s,
                            %s
                        )
                        RETURNING
                            telegram_id,
                            first_name,
                            last_name,
                            username,
                            balance,
                            referral_count,
                            tasks_completed,
                            verified,
                            invited_by
                    """, (
                        telegram_id,
                        first_name,
                        last_name,
                        username,
                        now,
                        now
                    ))

                    user = cur.fetchone()


                # ----------------------------------
                # UPDATE USER
                # ----------------------------------

                else:

                    cur.execute("""
                        UPDATE users
                        SET
                            first_name = %s,
                            last_name = %s,
                            username = %s,
                            updated_at = %s
                        WHERE telegram_id = %s
                        RETURNING
                            telegram_id,
                            first_name,
                            last_name,
                            username,
                            balance,
                            referral_count,
                            tasks_completed,
                            verified,
                            invited_by
                    """, (
                        first_name,
                        last_name,
                        username,
                        now,
                        telegram_id
                    ))

                    user = cur.fetchone()


            conn.commit()


        # --------------------------------------
        # RESPONSE
        # --------------------------------------

        return jsonify({

            "success": True,

            "user": {

                "telegram_id": user[0],

                "first_name": user[1],

                "last_name": user[2],

                "username": user[3],

                "balance": float(user[4]),

                "referral_count": user[5],

                "tasks_completed": user[6],

                "verified": bool(user[7]),

                "invited_by": user[8]
            }
        })


    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ==========================================
# VERCEL
# ==========================================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000))
                    )
