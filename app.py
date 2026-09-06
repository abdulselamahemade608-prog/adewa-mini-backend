import os
import json
import hmac
import hashlib
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg


# =========================================================
# ADEWA MINI BOT BACKEND
# =========================================================

app = Flask(__name__)
CORS(app)


# =========================================================
# ENVIRONMENT VARIABLES
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
BOT_API_SECRET = os.environ.get("BOT_API_SECRET", "").strip()


# =========================================================
# SETTINGS
# =========================================================

REFERRAL_REWARD = Decimal("1.00")

CHANNELS = [
    "@m_r_work1",
    "@ABDU_CRYPTO"
]


# =========================================================
# DATABASE
# =========================================================

def get_db():
    if not DATABASE_URL:
        raise Exception("DATABASE_URL is missing")

    return psycopg.connect(DATABASE_URL)


# =========================================================
# INIT DATABASE
# =========================================================

def init_db():

    conn = get_db()

    try:

        with conn.cursor() as cur:

            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id BIGINT PRIMARY KEY,
                    first_name TEXT,
                    last_name TEXT,
                    username TEXT,
                    balance NUMERIC(12,2) NOT NULL DEFAULT 0,
                    referral_count INTEGER NOT NULL DEFAULT 0,
                    tasks_completed INTEGER NOT NULL DEFAULT 0,
                    verified BOOLEAN NOT NULL DEFAULT FALSE,
                    invited_by BIGINT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS referrals (
                    id BIGSERIAL PRIMARY KEY,
                    inviter_id BIGINT NOT NULL,
                    invited_user_id BIGINT NOT NULL UNIQUE,
                    reward NUMERIC(12,2) NOT NULL DEFAULT 1.00,
                    rewarded BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    rewarded_at TIMESTAMPTZ,
                    UNIQUE(inviter_id, invited_user_id)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    type TEXT NOT NULL,
                    amount NUMERIC(12,2) NOT NULL,
                    description TEXT,
                    reference_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            conn.commit()

    finally:
        conn.close()


# =========================================================
# TELEGRAM INIT DATA VALIDATION
# =========================================================

def validate_init_data(init_data):

    if not BOT_TOKEN:
        return None, "BOT_TOKEN is missing"

    if not init_data:
        return None, "Telegram initData is missing"

    try:

        parsed = urllib.parse.parse_qs(
            init_data,
            strict_parsing=True
        )

        received_hash = parsed.get(
            "hash",
            [None]
        )[0]

        auth_date = parsed.get(
            "auth_date",
            [None]
        )[0]

        user_json = parsed.get(
            "user",
            [None]
        )[0]

        if not received_hash:
            return None, "Missing hash"

        if not auth_date:
            return None, "Missing auth_date"

        if not user_json:
            return None, "Missing user"


        # -------------------------------------------------
        # CHECK AUTH DATE
        # -------------------------------------------------

        try:

            auth_timestamp = int(
                auth_date
            )

        except:

            return None, "Invalid auth_date"


        now = int(
            datetime.now(
                timezone.utc
            ).timestamp()
        )


        # Telegram initData must not be older than 24 hours

        if now - auth_timestamp > 86400:

            return None, "Telegram initData expired"


        # -------------------------------------------------
        # DATA CHECK STRING
        # -------------------------------------------------

        data_pairs = []

        for key in sorted(parsed.keys()):

            if key == "hash":
                continue

            value = parsed[key][0]

            data_pairs.append(
                f"{key}={value}"
            )


        data_check_string = "\n".join(
            data_pairs
        )


        # -------------------------------------------------
        # SECRET KEY
        # -------------------------------------------------

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

            return None, "Invalid Telegram authentication"


        # -------------------------------------------------
        # USER
        # -------------------------------------------------

        user = json.loads(
            user_json
        )

        telegram_id = user.get(
            "id"
        )

        if not telegram_id:

            return None, "Telegram user ID missing"


        return user, None


    except Exception as e:

        return None, str(e)


# =========================================================
# GET AUTHENTICATED USER
# =========================================================

def get_authenticated_user():

    data = request.get_json(
        silent=True
    ) or {}

    init_data = data.get(
        "initData"
    )


    user, error = validate_init_data(
        init_data
    )


    if error:

        return None, error


    return user, None


# =========================================================
# TELEGRAM BOT API
# =========================================================

def telegram_api(
    method,
    params
):

    if not BOT_TOKEN:

        return None, "BOT_TOKEN is missing"


    url = (
        "https://api.telegram.org/bot"
        + BOT_TOKEN
        + "/"
        + method
    )


    try:

        encoded = urllib.parse.urlencode(
            params
        ).encode()


        req = urllib.request.Request(
            url,
            data=encoded,
            method="POST"
        )


        with urllib.request.urlopen(
            req,
            timeout=10
        ) as response:

            raw = response.read().decode()

            result = json.loads(
                raw
            )


        if not result.get(
            "ok",
            False
        ):

            return None, result.get(
                "description",
                "Telegram API error"
            )


        return result.get(
            "result"
        ), None


    except Exception as e:

        return None, str(e)


# =========================================================
# CHECK CHANNEL MEMBERSHIP
# =========================================================

def check_channel_membership(
    telegram_id
):

    for channel in CHANNELS:

        member, error = telegram_api(
            "getChatMember",
            {
                "chat_id": channel,
                "user_id": telegram_id
            }
        )


        if error:

            return False, (
                "Could not check "
                + channel
                + ": "
                + error
            )


        status = member.get(
            "status"
        )


        if status not in [
            "member",
            "administrator",
            "creator"
        ]:

            return False, (
                "User has not joined "
                + channel
            )


    return True, None


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    return jsonify({
        "success": True,
        "service": "ADEWA Mini Bot API",
        "status": "running"
    })


# =========================================================
# HEALTH
# =========================================================

@app.route(
    "/api/health",
    methods=["GET"]
)
def health():

    try:

        conn = get_db()

        conn.close()

        return jsonify({
            "success": True,
            "status": "online",
            "database": "connected"
        })


    except Exception as e:

        return jsonify({
            "success": False,
            "status": "offline",
            "database": "error",
            "error": str(e)
        }), 500


# =========================================================
# CREATE / UPDATE USER
# =========================================================

@app.route(
    "/api/me",
    methods=["POST"]
)
def me():

    user, error = get_authenticated_user()

    if error:

        return jsonify({
            "success": False,
            "error": error
        }), 401


    telegram_id = int(
        user["id"]
    )

    first_name = user.get(
        "first_name",
        ""
    )

    last_name = user.get(
        "last_name",
        ""
    )

    username = user.get(
        "username",
        ""
    )


    conn = get_db()

    try:

        with conn.cursor() as cur:

            cur.execute("""
                INSERT INTO users (
                    telegram_id,
                    first_name,
                    last_name,
                    username
                )
                VALUES (%s, %s, %s, %s)

                ON CONFLICT (telegram_id)
                DO UPDATE SET
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    username = EXCLUDED.username,
                    updated_at = NOW()
            """, (
                telegram_id,
                first_name,
                last_name,
                username
            ))


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


            row = cur.fetchone()

            conn.commit()


        user_data = {
            "telegram_id": row[0],
            "first_name": row[1],
            "last_name": row[2],
            "username": row[3],
            "balance": float(row[4]),
            "referral_count": row[5],
            "tasks_completed": row[6],
            "verified": row[7],
            "invited_by": row[8]
        }


        return jsonify({
            "success": True,
            "user": user_data
        })


    finally:

        conn.close()


# =========================================================
# SECURE VERIFY + QUALIFY
# =========================================================

@app.route(
    "/api/verify-and-qualify",
    methods=["POST"]
)
def verify_and_qualify():

    user, error = get_authenticated_user()

    if error:

        return jsonify({
            "success": False,
            "error": error
        }), 401


    telegram_id = int(
        user["id"]
    )


    # =====================================================
    # VERIFY TELEGRAM CHANNEL MEMBERSHIP
    # =====================================================

    joined, membership_error = (
        check_channel_membership(
            telegram_id
        )
    )


    if not joined:

        return jsonify({
            "success": False,
            "verified": False,
            "referral_rewarded": False,
            "error": membership_error
        }), 403


    conn = get_db()

    try:

        with conn.cursor() as cur:

            # =================================================
            # LOCK INVITED USER
            # =================================================

            cur.execute("""
                SELECT
                    telegram_id,
                    verified,
                    invited_by
                FROM users
                WHERE telegram_id = %s
                FOR UPDATE
            """, (
                telegram_id,
            ))


            invited_user = cur.fetchone()


            if not invited_user:

                return jsonify({
                    "success": False,
                    "error": "User account not found"
                }), 404


            invited_by = invited_user[2]


            # =================================================
            # MARK USER VERIFIED
            # =================================================

            cur.execute("""
                UPDATE users
                SET
                    verified = TRUE,
                    updated_at = NOW()
                WHERE telegram_id = %s
            """, (
                telegram_id,
            ))


            referral_rewarded = False
            reward_amount = Decimal("0.00")


            # =================================================
            # REFERRAL QUALIFICATION
            # =================================================

            if invited_by:

                # ---------------------------------------------
                # LOCK REFERRAL
                # ---------------------------------------------

                cur.execute("""
                    SELECT
                        id,
                        inviter_id,
                        invited_user_id,
                        reward,
                        rewarded
                    FROM referrals
                    WHERE invited_user_id = %s
                    FOR UPDATE
                """, (
                    telegram_id,
                ))


                referral = cur.fetchone()


                if referral:

                    referral_id = referral[0]
                    inviter_id = referral[1]
                    reward = Decimal(
                        str(referral[3])
                    )
                    rewarded = referral[4]


                    # -----------------------------------------
                    # NEVER REWARD TWICE
                    # -----------------------------------------

                    if not rewarded:

                        # =====================================
                        # MAKE SURE INVITER EXISTS
                        # =====================================

                        cur.execute("""
                            SELECT telegram_id
                            FROM users
                            WHERE telegram_id = %s
                            FOR UPDATE
                        """, (
                            inviter_id,
                        ))


                        inviter = cur.fetchone()


                        if inviter:

                            # =================================
                            # ADD +1 BIRR
                            # =================================

                            cur.execute("""
                                UPDATE users
                                SET
                                    balance = balance + %s,
                                    referral_count =
                                        referral_count + 1,
                                    updated_at = NOW()
                                WHERE telegram_id = %s
                            """, (
                                reward,
                                inviter_id
                            ))


                            # =================================
                            # TRANSACTION HISTORY
                            # =================================

                            cur.execute("""
                                INSERT INTO transactions (
                                    user_id,
                                    type,
                                    amount,
                                    description,
                                    reference_id
                                )
                                VALUES (
                                    %s,
                                    %s,
                                    %s,
                                    %s,
                                    %s
                                )
                            """, (
                                inviter_id,
                                "referral_reward",
                                reward,
                                "Referral reward",
                                str(
                                    referral_id
                                )
                            ))


                            # =================================
                            # MARK REWARDED
                            # =================================

                            cur.execute("""
                                UPDATE referrals
                                SET
                                    rewarded = TRUE,
                                    rewarded_at = NOW()
                                WHERE id = %s
                            """, (
                                referral_id,
                            ))


                            referral_rewarded = True
                            reward_amount = reward


            # =================================================
            # COMMIT EVERYTHING AT ONCE
            # =================================================

            conn.commit()


        # =====================================================
        # GET UPDATED USER
        # =====================================================

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

            row = cur.fetchone()


        user_data = {
            "telegram_id": row[0],
            "first_name": row[1],
            "last_name": row[2],
            "username": row[3],
            "balance": float(row[4]),
            "referral_count": row[5],
            "tasks_completed": row[6],
            "verified": row[7],
            "invited_by": row[8]
        }


        return jsonify({
            "success": True,
            "verified": True,
            "referral_rewarded":
                referral_rewarded,
            "reward":
                float(reward_amount),
            "user": user_data
        })


    except Exception as e:

        conn.rollback()

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


    finally:

        conn.close()


# =========================================================
# REFERRAL REGISTER
# =========================================================
#
# This endpoint is intended for server/bot use.
# The Mini App does NOT need BOT_API_SECRET.
#
# Example:
# /api/referral/register?inviter_id=123&invited_user_id=456&secret=...
# =========================================================

@app.route(
    "/api/referral/register",
    methods=["GET"]
)
def register_referral():

    secret = request.args.get(
        "secret",
        ""
    )


    if not BOT_API_SECRET:

        return jsonify({
            "success": False,
            "error": "BOT_API_SECRET is not configured"
        }), 500


    if not hmac.compare_digest(
        secret,
        BOT_API_SECRET
    ):

        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 401


    try:

        inviter_id = int(
            request.args.get(
                "inviter_id"
            )
        )

        invited_user_id = int(
            request.args.get(
                "invited_user_id"
            )
        )

    except:

        return jsonify({
            "success": False,
            "error": "Invalid user ID"
        }), 400


    if inviter_id == invited_user_id:

        return jsonify({
            "success": False,
            "error": "Self referral is not allowed"
        }), 400


    conn = get_db()

    try:

        with conn.cursor() as cur:

            # =============================================
            # MAKE SURE INVITER EXISTS
            # =============================================

            cur.execute("""
                SELECT telegram_id
                FROM users
                WHERE telegram_id = %s
            """, (
                inviter_id,
            ))

            if not cur.fetchone():

                return jsonify({
                    "success": False,
                    "error": "Inviter not found"
                }), 404


            # =============================================
            # MAKE SURE INVITED USER EXISTS
            # =============================================

            cur.execute("""
                INSERT INTO users (
                    telegram_id
                )
                VALUES (%s)
                ON CONFLICT (telegram_id)
                DO NOTHING
            """, (
                invited_user_id,
            ))


            # =============================================
            # SAVE INVITER
            # =============================================

            cur.execute("""
                UPDATE users
                SET
                    invited_by = %s,
                    updated_at = NOW()
                WHERE
                    telegram_id = %s
                    AND invited_by IS NULL
            """, (
                inviter_id,
                invited_user_id
            ))


            # =============================================
            # REGISTER REFERRAL
            # =============================================

            cur.execute("""
                INSERT INTO referrals (
                    inviter_id,
                    invited_user_id,
                    reward
                )
                VALUES (
                    %s,
                    %s,
                    %s
                )
                ON CONFLICT (invited_user_id)
                DO NOTHING
            """, (
                inviter_id,
                invited_user_id,
                REFERRAL_REWARD
            ))


            conn.commit()


        return jsonify({
            "success": True,
            "message": "Referral registered"
        })


    except Exception as e:

        conn.rollback()

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


    finally:

        conn.close()


# =========================================================
# HISTORY
# =========================================================

@app.route(
    "/api/history",
    methods=["POST"]
)
def history():

    user, error = get_authenticated_user()

    if error:

        return jsonify({
            "success": False,
            "error": error
        }), 401


    telegram_id = int(
        user["id"]
    )


    conn = get_db()

    try:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    id,
                    type,
                    amount,
                    description,
                    reference_id,
                    created_at
                FROM transactions
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 100
            """, (
                telegram_id,
            ))


            rows = cur.fetchall()


        transactions = []


        for row in rows:

            transactions.append({

                "id": row[0],

                "type": row[1],

                "amount": float(
                    row[2]
                ),

                "description":
                    row[3],

                "reference_id":
                    row[4],

                "created_at":
                    row[5].isoformat()
                    if row[5]
                    else None
            })


        return jsonify({
            "success": True,
            "transactions":
                transactions
        })


    finally:

        conn.close()


# =========================================================
# OLD SECRET VERIFY ENDPOINT
# =========================================================

@app.route(
    "/api/user/verify",
    methods=["GET"]
)
def verify_user_old():

    secret = request.args.get(
        "secret",
        ""
    )


    if not BOT_API_SECRET:

        return jsonify({
            "success": False,
            "error": "BOT_API_SECRET is not configured"
        }), 500


    if not hmac.compare_digest(
        secret,
        BOT_API_SECRET
    ):

        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 401


    try:

        telegram_id = int(
            request.args.get(
                "user_id"
            )
        )

    except:

        return jsonify({
            "success": False,
            "error": "Invalid user_id"
        }), 400


    conn = get_db()

    try:

        with conn.cursor() as cur:

            cur.execute("""
                UPDATE users
                SET
                    verified = TRUE,
                    updated_at = NOW()
                WHERE telegram_id = %s
            """, (
                telegram_id,
            ))

            conn.commit()


        return jsonify({
            "success": True,
            "verified": True
        })


    finally:

        conn.close()


# =========================================================
# STARTUP
# =========================================================

try:

    init_db()

except Exception as e:

    print(
        "Database initialization error:",
        e
    )


# =========================================================
# LOCAL RUN
# =========================================================

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
