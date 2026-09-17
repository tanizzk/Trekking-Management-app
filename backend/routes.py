
import json
from datetime import date, datetime

import redis as redis_lib
from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import func

from auth import generate_token, roles_required, token_required
from celery_app import celery_app
from extensions import db, redis_client
from models import (
    Booking,
    BookingStatus,
    StaffProfile,
    Trek,
    TrekStatus,
    User,
    UserRole,
    UserStatus,
)
from tasks import export_user_bookings_csv, generate_monthly_report, send_daily_reminders

api_bp = Blueprint("api", __name__)

TREKS_CACHE_KEY = "cache:treks:open"


def invalidate_treks_cache():
    
    try:
        redis_client.delete(TREKS_CACHE_KEY)
    except redis_lib.exceptions.RedisError:
        current_app.logger.warning("Redis unavailable - could not invalidate treks cache")


def _role_value(role_field):
    return role_field.value if hasattr(role_field, "value") else role_field


# ===========================================================================
# AUTH
# ===========================================================================
@api_bp.route("/auth/register", methods=["POST"])
def register():

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    phone = (data.get("phone") or "").strip()

    if not name or not email or not password:
        return jsonify({"error": "Name, email and password are required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters long"}), 400
    if "@" not in email or "." not in email:
        return jsonify({"error": "Please provide a valid email address"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "An account with this email already exists"}), 409

    user = User(name=name, email=email, phone=phone, role=UserRole.TREKKER.value,
                status=UserStatus.ACTIVE.value)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    token = generate_token(user)
    return jsonify({"message": "Registration successful", "token": token, "user": user.to_dict()}), 201


