import os
import time
import hmac
import hashlib
import json
from urllib.parse import parse_qsl

import psycopg
from flask import Flask, request, jsonify
from flask_cors import CORS


# =========================================================
# APP
# =========================================================

app = Flask(__name__)
CORS(app)


# =========================================================
# ENVIRONMENT VARIABLES
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
BOT_API_SECRET = os.environ.get("BOT_API_SECRET")


if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is missing")

if not BOT_API_SECRET:
    raise RuntimeError("BOT_API_SECRET environment variable is missing")


# =========================================================
# SETTINGS
# =========================================================

REFERRAL_REWARD = 1.00


# =========================================================
# DATABASE
# =========================================================

def get_db():
    return psycopg.connect(DATABASE_URL)


def init_db():

    with get_db() as conn:

        with conn.cursor() as cur:

            # -------------------------------------------------
            # USERS
            # -------------------------------------------------

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


            # -------------------------------------------------
            # REFERRALS
            # -------------------------------------------------

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


            # -------------------------------------------------
            # TRANSACTIONS
            # -------------------------------------------------

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


# =========================================================
# TELEGRAM MINI APP INIT DATA VALIDATION
# =========================================================

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


        received_hash = parsed.pop(
            "hash",
            None
        )


        if not received_hash:
            return None


        auth_date = parsed.get(
            "auth_date"
        )


        if not auth_date:
            return None


        # InitData valid for 24 hours
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


        user_data = parsed.get(
            "user"
        )


        if not user_data:
            return None


        return json.loads(user_data)


    except Exception:

        return None


# =========================================================
# GET TELEGRAM USER FROM REQUEST
# =========================================================

def get_authenticated_user():

    data = request.get_json(
        silent=True
    ) or {}

    init_data = data.get(
        "initData"
    )


    if not init_data:

        return None, jsonify({

            "success": False,

            "error": "initData is required"

        }), 400


    telegram_user = validate_init_data(
        init_data
    )


    if not telegram_user:

        return None, jsonify({

            "success": False,

            "error": "Invalid or expired Telegram initData"

        }), 401


    return telegram_user, None, None


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
# HEALTH CHECK
# =========================================================

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


# =========================================================
# CREATE / UPDATE USER
# POST /api/me
# =========================================================

@app.route(
    "/api/me",
    methods=["POST"]
)
def get_me():

    try:

        telegram_user, error_response, error_code = \
            get_authenticated_user()


        if error_response:

            return error_response, error_code


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


        now = int(
            time.time()
        )


        init_db()


        with get_db() as conn:

            with conn.cursor() as cur:

                # -------------------------------------------------
                # CHECK USER
                # -------------------------------------------------

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


                # -------------------------------------------------
                # CREATE USER
                # -------------------------------------------------

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


                # -------------------------------------------------
                # UPDATE USER
                # -------------------------------------------------

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


# =========================================================
# HISTORY
# POST /api/history
# =========================================================

@app.route(
    "/api/history",
    methods=["POST"]
)
def history():

    try:

        telegram_user, error_response, error_code = \
            get_authenticated_user()


        if error_response:

            return error_response, error_code


        telegram_id = int(
            telegram_user["id"]
        )


        init_db()


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

                """, (telegram_id,))


                rows = cur.fetchall()


        history_list = []


        for row in rows:

            history_list.append({

                "id": row[0],

                "type": row[1],

                "amount": float(row[2]),

                "description": row[3],

                "reference_id": row[4],

                "created_at": row[5]

            })


        return jsonify({

            "success": True,

            "history": history_list

        })


    except Exception as e:

        return jsonify({

            "success": False,

            "error": str(e)

        }), 500


# =========================================================
# REGISTER REFERRAL
# POST /api/referral/register
#
# This endpoint is protected by BOT_API_SECRET.
# =========================================================

@app.route(
    "/api/referral/register",
    methods=["POST"]
)
def register_referral():

    try:

        data = request.get_json(
            silent=True
        ) or {}


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


        inviter_id = int(
            data.get("inviter_id")
        )


        invited_user_id = int(
            data.get("invited_user_id")
        )


        # -------------------------------------------------
        # SELF REFERRAL
        # -------------------------------------------------

        if inviter_id == invited_user_id:

            return jsonify({

                "success": False,

                "error": "Self referral is not allowed"

            }), 400


        now = int(
            time.time()
        )


        init_db()


        with get_db() as conn:

            with conn.cursor() as cur:

                # -------------------------------------------------
                # CHECK INVITER
                # -------------------------------------------------

                cur.execute("""
                    SELECT telegram_id

                    FROM users

                    WHERE telegram_id = %s
                """, (inviter_id,))


                inviter = cur.fetchone()


                if not inviter:

                    return jsonify({

                        "success": False,

                        "error": "Inviter does not exist"

                    }), 404


                # -------------------------------------------------
                # CHECK INVITED USER
                # -------------------------------------------------

                cur.execute("""
                    SELECT

                        telegram_id,
                        invited_by

                    FROM users

                    WHERE telegram_id = %s

                    FOR UPDATE
                """, (invited_user_id,))


                invited = cur.fetchone()


                # -------------------------------------------------
                # CREATE INVITED USER IF NEEDED
                # -------------------------------------------------

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

                    # -------------------------------------------------
                    # ALREADY HAS INVITER
                    # -------------------------------------------------

                    if invited[1] is not None:

                        conn.commit()

                        return jsonify({

                            "success": True,

                            "message":
                                "Referral already registered",

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


                # -------------------------------------------------
                # INSERT REFERRAL
                # -------------------------------------------------

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
                        %s,
                        FALSE,
                        %s

                    )

                    ON CONFLICT (invited_user_id)

                    DO NOTHING

                    RETURNING id

                """, (

                    inviter_id,
                    invited_user_id,
                    REFERRAL_REWARD,
                    now

                ))


                referral = cur.fetchone()


            conn.commit()


        return jsonify({

            "success": True,

            "message": "Referral registered",

            "rewarded": False,

            "referral_created":
                referral is not None

        })


    except Exception as e:

        return jsonify({

            "success": False,

            "error": str(e)

        }), 500


