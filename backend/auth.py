
import datetime
from functools import wraps

import jwt
from flask import current_app, g, jsonify, request

from models import User, UserStatus


def generate_token(user: User) -> str:
    role = user.role.value if hasattr(user.role, "value") else user.role
    payload = {
        "user_id": user.id,
        "role": role,
        "iat": datetime.datetime.utcnow(),
        "exp": datetime.datetime.utcnow()
        + datetime.timedelta(hours=current_app.config["JWT_EXPIRY_HOURS"]),
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])


def token_required(f):


    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or malformed Authorization header"}), 401

        token = auth_header.split(" ", 1)[1].strip()
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Session expired, please log in again"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid authentication token"}), 401

        user = User.query.get(payload.get("user_id"))
        if not user:
            return jsonify({"error": "User account no longer exists"}), 401

        status = user.status.value if hasattr(user.status, "value") else user.status
        if status == UserStatus.BLACKLISTED.value:
            return jsonify({"error": "Your account has been blacklisted"}), 403

        g.current_user = user
        return f(*args, **kwargs)

    return decorated


def roles_required(*allowed_roles):
   

    def wrapper(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            role = (
                g.current_user.role.value
                if hasattr(g.current_user.role, "value")
                else g.current_user.role
            )
            if role not in allowed_roles:
                return jsonify({"error": "You do not have permission to perform this action"}), 403
            return f(*args, **kwargs)

        return decorated

    return wrapper