@api_bp.route("/auth/login", methods=["POST"])
def login():
    """Shared login for all roles (Admin / Staff / Trekker)."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({"error": "Invalid email or password"}), 401

    if _role_value(user.status) == UserStatus.BLACKLISTED.value:
        return jsonify({"error": "Your account has been blacklisted. Contact an administrator."}), 403

    token = generate_token(user)
    return jsonify({"message": "Login successful", "token": token, "user": user.to_dict()})


@api_bp.route("/auth/me", methods=["GET"])
@token_required
def me():
    return jsonify({"user": g.current_user.to_dict()})


# ===========================================================================
# PUBLIC / SHARED TREK BROWSING  (cached in Redis)
# ===========================================================================
@api_bp.route("/treks", methods=["GET"])
def list_treks():

    search = (request.args.get("search") or "").strip().lower()
    location = (request.args.get("location") or "").strip().lower()
    difficulty = (request.args.get("difficulty") or "").strip().lower()

    use_cache = not (search or location or difficulty)

    if use_cache:
        try:
            cached = redis_client.get(TREKS_CACHE_KEY)
            if cached:
                return jsonify({"treks": json.loads(cached), "cached": True})
        except redis_lib.exceptions.RedisError:
            current_app.logger.warning("Redis unavailable - falling back to DB for /treks")

    query = Trek.query.filter_by(status=TrekStatus.OPEN.value)
    if search:
        query = query.filter(Trek.title.ilike(f"%{search}%"))
    if location:
        query = query.filter(Trek.location.ilike(f"%{location}%"))
    if difficulty:
        query = query.filter(Trek.difficulty == difficulty)

    treks = query.order_by(Trek.start_date.asc()).all()
    data = [t.to_dict() for t in treks]

    if use_cache:
        try:
            redis_client.setex(
                TREKS_CACHE_KEY, current_app.config["TREKS_CACHE_TTL_SECONDS"], json.dumps(data)
            )
        except redis_lib.exceptions.RedisError:
            current_app.logger.warning("Redis unavailable - could not populate treks cache")

    return jsonify({"treks": data, "cached": False})


@api_bp.route("/treks/<int:trek_id>", methods=["GET"])
def get_trek(trek_id):
    trek = Trek.query.get(trek_id)
    if not trek:
        return jsonify({"error": "Trek not found"}), 404
    return jsonify({"trek": trek.to_dict()})


# ===========================================================================
# TREKKER: BOOKINGS
# ===========================================================================
@api_bp.route("/treks/<int:trek_id>/book", methods=["POST"])
@token_required
@roles_required(UserRole.TREKKER.value)
def book_trek(trek_id):
    user = g.current_user
    data = request.get_json(silent=True) or {}
    num_slots = data.get("num_slots", 1)

    if not isinstance(num_slots, int) or num_slots < 1:
        return jsonify({"error": "num_slots must be a positive integer"}), 400

    trek = Trek.query.get(trek_id)
    if not trek:
        return jsonify({"error": "Trek not found"}), 404

    if _role_value(trek.status) != TrekStatus.OPEN.value:
        return jsonify({"error": "This trek is not currently open for booking"}), 400

    # --- Overbooking prevention: re-check available slots right before insert ---
    if trek.available_slots < num_slots:
        return jsonify(
            {"error": f"Only {trek.available_slots} slot(s) remaining for this trek"}
        ), 409

    existing = Booking.query.filter_by(
        user_id=user.id, trek_id=trek_id, status=BookingStatus.CONFIRMED.value
    ).first()
    if existing:
        return jsonify({"error": "You already have an active booking for this trek"}), 409

    booking = Booking(
        user_id=user.id, trek_id=trek_id, num_slots=num_slots, status=BookingStatus.CONFIRMED.value
    )
    db.session.add(booking)
    db.session.commit()

    # Auto-close the trek if this booking filled the last slot(s).
    if trek.available_slots == 0:
        trek.status = TrekStatus.CLOSED.value
        db.session.commit()

    invalidate_treks_cache()
    return jsonify({"message": "Booking confirmed", "booking": booking.to_dict()}), 201


@api_bp.route("/bookings/my", methods=["GET"])
@token_required
@roles_required(UserRole.TREKKER.value)
def my_bookings():
    bookings = (
        Booking.query.filter_by(user_id=g.current_user.id)
        .order_by(Booking.booking_date.desc())
        .all()
    )
    return jsonify({"bookings": [b.to_dict() for b in bookings]})


@api_bp.route("/bookings/<int:booking_id>/cancel", methods=["PUT"])
@token_required
@roles_required(UserRole.TREKKER.value)
def cancel_booking(booking_id):
    user = g.current_user
    booking = Booking.query.get(booking_id)
    if not booking or booking.user_id != user.id:
        return jsonify({"error": "Booking not found"}), 404
    if _role_value(booking.status) != BookingStatus.CONFIRMED.value:
        return jsonify({"error": "Only confirmed bookings can be cancelled"}), 400

    trek = booking.trek
    booking.status = BookingStatus.CANCELLED.value
    booking.cancelled_at = datetime.utcnow()
    db.session.commit()

    # Re-open a previously auto-closed trek now that a slot freed up.
    if trek and _role_value(trek.status) == TrekStatus.CLOSED.value and trek.available_slots > 0:
        trek.status = TrekStatus.OPEN.value
        db.session.commit()

    invalidate_treks_cache()
    return jsonify({"message": "Booking cancelled", "booking": booking.to_dict()})


@api_bp.route("/bookings/export", methods=["POST"])
@token_required
@roles_required(UserRole.TREKKER.value)
def export_bookings():
    """User-triggered ASYNC job: kicks off a Celery task and returns immediately
    with a task_id the frontend polls via GET /api/tasks/<task_id>."""
    task = export_user_bookings_csv.delay(g.current_user.id)
    return jsonify({"message": "Export started", "task_id": task.id}), 202


# ===========================================================================
# GENERIC ASYNC TASK STATUS POLLING
# ===========================================================================
@api_bp.route("/tasks/<task_id>", methods=["GET"])
@token_required
def get_task_status(task_id):
    result = celery_app.AsyncResult(task_id)
    response = {"task_id": task_id, "state": result.state}
    if result.state == "SUCCESS":
        response["result"] = result.result
    elif result.state == "FAILURE":
        response["error"] = str(result.result)
    return jsonify(response)


# ===========================================================================
# STAFF: TREK MANAGEMENT
# ===========================================================================
@api_bp.route("/staff/treks", methods=["POST"])
@token_required
@roles_required(UserRole.STAFF.value, UserRole.ADMIN.value)
def create_trek():
    data = request.get_json(silent=True) or {}
    required_fields = ["title", "location", "start_date", "end_date", "total_slots", "price"]
    missing = [f for f in required_fields if data.get(f) in (None, "")]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    try:
        start_dt = datetime.strptime(data["start_date"], "%Y-%m-%d").date()
        end_dt = datetime.strptime(data["end_date"], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return jsonify({"error": "Dates must be in YYYY-MM-DD format"}), 400

    if end_dt < start_dt:
        return jsonify({"error": "End date cannot be earlier than start date"}), 400
    if start_dt < date.today():
        return jsonify({"error": "Start date cannot be in the past"}), 400

    try:
        total_slots = int(data["total_slots"])
        price = float(data["price"])
    except (ValueError, TypeError):
        return jsonify({"error": "total_slots must be an integer and price must be numeric"}), 400

    if total_slots < 1:
        return jsonify({"error": "total_slots must be at least 1"}), 400
    if price < 0:
        return jsonify({"error": "price cannot be negative"}), 400

    difficulty = (data.get("difficulty") or "moderate").lower()
    if difficulty not in ("easy", "moderate", "hard"):
        difficulty = "moderate"

    trek = Trek(
        title=data["title"].strip(),
        description=(data.get("description") or "").strip(),
        location=data["location"].strip(),
        difficulty=difficulty,
        start_date=start_dt,
        end_date=end_dt,
        price=price,
        total_slots=total_slots,
        status=TrekStatus.PENDING.value,
        created_by=g.current_user.id,
    )
    db.session.add(trek)
    db.session.commit()
    return jsonify({"message": "Trek submitted and awaiting admin approval", "trek": trek.to_dict()}), 201


@api_bp.route("/staff/treks", methods=["GET"])
@token_required
@roles_required(UserRole.STAFF.value, UserRole.ADMIN.value)
def my_treks():
    if _role_value(g.current_user.role) == UserRole.ADMIN.value:
        treks = Trek.query.order_by(Trek.created_at.desc()).all()
    else:
        treks = (
            Trek.query.filter_by(created_by=g.current_user.id)
            .order_by(Trek.created_at.desc())
            .all()
        )
    return jsonify({"treks": [t.to_dict() for t in treks]})


def _authorize_trek_management(trek):
    """Staff may only manage their own treks; Admin may manage any."""
    if _role_value(g.current_user.role) == UserRole.STAFF.value and trek.created_by != g.current_user.id:
        return False
    return True


@api_bp.route("/staff/treks/<int:trek_id>", methods=["PUT"])
@token_required
@roles_required(UserRole.STAFF.value, UserRole.ADMIN.value)
def update_trek(trek_id):
    trek = Trek.query.get(trek_id)
    if not trek:
        return jsonify({"error": "Trek not found"}), 404
    if not _authorize_trek_management(trek):
        return jsonify({"error": "You can only edit your own treks"}), 403
    if _role_value(trek.status) not in (TrekStatus.PENDING.value, TrekStatus.APPROVED.value):
        return jsonify({"error": "Only pending or approved treks can be edited"}), 400

    data = request.get_json(silent=True) or {}
    for field in ("title", "description", "location"):
        if field in data and data[field] is not None:
            setattr(trek, field, str(data[field]).strip())

    if "difficulty" in data and data["difficulty"] in ("easy", "moderate", "hard"):
        trek.difficulty = data["difficulty"]

    if "total_slots" in data:
        try:
            new_slots = int(data["total_slots"])
            if new_slots < trek.booked_slots:
                return jsonify({"error": "total_slots cannot be less than already booked slots"}), 400
            trek.total_slots = new_slots
        except (ValueError, TypeError):
            return jsonify({"error": "total_slots must be an integer"}), 400

    if "price" in data:
        try:
            new_price = float(data["price"])
            if new_price < 0:
                return jsonify({"error": "price cannot be negative"}), 400
            trek.price = new_price
        except (ValueError, TypeError):
            return jsonify({"error": "price must be numeric"}), 400

    db.session.commit()
    invalidate_treks_cache()
    return jsonify({"message": "Trek updated", "trek": trek.to_dict()})


@api_bp.route("/staff/treks/<int:trek_id>/open", methods=["PUT"])
@token_required
@roles_required(UserRole.STAFF.value, UserRole.ADMIN.value)
def open_trek(trek_id):
    trek = Trek.query.get(trek_id)
    if not trek:
        return jsonify({"error": "Trek not found"}), 404
    if not _authorize_trek_management(trek):
        return jsonify({"error": "You can only manage your own treks"}), 403
    if _role_value(trek.status) != TrekStatus.APPROVED.value:
        return jsonify({"error": "Only admin-approved treks can be opened for booking"}), 400

    trek.status = TrekStatus.OPEN.value
    db.session.commit()
    invalidate_treks_cache()
    return jsonify({"message": "Trek is now open for booking", "trek": trek.to_dict()})


@api_bp.route("/staff/treks/<int:trek_id>/close", methods=["PUT"])
@token_required
@roles_required(UserRole.STAFF.value, UserRole.ADMIN.value)
def close_trek(trek_id):
    trek = Trek.query.get(trek_id)
    if not trek:
        return jsonify({"error": "Trek not found"}), 404
    if not _authorize_trek_management(trek):
        return jsonify({"error": "You can only manage your own treks"}), 403
    if _role_value(trek.status) != TrekStatus.OPEN.value:
        return jsonify({"error": "Only open treks can be closed"}), 400

    trek.status = TrekStatus.CLOSED.value
    db.session.commit()
    invalidate_treks_cache()
    return jsonify({"message": "Trek closed for booking", "trek": trek.to_dict()})


@api_bp.route("/staff/treks/<int:trek_id>/complete", methods=["PUT"])
@token_required
@roles_required(UserRole.STAFF.value, UserRole.ADMIN.value)
def complete_trek(trek_id):
    trek = Trek.query.get(trek_id)
    if not trek:
        return jsonify({"error": "Trek not found"}), 404
    if not _authorize_trek_management(trek):
        return jsonify({"error": "You can only manage your own treks"}), 403
    if _role_value(trek.status) not in (TrekStatus.OPEN.value, TrekStatus.CLOSED.value):
        return jsonify({"error": "Trek cannot be marked completed from its current state"}), 400

    trek.status = TrekStatus.COMPLETED.value
    db.session.commit()
    invalidate_treks_cache()
    return jsonify({"message": "Trek marked as completed", "trek": trek.to_dict()})


@api_bp.route("/staff/treks/<int:trek_id>/bookings", methods=["GET"])
@token_required
@roles_required(UserRole.STAFF.value, UserRole.ADMIN.value)
def trek_bookings(trek_id):
    trek = Trek.query.get(trek_id)
    if not trek:
        return jsonify({"error": "Trek not found"}), 404
    if not _authorize_trek_management(trek):
        return jsonify({"error": "You can only view bookings for your own treks"}), 403

    bookings = Booking.query.filter_by(trek_id=trek_id).order_by(Booking.booking_date.desc()).all()
    return jsonify({"trek": trek.to_dict(), "bookings": [b.to_dict() for b in bookings]})


# ===========================================================================
# ADMIN: USER MANAGEMENT
# ===========================================================================
@api_bp.route("/admin/staff", methods=["POST"])
@token_required
@roles_required(UserRole.ADMIN.value)
def create_staff():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    phone = (data.get("phone") or "").strip()
    designation = (data.get("designation") or "Trek Coordinator").strip()
    assigned_region = (data.get("assigned_region") or "").strip()

    if not name or not email or not password:
        return jsonify({"error": "Name, email and password are required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters long"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "An account with this email already exists"}), 409

    staff_user = User(
        name=name, email=email, phone=phone, role=UserRole.STAFF.value, status=UserStatus.ACTIVE.value
    )
    staff_user.set_password(password)
    db.session.add(staff_user)
    db.session.flush()  # assign staff_user.id before creating the profile

    profile = StaffProfile(
        user_id=staff_user.id, designation=designation, assigned_region=assigned_region
    )
    db.session.add(profile)
    db.session.commit()

    return jsonify({"message": "Staff account created", "user": staff_user.to_dict()}), 201


@api_bp.route("/admin/users", methods=["GET"])
@token_required
@roles_required(UserRole.ADMIN.value)
def list_users():
    role_filter = request.args.get("role")
    query = User.query
    if role_filter:
        query = query.filter_by(role=role_filter)
    users = query.order_by(User.created_at.desc()).all()
    return jsonify({"users": [u.to_dict() for u in users]})


@api_bp.route("/admin/users/<int:user_id>/blacklist", methods=["PUT"])
@token_required
@roles_required(UserRole.ADMIN.value)
def blacklist_user(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    if _role_value(user.role) == UserRole.ADMIN.value:
        return jsonify({"error": "The admin account cannot be blacklisted"}), 400

    user.status = UserStatus.BLACKLISTED.value
    db.session.commit()
    return jsonify({"message": f"{user.name} has been blacklisted", "user": user.to_dict()})


@api_bp.route("/admin/users/<int:user_id>/activate", methods=["PUT"])
@token_required
@roles_required(UserRole.ADMIN.value)
def activate_user(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    user.status = UserStatus.ACTIVE.value
    db.session.commit()
    return jsonify({"message": f"{user.name} has been reactivated", "user": user.to_dict()})


# ===========================================================================
# ADMIN: TREK APPROVAL WORKFLOW
# ===========================================================================
@api_bp.route("/admin/treks", methods=["GET"])
@token_required
@roles_required(UserRole.ADMIN.value)
def admin_all_treks():
    status_filter = request.args.get("status")
    query = Trek.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    treks = query.order_by(Trek.created_at.desc()).all()
    return jsonify({"treks": [t.to_dict() for t in treks]})


@api_bp.route("/admin/treks/pending", methods=["GET"])
@token_required
@roles_required(UserRole.ADMIN.value)
def pending_treks():
    treks = Trek.query.filter_by(status=TrekStatus.PENDING.value).order_by(Trek.created_at.asc()).all()
    return jsonify({"treks": [t.to_dict() for t in treks]})


@api_bp.route("/admin/treks/<int:trek_id>/approve", methods=["PUT"])
@token_required
@roles_required(UserRole.ADMIN.value)
def approve_trek(trek_id):
    trek = Trek.query.get(trek_id)
    if not trek:
        return jsonify({"error": "Trek not found"}), 404
    if _role_value(trek.status) != TrekStatus.PENDING.value:
        return jsonify({"error": "Only pending treks can be approved"}), 400

    trek.status = TrekStatus.APPROVED.value
    db.session.commit()
    return jsonify({"message": "Trek approved", "trek": trek.to_dict()})


@api_bp.route("/admin/treks/<int:trek_id>/reject", methods=["PUT"])
@token_required
@roles_required(UserRole.ADMIN.value)
def reject_trek(trek_id):
    trek = Trek.query.get(trek_id)
    if not trek:
        return jsonify({"error": "Trek not found"}), 404
    if _role_value(trek.status) != TrekStatus.PENDING.value:
        return jsonify({"error": "Only pending treks can be rejected"}), 400

    trek.status = TrekStatus.REJECTED.value
    db.session.commit()
    return jsonify({"message": "Trek rejected", "trek": trek.to_dict()})


# ===========================================================================
# ADMIN: DASHBOARD STATS + REPORTING
# ===========================================================================
@api_bp.route("/admin/dashboard/stats", methods=["GET"])
@token_required
@roles_required(UserRole.ADMIN.value)
def dashboard_stats():
    total_trekkers = User.query.filter_by(role=UserRole.TREKKER.value).count()
    total_staff = User.query.filter_by(role=UserRole.STAFF.value).count()
    blacklisted_users = User.query.filter_by(status=UserStatus.BLACKLISTED.value).count()

    total_treks = Trek.query.count()
    pending_treks_count = Trek.query.filter_by(status=TrekStatus.PENDING.value).count()
    open_treks_count = Trek.query.filter_by(status=TrekStatus.OPEN.value).count()
    completed_treks_count = Trek.query.filter_by(status=TrekStatus.COMPLETED.value).count()

    total_bookings = Booking.query.filter_by(status=BookingStatus.CONFIRMED.value).count()

    revenue = (
        db.session.query(func.sum(Trek.price * Booking.num_slots))
        .select_from(Booking)
        .join(Trek, Booking.trek_id == Trek.id)
        .filter(Booking.status == BookingStatus.CONFIRMED.value)
        .scalar()
        or 0
    )

    return jsonify(
        {
            "total_trekkers": total_trekkers,
            "total_staff": total_staff,
            "blacklisted_users": blacklisted_users,
            "total_treks": total_treks,
            "pending_treks": pending_treks_count,
            "open_treks": open_treks_count,
            "completed_treks": completed_treks_count,
            "total_bookings": total_bookings,
            "estimated_revenue": round(revenue, 2),
        }
    )


@api_bp.route("/admin/reports/monthly/trigger", methods=["POST"])
@token_required
@roles_required(UserRole.ADMIN.value)
def trigger_monthly_report():
    """Manually triggers the same task that Celery Beat runs on the 1st of each month."""
    task = generate_monthly_report.delay()
    return jsonify({"message": "Monthly report generation started", "task_id": task.id}), 202


@api_bp.route("/admin/reminders/trigger", methods=["POST"])
@token_required
@roles_required(UserRole.ADMIN.value)
def trigger_daily_reminders():
    """Lets an admin manually fire the daily reminder job on demand (for demoing)."""
    task = send_daily_reminders.delay()
    return jsonify({"message": "Reminder job started", "task_id": task.id}), 202