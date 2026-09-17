
import csv
import io
import os
import sys
from datetime import datetime, timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

from celery_app import celery_app

REPORTS_DIR = os.path.join(BASE_DIR, "reports")
EXPORTS_DIR = os.path.join(BASE_DIR, "exports")


def _get_flask_app():
    
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)
    from app import app  # noqa: WPS433 (intentional local import)

    return app


@celery_app.task(name="tasks.send_daily_reminders", bind=True, max_retries=3)
def send_daily_reminders(self):
    
    app = _get_flask_app()
    with app.app_context():
        from models import Booking, BookingStatus, Trek, TrekStatus

        today = datetime.utcnow().date()
        window_end = today + timedelta(days=3)

        upcoming_bookings = (
            Booking.query.join(Trek)
            .filter(
                Booking.status == BookingStatus.CONFIRMED.value,
                Trek.status.in_([TrekStatus.OPEN.value, TrekStatus.CLOSED.value]),
                Trek.start_date >= today,
                Trek.start_date <= window_end,
            )
            .all()
        )

        notifications = []
        for booking in upcoming_bookings:
            message = (
                f"Reminder: your trek '{booking.trek.title}' to "
                f"{booking.trek.location} starts on {booking.trek.start_date}. "
                f"Pack your gear!"
            )
            # SIMULATED notification channel (email/SMS/push would go here).
            print(f"[NOTIFICATION -> {booking.trekker.email}] {message}")
            notifications.append(
                {
                    "user_email": booking.trekker.email,
                    "trek_title": booking.trek.title,
                    "start_date": booking.trek.start_date.isoformat(),
                    "message": message,
                }
            )

        return {
            "status": "completed",
            "run_at": datetime.utcnow().isoformat(),
            "notifications_sent": len(notifications),
            "details": notifications,
        }


@celery_app.task(name="tasks.generate_monthly_report", bind=True, max_retries=3)
def generate_monthly_report(self):
    
    app = _get_flask_app()
    with app.app_context():
        from models import Booking, BookingStatus, Trek, TrekStatus, User, UserRole

        now = datetime.utcnow()
        period_start = now - timedelta(days=30)

        new_users = User.query.filter(
            User.role == UserRole.TREKKER.value, User.created_at >= period_start
        ).count()

        new_bookings = Booking.query.filter(Booking.booking_date >= period_start).all()
        confirmed_bookings = [b for b in new_bookings if b.status == BookingStatus.CONFIRMED.value]
        cancelled_bookings = [b for b in new_bookings if b.status == BookingStatus.CANCELLED.value]

        revenue = sum(
            (b.trek.price * b.num_slots) for b in confirmed_bookings if b.trek is not None
        )

        treks_completed = Trek.query.filter(
            Trek.status == TrekStatus.COMPLETED.value, Trek.updated_at >= period_start
        ).count()

        treks_opened = Trek.query.filter(Trek.created_at >= period_start).count()

        top_treks = sorted(
            Trek.query.all(),
            key=lambda t: t.booked_slots,
            reverse=True,
        )[:5]

        rows_html = "".join(
            f"<tr><td>{t.title}</td><td>{t.location}</td>"
            f"<td>{t.booked_slots}/{t.total_slots}</td>"
            f"<td>{(t.status.value if hasattr(t.status, 'value') else t.status)}</td></tr>"
            for t in top_treks
        )

        html_report = f"""
        <html>
        <head><meta charset="utf-8"><title>Monthly Activity Report</title></head>
        <body style="font-family: Arial, sans-serif; padding: 24px; color: #222;">
            <h1>Trekking Management Application - Monthly Activity Report</h1>
            <p><strong>Period:</strong> {period_start.strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')}</p>
            <hr>
            <h2>Summary</h2>
            <ul>
                <li>New trekker registrations: {new_users}</li>
                <li>New bookings: {len(new_bookings)}</li>
                <li>Confirmed bookings: {len(confirmed_bookings)}</li>
                <li>Cancelled bookings: {len(cancelled_bookings)}</li>
                <li>Treks submitted: {treks_opened}</li>
                <li>Treks completed: {treks_completed}</li>
                <li>Estimated revenue (confirmed bookings): ${revenue:,.2f}</li>
            </ul>
            <h2>Top Treks by Bookings</h2>
            <table border="1" cellpadding="6" cellspacing="0">
                <tr><th>Title</th><th>Location</th><th>Slots Booked</th><th>Status</th></tr>
                {rows_html if rows_html else '<tr><td colspan="4">No data</td></tr>'}
            </table>
            <p style="margin-top:24px;color:#777;">Generated automatically on {now.isoformat()} UTC</p>
        </body>
        </html>
        """

        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"monthly_report_{now.strftime('%Y_%m_%d_%H%M%S')}.html"
        filepath = os.path.join(REPORTS_DIR, filename)
        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write(html_report)

        return {
            "status": "completed",
            "generated_at": now.isoformat(),
            "report_file": filename,
            "report_path": filepath,
            "summary": {
                "new_users": new_users,
                "new_bookings": len(new_bookings),
                "confirmed_bookings": len(confirmed_bookings),
                "cancelled_bookings": len(cancelled_bookings),
                "treks_submitted": treks_opened,
                "treks_completed": treks_completed,
                "estimated_revenue": round(revenue, 2),
            },
            "html": html_report,
        }


@celery_app.task(name="tasks.export_user_bookings_csv", bind=True, max_retries=3)
def export_user_bookings_csv(self, user_id: int):
    
    app = _get_flask_app()
    with app.app_context():
        from models import Booking, User

        user = User.query.get(user_id)
        if not user:
            return {"status": "failed", "error": "User not found"}

        bookings = Booking.query.filter_by(user_id=user_id).order_by(
            Booking.booking_date.desc()
        ).all()

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ["Booking ID", "Trek Title", "Location", "Start Date", "End Date",
             "Slots Booked", "Price Per Slot", "Status", "Booking Date"]
        )
        for b in bookings:
            trek = b.trek
            writer.writerow(
                [
                    b.id,
                    trek.title if trek else "",
                    trek.location if trek else "",
                    trek.start_date.isoformat() if trek and trek.start_date else "",
                    trek.end_date.isoformat() if trek and trek.end_date else "",
                    b.num_slots,
                    trek.price if trek else "",
                    b.status.value if hasattr(b.status, "value") else b.status,
                    b.booking_date.isoformat() if b.booking_date else "",
                ]
            )
        csv_content = buffer.getvalue()

        os.makedirs(EXPORTS_DIR, exist_ok=True)
        filename = f"booking_history_user_{user_id}_{int(datetime.utcnow().timestamp())}.csv"
        filepath = os.path.join(EXPORTS_DIR, filename)
        with open(filepath, "w", encoding="utf-8", newline="") as fh:
            fh.write(csv_content)

        return {
            "status": "completed",
            "user_email": user.email,
            "row_count": len(bookings),
            "export_file": filename,
            "export_path": filepath,
            "csv_content": csv_content,
        }
    