# =========================================================
# QUALIFY REFERRAL
#
# POST /api/referral/qualify
#
# The invited user must be verified.
# Reward is given only once.
# =========================================================

@app.route(
    "/api/referral/qualify",
    methods=["POST"]
)
def qualify_referral():

    try:

        data = request.get_json(
            silent=True
        ) or {}


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


        invited_user_id = int(
            data.get("invited_user_id")
        )


        init_db()


        with get_db() as conn:

            with conn.cursor() as cur:

                # -------------------------------------------------
                # LOCK INVITED USER
                # -------------------------------------------------

                cur.execute("""
                    SELECT

                        telegram_id,
                        verified,
                        invited_by

                    FROM users

                    WHERE telegram_id = %s

                    FOR UPDATE

                """, (invited_user_id,))


                invited_user = cur.fetchone()


                if not invited_user:

                    return jsonify({

                        "success": False,

                        "error":
                            "Invited user does not exist"

                    }), 404


                # -------------------------------------------------
                # USER MUST BE VERIFIED
                # -------------------------------------------------

                if not invited_user[1]:

                    return jsonify({

                        "success": False,

                        "error":
                            "Referral is not qualified yet",

                        "qualified": False

                    })


                inviter_id = invited_user[2]


                if not inviter_id:

                    return jsonify({

                        "success": False,

                        "error":
                            "User has no inviter",

                        "qualified": False

                    })


                # -------------------------------------------------
                # LOCK REFERRAL
                # -------------------------------------------------

                cur.execute("""
                    SELECT

                        id,
                        reward,
                        rewarded

                    FROM referrals

                    WHERE invited_user_id = %s

                    FOR UPDATE

                """, (invited_user_id,))


                referral = cur.fetchone()


                if not referral:

                    return jsonify({

                        "success": False,

                        "error":
                            "Referral record not found"

                    }), 404


                referral_id = referral[0]

                reward = referral[1]

                rewarded = referral[2]


                # -------------------------------------------------
                # ALREADY REWARDED
                # -------------------------------------------------

                if rewarded:

                    conn.commit()

                    return jsonify({

                        "success": True,

                        "message":
                            "Referral reward already given",

                        "qualified": True,

                        "rewarded": True

                    })


                # -------------------------------------------------
                # LOCK INVITER
                # -------------------------------------------------

                cur.execute("""
                    SELECT

                        telegram_id,
                        balance,
                        referral_count

                    FROM users

                    WHERE telegram_id = %s

                    FOR UPDATE

                """, (inviter_id,))


                inviter = cur.fetchone()


                if not inviter:

                    return jsonify({

                        "success": False,

                        "error":
                            "Inviter does not exist"

                    }), 404


                old_balance = inviter[1]


                new_balance = (
                    old_balance + reward
                )


                new_referral_count = (
                    inviter[2] + 1
                )


                # -------------------------------------------------
                # UPDATE INVITER
                # -------------------------------------------------

                cur.execute("""
                    UPDATE users

                    SET

                        balance = %s,

                        referral_count = %s,

                        updated_at = %s

                    WHERE telegram_id = %s

                """, (

                    new_balance,

                    new_referral_count,

                    int(time.time()),

                    inviter_id

                ))


                # -------------------------------------------------
                # MARK REFERRAL REWARDED
                # -------------------------------------------------

                cur.execute("""
                    UPDATE referrals

                    SET

                        rewarded = TRUE,

                        rewarded_at = %s

                    WHERE id = %s

                """, (

                    int(time.time()),

                    referral_id

                ))


                # -------------------------------------------------
                # ADD TRANSACTION
                # -------------------------------------------------

                cur.execute("""
                    INSERT INTO transactions (

                        user_id,
                        type,
                        amount,
                        description,
                        reference_id,
                        created_at

                    )

                    VALUES (

                        %s,
                        'referral',
                        %s,
                        %s,
                        %s,
                        %s

                    )

                """, (

                    inviter_id,

                    reward,

                    "Referral reward",

                    str(referral_id),

                    int(time.time())

                ))


            conn.commit()


        return jsonify({

            "success": True,

            "message":
                "Referral qualified and rewarded",

            "qualified": True,

            "rewarded": True,

            "reward": float(reward),

            "inviter_id": inviter_id

        })


    except Exception as e:

        return jsonify({

            "success": False,

            "error": str(e)

        }), 500


