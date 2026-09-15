import os
import json
import hmac
import hashlib
import urllib.parse
import urllib.request
import uuid

from decimal import Decimal
from datetime import datetime, timezone

from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg


app = Flask(__name__)
CORS(app)


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
BOT_API_SECRET = os.environ.get("BOT_API_SECRET", "")

REFERRAL_REWARD = Decimal("1.00")

# AdsGram reward
AD_REWARD = Decimal("0.01")

# Maximum rewarded ads per user per day
MAX_AD_REWARDS_PER_DAY = 20

CHANNELS = [
    "@m_r_work1",
    "@ABDU_CRYPTO"
]


# =========================================================
# JSON ERROR HANDLERS
# =========================================================

@app.errorhandler(404)
def error_404(error):

    return jsonify({
        "success": False,
        "error": "Endpoint not found",
        "path": request.path
    }), 404


@app.errorhandler(405)
def error_405(error):

    return jsonify({
        "success": False,
        "error": "Method not allowed",
        "method": request.method,
        "path": request.path
    }), 405


@app.errorhandler(500)
def error_500(error):

    return jsonify({
        "success": False,
        "error": "Internal server error"
    }), 500


# =========================================================
# DATABASE
# =========================================================

def get_db():

    if not DATABASE_URL:
        raise Exception(
            "DATABASE_URL is missing"
        )

    return psycopg.connect(
        DATABASE_URL
    )


def init_db():

    with get_db() as conn:

        with conn.cursor() as cur:

            # =================================================
            # USERS
            # =================================================

            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (

                    telegram_id BIGINT PRIMARY KEY,

                    first_name TEXT,

                    last_name TEXT,

                    username TEXT,

                    balance NUMERIC(12,2)
                        DEFAULT 0,

                    referral_count INTEGER
                        DEFAULT 0,

                    tasks_completed INTEGER
                        DEFAULT 0,

                    verified BOOLEAN
                        DEFAULT FALSE,

                    invited_by BIGINT,

                    created_at TIMESTAMPTZ
                        DEFAULT NOW(),

                    updated_at TIMESTAMPTZ
                        DEFAULT NOW()
                )
            """)


            # =================================================
            # REFERRALS
            # =================================================

            cur.execute("""
                CREATE TABLE IF NOT EXISTS referrals (

                    id SERIAL PRIMARY KEY,

                    inviter_id BIGINT NOT NULL,

                    invited_user_id BIGINT
                        UNIQUE NOT NULL,

                    reward NUMERIC(12,2)
                        DEFAULT 1.00,

                    rewarded BOOLEAN
                        DEFAULT FALSE,

                    created_at TIMESTAMPTZ
                        DEFAULT NOW(),

                    rewarded_at TIMESTAMPTZ
                )
            """)


            # =================================================
            # TRANSACTIONS
            # =================================================

            cur.execute("""
                CREATE TABLE IF NOT EXISTS transactions (

                    id SERIAL PRIMARY KEY,

                    user_id BIGINT NOT NULL,

                    type TEXT NOT NULL,

                    amount NUMERIC(12,2)
                        NOT NULL,

                    description TEXT,

                    reference_id TEXT,

                    created_at TIMESTAMPTZ
                        DEFAULT NOW()
                )
            """)

        conn.commit()


# =========================================================
# TELEGRAM MINI APP INIT DATA
# =========================================================

def validate_init_data(init_data):

    if not BOT_TOKEN:
        raise Exception(
            "BOT_TOKEN is missing"
        )

    if not init_data:
        raise Exception(
            "Telegram initData is missing"
        )

    try:

        parsed = urllib.parse.parse_qs(
            init_data,
            strict_parsing=True
        )

        received_hash = parsed.get(
            "hash",
            [None]
        )[0]

        if not received_hash:
            raise Exception(
                "Missing Telegram hash"
            )

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
            raise Exception(
                "Invalid Telegram initData"
            )

        auth_date = int(
            parsed.get(
                "auth_date",
                [0]
            )[0]
        )

        now = int(
            datetime.now(
                timezone.utc
            ).timestamp()
        )

        if now - auth_date > 86400:

            raise Exception(
                "Telegram initData expired"
            )

        user_json = parsed.get(
            "user",
            [None]
        )[0]

        if not user_json:

            raise Exception(
                "Telegram user data missing"
            )

        user = json.loads(
            user_json
        )

        return user

    except Exception as e:

        raise Exception(
            "Telegram authentication failed: "
            + str(e)
        )


# =========================================================
# TELEGRAM API
# =========================================================

def telegram_api(method, data):

    if not BOT_TOKEN:

        raise Exception(
            "BOT_TOKEN is missing"
        )

    url = (
        "https://api.telegram.org/bot"
        + BOT_TOKEN
        + "/"
        + method
    )

    encoded = urllib.parse.urlencode(
        data
    ).encode()

    req = urllib.request.Request(
        url,
        data=encoded,
        method="POST"
    )

    with urllib.request.urlopen(
        req,
        timeout=15
    ) as response:

        raw = response.read().decode()

        return json.loads(raw)


# =========================================================
# CHANNEL MEMBERSHIP
# =========================================================

def check_channel_membership(user_id):

    for channel in CHANNELS:

        result = telegram_api(
            "getChatMember",
            {
                "chat_id": channel,
                "user_id": user_id
            }
        )

        if not result.get("ok"):

            raise Exception(
                "Could not check channel "
                + channel
            )

        member = result.get(
            "result",
            {}
        )

        status = member.get(
            "status"
        )

        if status not in [
            "member",
            "administrator",
            "creator"
        ]:

            return False, channel

    return True, None


# =========================================================
# CREATE / UPDATE USER
# =========================================================

def save_user(user_data):

    telegram_id = int(
        user_data["id"]
    )

    first_name = user_data.get(
        "first_name",
        "User"
    )

    last_name = user_data.get(
        "last_name"
    )

    username = user_data.get(
        "username"
    )

    with get_db() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                INSERT INTO users (
                    telegram_id,
                    first_name,
                    last_name,
                    username
                )

                VALUES (
                    %s,
                    %s,
                    %s,
                    %s
                )

                ON CONFLICT (telegram_id)

                DO UPDATE SET

                    first_name =
                        EXCLUDED.first_name,

                    last_name =
                        EXCLUDED.last_name,

                    username =
                        EXCLUDED.username,

                    updated_at =
                        NOW()
            """, (
                telegram_id,
                first_name,
                last_name,
                username
            ))

        conn.commit()


