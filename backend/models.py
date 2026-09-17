
from datetime import datetime
from enum import Enum

from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db



class UserRole(str, Enum):
    ADMIN = "admin"
    STAFF = "staff"
    TREKKER = "trekker"


class UserStatus(str, Enum):
    ACTIVE = "active"
    BLACKLISTED = "blacklisted"


class TrekStatus(str, Enum):
    PENDING = "pending"      
    APPROVED = "approved"    
    OPEN = "open"             
    CLOSED = "closed"         
    COMPLETED = "completed"   
    REJECTED = "rejected"     


class BookingStatus(str, Enum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(150), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(20))
   
    role = db.Column(db.String(20), nullable=False, default=UserRole.TREKKER.value)
    status = db.Column(db.String(20), nullable=False, default=UserStatus.ACTIVE.value)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # One-to-one: only populated for role == staff
    staff_profile = db.relationship(
        "StaffProfile", backref="user", uselist=False, cascade="all, delete-orphan"
    )
    # Bookings made by this user (for role == trekker)
    bookings = db.relationship(
        "Booking", backref="trekker", lazy=True, foreign_keys="Booking.user_id"
    )
    # Treks authored by this user (for role == staff/admin)
    treks_created = db.relationship(
        "Trek", backref="creator", lazy=True, foreign_keys="Trek.created_by"
    )

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    def to_dict(self):
        role = self.role.value if isinstance(self.role, UserRole) else self.role
        status = self.status.value if isinstance(self.status, UserStatus) else self.status
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "role": role,
            "status": status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "staff_profile": self.staff_profile.to_dict() if self.staff_profile else None,
        }


class StaffProfile(db.Model):
    __tablename__ = "staff_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    designation = db.Column(db.String(100), default="Trek Coordinator")
    assigned_region = db.Column(db.String(120))
    joined_date = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "designation": self.designation,
            "assigned_region": self.assigned_region,
            "joined_date": self.joined_date.isoformat() if self.joined_date else None,
        }


class Trek(db.Model):
    __tablename__ = "treks"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    location = db.Column(db.String(150), nullable=False)
    difficulty = db.Column(db.String(20), default="easy") 
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    price = db.Column(db.Float, nullable=False, default=0.0)
    total_slots = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default=TrekStatus.PENDING.value)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    bookings = db.relationship(
        "Booking", backref="trek", lazy=True, cascade="all, delete-orphan"
    )

    @property
    def booked_slots(self) -> int:
        return sum(
            b.num_slots for b in self.bookings if b.status == BookingStatus.CONFIRMED.value
        )

    @property
    def available_slots(self) -> int:
        return max(self.total_slots - self.booked_slots, 0)

    def to_dict(self, include_bookings: bool = False):
        status = self.status.value if isinstance(self.status, TrekStatus) else self.status
        data = {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "location": self.location,
            "difficulty": self.difficulty,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "price": self.price,
            "total_slots": self.total_slots,
            "booked_slots": self.booked_slots,
            "available_slots": self.available_slots,
            "status": status,
            "created_by": self.created_by,
            "creator_name": self.creator.name if self.creator else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_bookings:
            data["bookings"] = [b.to_dict() for b in self.bookings]
        return data


class Booking(db.Model):
    __tablename__ = "bookings"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    trek_id = db.Column(db.Integer, db.ForeignKey("treks.id"), nullable=False)
    num_slots = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(db.String(20), nullable=False, default=BookingStatus.CONFIRMED.value)
    booking_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    cancelled_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        status = self.status.value if isinstance(self.status, BookingStatus) else self.status
        return {
            "id": self.id,
            "user_id": self.user_id,
            "trekker_name": self.trekker.name if self.trekker else None,
            "trekker_email": self.trekker.email if self.trekker else None,
            "trek_id": self.trek_id,
            "trek_title": self.trek.title if self.trek else None,
            "num_slots": self.num_slots,
            "status": status,
            "booking_date": self.booking_date.isoformat() if self.booking_date else None,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
        }