# =========================================================
# ADMIN / INTERNAL VERIFY USER
#
# Protected with BOT_API_SECRET.
#
# This endpoint can be used by your trusted bot/backend
# after the membership verification process.
# =========================================================

@app.route(
    "/api/user/verify",
    methods=["POST"]
)
def verify_user():

    try:

        data = request.get_json(
            silent=True
        ) or {}


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


        telegram_id = int(
            data.get("telegram_id")
        )


        init_db()


        with get_db() as conn:

            with conn.cursor() as cur:

                # -------------------------------------------------
                # CHECK USER
                # -------------------------------------------------

                cur.execute("""
                    SELECT

                        telegram_id,
                        verified

                    FROM users

                    WHERE telegram_id = %s

                    FOR UPDATE

                """, (telegram_id,))


                user = cur.fetchone()


                if not user:

                    return jsonify({

                        "success": False,

                        "error":
                            "User does not exist"

                    }), 404


                # -------------------------------------------------
                # VERIFY
                # -------------------------------------------------

                cur.execute("""
                    UPDATE users

                    SET

                        verified = TRUE,

                        updated_at = %s

                    WHERE telegram_id = %s

                """, (

                    int(time.time()),

                    telegram_id

                ))


            conn.commit()


        return jsonify({

            "success": True,

            "verified": True,

            "telegram_id": telegram_id

        })


    except Exception as e:

        return jsonify({

            "success": False,

            "error": str(e)

        }), 500

# =========================================================
# REFERRAL REGISTER - GET
# TELEBOT CREATOR HTTP.get(url)
# =========================================================

@app.route(
    "/api/referral/register",
    methods=["GET"]
)
def register_referral_get():

    try:

        inviter_id = request.args.get(
            "inviter_id",
            type=int
        )

        invited_user_id = request.args.get(
            "invited_user_id",
            type=int
        )

        if not inviter_id or not invited_user_id:

            return jsonify({
                "success": False,
                "error": "inviter_id and invited_user_id are required"
            }), 400

        if inviter_id == invited_user_id:

            return jsonify({
                "success": False,
                "error": "Self referral is not allowed"
            }), 400

        now = int(time.time())

        init_db()

        with get_db() as conn:

            with conn.cursor() as cur:

                # Check inviter
                cur.execute("""
                    SELECT telegram_id
                    FROM users
                    WHERE telegram_id = %s
                """, (inviter_id,))

                inviter = cur.fetchone()

                if not inviter:

                    return jsonify({
                        "success": False,
                        "error": "Inviter does not exist"
                    }), 404

                # Check invited user
                cur.execute("""
                    SELECT telegram_id, invited_by
                    FROM users
                    WHERE telegram_id = %s
                    FOR UPDATE
                """, (invited_user_id,))

                invited = cur.fetchone()

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

                    if invited[1] is not None:

                        conn.commit()

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

                # Create referral
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
                        %s,
                        FALSE,
                        %s
                    )
                    ON CONFLICT (invited_user_id)
                    DO NOTHING
                    RETURNING id
                """, (
                    inviter_id,
                    invited_user_id,
                    REFERRAL_REWARD,
                    now
                ))

                referral = cur.fetchone()

            conn.commit()

        return jsonify({
            "success": True,
            "message": "Referral registered",
            "rewarded": False,
            "referral_created": referral is not None
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
# =========================================================
# VERCEL / LOCAL
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