# =========================================================
# USER DATA
# =========================================================

def get_user(telegram_id):

    with get_db() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT

                    telegram_id,
                    first_name,
                    last_name,
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

    if not row:
        return None

    return {

        "telegram_id": row[0],

        "first_name": row[1],

        "last_name": row[2],

        "balance": float(
            row[3] or 0
        ),

        "referral_count":
            row[4] or 0,

        "tasks_completed":
            row[5] or 0,

        "verified":
            bool(row[6]),

        "invited_by":
            row[7]
    }


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    return jsonify({

        "success": True,

        "service":
            "ADEWA Mini Bot API",

        "status":
            "running"
    })


# =========================================================
# HEALTH
# =========================================================

@app.route("/api/health")
def health():

    try:

        with get_db() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    "SELECT 1"
                )

        return jsonify({

            "success": True,

            "status":
                "online",

            "database":
                "connected"
        })

    except Exception as e:

        return jsonify({

            "success": False,

            "status":
                "offline",

            "database":
                "error",

            "error":
                str(e)
        }), 500


# =========================================================
# MINI APP /api/me
# =========================================================

@app.route(
    "/api/me",
    methods=["POST"]
)
def api_me():

    try:

        body = request.get_json(
            silent=True
        ) or {}

        init_data = body.get(
            "initData"
        )

        telegram_user = validate_init_data(
            init_data
        )

        save_user(
            telegram_user
        )

        user = get_user(
            int(
                telegram_user["id"]
            )
        )

        return jsonify({

            "success": True,

            "user":
                user
        })

    except Exception as e:

        return jsonify({

            "success": False,

            "error":
                str(e)

        }), 401


# =========================================================
# VERIFY + QUALIFY
# =========================================================

