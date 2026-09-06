import os
import time
import hmac
import hashlib
import json
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
# ENVIRONMENT VARIABLES
# ==========================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
BOT_API_SECRET = os.environ.get("BOT_API_SECRET")


if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is missing")

if not BOT_API_SECRET:
    raise RuntimeError("BOT_API_SECRET environment variable is missing")


# ==========================================
# DATABASE
# ==========================================

def get_db():
    return psycopg.connect(DATABASE_URL)


# ==========================================
# CREATE DATABASE TABLES
# ==========================================

def init_db():

    with get_db() as conn:

        with conn.cursor() as cur:

            # ==================================
            # USERS
            # ==================================

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


            # ==================================
            # REFERRALS
            # ==================================

            cur.execute("""
                CREATE TABLE IF NOT EXISTS referrals (

                    id BIGSERIAL PRIMARY KEY,

                    inviter_id BIGINT NOT NULL,

                    invited_user_id BIGINT NOT NULL UNIQUE,

                    reward NUMERIC(18, 2) DEFAULT 1.00,

                    rewarded BOOLEAN DEFAULT FALSE,

                    created_at BIGINT NOT NULL,

                    rewarded_at BIGINT,

                    UNIQUE(inviter_id, invited_user_id)

                )
            """)


            # ==================================
            # TRANSACTIONS
            # ==================================

            cur.execute("""
                CREATE TABLE IF NOT EXISTS transactions (

                    id BIGSERIAL PRIMARY KEY,

                    user_id BIGINT NOT NULL,

                    type TEXT NOT NULL,

                    amount NUMERIC(18, 2) NOT NULL,

                    description TEXT DEFAULT '',

                    reference_id TEXT,

                    created_at BIGINT NOT NULL

                )
            """)

        conn.commit()


# ==========================================
# TELEGRAM INIT DATA VALIDATION
# ==========================================

def validate_init_data(init_data):

    if not init_data:
        return None

    try:

        parsed = dict(
            parse_qsl(
                init_data,
                keep_blank_values=True
            )
        )

        received_hash = parsed.pop("hash", None)

        if not received_hash:
            return None

        auth_date = parsed.get("auth_date")

        if not auth_date:
            return None

        # 24 hour validity
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
# HEALTH CHECK
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
# GET / CREATE USER
# ==========================================

@app.route("/api/me", methods=["POST"])
def get_me():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        init_data = data.get(
            "initData"
        )

        if not init_data:

            return jsonify({

                "success": False,

                "error": "initData is required"

            }), 400


        telegram_user = validate_init_data(
            init_data
        )

        if not telegram_user:

            return jsonify({

                "success": False,

                "error": "Invalid or expired Telegram initData"

            }), 401


        telegram_id = int(
            telegram_user["id"]
        )

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
                """, (
                    telegram_id,
                ))

                user = cur.fetchone()


                # ==================================
                # CREATE USER
                # ==================================

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


                # ==================================
                # UPDATE USER
                # ==================================

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
# REGISTER REFERRAL
# ==========================================

@app.route(
    "/api/referral/register",
    methods=["POST"]
)
def register_referral():

    try:

        data = request.get_json(
            silent=True
        ) or {}


        # ==================================
        # SECURITY CHECK
        # ==================================

        secret = data.get(
            "secret"
        )

        if not secret:

            return jsonify({

                "success": False,

                "error": "Secret is required"

            }), 401


        if not hmac.compare_digest(
            str(secret),
            str(BOT_API_SECRET)
        ):

            return jsonify({

                "success": False,

                "error": "Unauthorized"

            }), 403


        # ==================================
        # DATA
        # ==================================

        inviter_id = int(
            data.get("inviter_id")
        )

        invited_user_id = int(
            data.get("invited_user_id")
        )


        # ==================================
        # SELF REFERRAL BLOCK
        # ==================================

        if inviter_id == invited_user_id:

            return jsonify({

                "success": False,

                "error": "Self referral is not allowed"

            }), 400


        now = int(time.time())


        init_db()


        with get_db() as conn:

            with conn.cursor() as cur:

                # ==================================
                # CHECK INVITER
                # ==================================

                cur.execute("""
                    SELECT telegram_id
                    FROM users
                    WHERE telegram_id = %s
                """, (
                    inviter_id,
                ))

                inviter = cur.fetchone()


                if not inviter:

                    return jsonify({

                        "success": False,

                        "error": "Inviter does not exist"

                    }), 404


                # ==================================
                # CHECK INVITED USER
                # ==================================

                cur.execute("""
                    SELECT
                        telegram_id,
                        invited_by
                    FROM users
                    WHERE telegram_id = %s
                """, (
                    invited_user_id,
                ))

                invited = cur.fetchone()


                # ==================================
                # CREATE USER IF NEEDED
                # ==================================

                if not invited:

                    cur.execute("""
                        INSERT INTO users (

                            telegram_id,
                            invited_by,
                            created_at,
                            updated_at

                        )

                        VALUES (

                            %s,
                            %s,
                            %s,
                            %s

                        )

                    """, (

                        invited_user_id,
                        inviter_id,
                        now,
                        now

                    ))

                else:

                    # Already has inviter
                    if invited[1] is not None:

                        return jsonify({

                            "success": True,

                            "message": "Referral already registered",

                            "rewarded": False

                        })


                    cur.execute("""
                        UPDATE users

                        SET

                            invited_by = %s,

                            updated_at = %s

                        WHERE telegram_id = %s

                    """, (

                        inviter_id,
                        now,
                        invited_user_id

                    ))


                # ==================================
                # INSERT REFERRAL
                # ==================================

                cur.execute("""
                    INSERT INTO referrals (

                        inviter_id,

                        invited_user_id,

                        reward,

                        rewarded,

                        created_at

                    )

                    VALUES (

                        %s,
                        %s,
                        1.00,
                        FALSE,
                        %s

                    )

                    ON CONFLICT (invited_user_id)
                    DO NOTHING

                """, (

                    inviter_id,

                    invited_user_id,

                    now

                ))


            conn.commit()


        return jsonify({

            "success": True,

            "message": "Referral registered",

            "rewarded": False

        })


    except Exception as e:

        return jsonify({

            "success": False,

            "error": str(e)

        }), 500


# ==========================================
# RUN LOCAL
# ==========================================

if __name__ == "__main__":

    app.run(

        host="0.0.0.0",

        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        )

    )