@app.route(
    "/api/verify-and-qualify",
    methods=["POST"]
)
def verify_and_qualify():

    try:

        body = request.get_json(
            silent=True
        ) or {}

        init_data = body.get(
            "initData"
        )

        telegram_user = validate_init_data(
            init_data
        )

        user_id = int(
            telegram_user["id"]
        )

        save_user(
            telegram_user
        )

        joined, missing_channel = (
            check_channel_membership(
                user_id
            )
        )

        if not joined:

            return jsonify({

                "success": False,

                "verified": False,

                "error":
                    "Please join all required channels.",

                "missing_channel":
                    missing_channel

            }), 403

        referral_rewarded = False

        with get_db() as conn:

            with conn.cursor() as cur:

                # Lock invited user
                cur.execute("""
                    SELECT

                        telegram_id,
                        invited_by,
                        verified

                    FROM users

                    WHERE telegram_id = %s

                    FOR UPDATE
                """, (
                    user_id,
                ))

                user_row = cur.fetchone()

                if not user_row:

                    raise Exception(
                        "User not found"
                    )

                invited_by = user_row[1]

                # Mark verified
                cur.execute("""
                    UPDATE users

                    SET

                        verified = TRUE,

                        updated_at = NOW()

                    WHERE telegram_id = %s
                """, (
                    user_id,
                ))

                # =============================================
                # REFERRAL REWARD
                # =============================================

                if invited_by:

                    cur.execute("""
                        SELECT

                            id,
                            rewarded,
                            reward

                        FROM referrals

                        WHERE

                            inviter_id = %s

                            AND invited_user_id = %s

                        FOR UPDATE
                    """, (
                        invited_by,
                        user_id
                    ))

                    referral = cur.fetchone()

                    if referral and not referral[1]:

                        reward = Decimal(
                            str(referral[2])
                        )

                        # Lock inviter
                        cur.execute("""
                            SELECT telegram_id

                            FROM users

                            WHERE telegram_id = %s

                            FOR UPDATE
                        """, (
                            invited_by,
                        ))

                        inviter = cur.fetchone()

                        if inviter:

                            cur.execute("""
                                UPDATE users

                                SET

                                    balance =
                                        balance + %s,

                                    referral_count =
                                        referral_count + 1,

                                    updated_at =
                                        NOW()

                                WHERE telegram_id = %s
                            """, (
                                reward,
                                invited_by
                            ))

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
                                    'referral',
                                    %s,
                                    %s,
                                    %s

                                )
                            """, (
                                invited_by,
                                reward,
                                "Referral reward",
                                str(user_id)
                            ))

                            cur.execute("""
                                UPDATE referrals

                                SET

                                    rewarded = TRUE,

                                    rewarded_at = NOW()

                                WHERE id = %s
                            """, (
                                referral[0],
                            ))

                            referral_rewarded = True

            conn.commit()

        updated_user = get_user(
            user_id
        )

        return jsonify({

            "success": True,

            "verified": True,

            "referral_rewarded":
                referral_rewarded,

            "user":
                updated_user
        })

    except Exception as e:

        return jsonify({

            "success": False,

            "verified": False,

            "error":
                str(e)

        }), 400


# =========================================================
# REFERRAL REGISTER
# BOT ONLY
# =========================================================

@app.route(
    "/api/referral/register",
    methods=["GET"]
)
def register_referral():

    try:

        secret = request.args.get(
            "secret",
            ""
        )

        if not BOT_API_SECRET:

            return jsonify({

                "success": False,

                "error":
                    "BOT_API_SECRET is not configured"

            }), 500

        if not hmac.compare_digest(
            secret,
            BOT_API_SECRET
        ):

            return jsonify({

                "success": False,

                "error":
                    "Unauthorized"

            }), 401

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

        if inviter_id == invited_user_id:

            return jsonify({

                "success": False,

                "error":
                    "Self referral is not allowed"

            }), 400

        with get_db() as conn:

            with conn.cursor() as cur:

                # Make sure inviter exists
                cur.execute("""
                    INSERT INTO users (
                        telegram_id
                    )

                    VALUES (%s)

                    ON CONFLICT DO NOTHING
                """, (
                    inviter_id,
                ))

                # Make sure invited user exists
                cur.execute("""
                    INSERT INTO users (
                        telegram_id
                    )

                    VALUES (%s)

                    ON CONFLICT DO NOTHING
                """, (
                    invited_user_id,
                ))

                # Only first inviter counts
                cur.execute("""
                    SELECT invited_by

                    FROM users

                    WHERE telegram_id = %s

                    FOR UPDATE
                """, (
                    invited_user_id,
                ))

                existing = cur.fetchone()

                if existing and existing[0]:

                    return jsonify({

                        "success": True,

                        "registered": False,

                        "message":
                            "Referral already exists"
                    })

                cur.execute("""
                    UPDATE users

                    SET

                        invited_by = %s,

                        updated_at = NOW()

                    WHERE telegram_id = %s
                """, (
                    inviter_id,
                    invited_user_id
                ))

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

                    ON CONFLICT (
                        invited_user_id
                    )

                    DO NOTHING
                """, (
                    inviter_id,
                    invited_user_id,
                    REFERRAL_REWARD
                ))

            conn.commit()

        return jsonify({

            "success": True,

            "registered": True
        })

    except Exception as e:

        return jsonify({

            "success": False,

            "error":
                str(e)

        }), 400


# =========================================================
# ADSGRAM REWARD
# =========================================================

@app.route(
    "/api/reward/ad",
    methods=["POST"]
)
def reward_ad():

    try:

        body = request.get_json(
            silent=True
        ) or {}

        init_data = body.get(
            "initData"
        )

        # =============================================
        # VALIDATE TELEGRAM USER
        # =============================================

        telegram_user = validate_init_data(
            init_data
        )

        user_id = int(
            telegram_user["id"]
        )

        # Make sure account exists
        save_user(
            telegram_user
        )

        # =============================================
        # DATABASE TRANSACTION
        # =============================================

        with get_db() as conn:

            with conn.cursor() as cur:

                # Lock user
                cur.execute("""
                    SELECT

                        telegram_id,
                        first_name,
                        last_name,
                        balance,
                        referral_count,
                        tasks_completed,
                        verified

                    FROM users

                    WHERE telegram_id = %s

                    FOR UPDATE
                """, (
                    user_id,
                ))

                user_row = cur.fetchone()

                if not user_row:

                    raise Exception(
                        "User account not found"
                    )

                # =============================================
                # DAILY AD LIMIT
                # =============================================

                cur.execute("""
                    SELECT COUNT(*)

                    FROM transactions

                    WHERE

                        user_id = %s

                        AND type = 'ad_reward'

                        AND created_at >= CURRENT_DATE
                """, (
                    user_id,
                ))

                today_count = cur.fetchone()[0]

                if today_count >= MAX_AD_REWARDS_PER_DAY:

                    return jsonify({

                        "success": False,

                        "error":
                            "Daily advertisement reward limit reached."

                    }), 429

                # =============================================
                # UNIQUE REFERENCE
                # =============================================

                reference_id = (
                    "ad_"
                    + str(uuid.uuid4())
                )

                # =============================================
                # ADD REWARD
                # =============================================

                cur.execute("""
                    UPDATE users

                    SET

                        balance =
                            balance + %s,

                        updated_at =
                            NOW()

                    WHERE telegram_id = %s

                    RETURNING

                        telegram_id,
                        first_name,
                        last_name,
                        balance,
                        referral_count,
                        tasks_completed,
                        verified
                """, (
                    AD_REWARD,
                    user_id
                ))

                updated_user = cur.fetchone()

                if not updated_user:

                    raise Exception(
                        "Could not update user balance"
                    )

                # =============================================
                # SAVE TRANSACTION
                # =============================================

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
                        'ad_reward',
                        %s,
                        %s,
                        %s
                    )
                """, (
                    user_id,
                    AD_REWARD,
                    "AdsGram rewarded ad",
                    reference_id
                ))

            conn.commit()

        # =============================================
        # RESPONSE
        # =============================================

        return jsonify({

            "success": True,

            "reward":
                str(AD_REWARD),

            "user": {

                "telegram_id":
                    updated_user[0],

                "first_name":
                    updated_user[1],

                "last_name":
                    updated_user[2],

                "balance":
                    str(updated_user[3]),

                "referral_count":
                    updated_user[4],

                "tasks_completed":
                    updated_user[5],

                "verified":
                    updated_user[6]
            }
        })

    except Exception as e:

        return jsonify({

            "success": False,

            "error":
                str(e)

        }), 400


# =========================================================
# HISTORY
# =========================================================

@app.route(
    "/api/history",
    methods=["POST"]
)
def history():

    try:

        body = request.get_json(
            silent=True
        ) or {}

        init_data = body.get(
            "initData"
        )

        telegram_user = validate_init_data(
            init_data
        )

        user_id = int(
            telegram_user["id"]
        )

        save_user(
            telegram_user
        )

        with get_db() as conn:

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
                    user_id,
                ))

                rows = cur.fetchall()

        transactions = []

        for row in rows:

            transactions.append({

                "id":
                    row[0],

                "type":
                    row[1],

                "amount":
                    str(row[2]),

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

    except Exception as e:

        return jsonify({

            "success": False,

            "error":
                str(e)

        }), 400


# =========================================================
# START DATABASE
# =========================================================

try:

    init_db()

except Exception as e:

    print(
        "Database initialization error:",
        e
    )


# =========================================================
# LOCAL DEVELOPMENT
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
