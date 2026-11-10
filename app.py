
import webbrowser
import threading
import os
import math

from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash
)
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta


# ------------------ APP CONFIGURATION ------------------

app = Flask(__name__)
app.secret_key = "mysecretkey"

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///parking.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

PARKING_RATE = 50.0


# ------------------ DATABASE MODELS ------------------

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)


class Slot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), nullable=False, default="available")
    vehicle = db.Column(db.String(50), nullable=True)


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    slot_id = db.Column(db.Integer, nullable=False)
    vehicle = db.Column(db.String(50), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), nullable=False)


class Bill(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    booking_id = db.Column(
        db.Integer,
        db.ForeignKey("booking.id"),
        nullable=False,
        unique=True
    )

    user_id = db.Column(db.Integer, nullable=False)
    slot_id = db.Column(db.Integer, nullable=False)

    rate_per_hour = db.Column(db.Float, default=PARKING_RATE)
    booked_hours = db.Column(db.Integer, nullable=False)

    entry_time = db.Column(db.DateTime, nullable=False)
    expected_exit = db.Column(db.DateTime, nullable=False)
    checkout_time = db.Column(db.DateTime, nullable=True)

    estimated_amount = db.Column(db.Float, nullable=False)
    advance_paid = db.Column(db.Float, nullable=False, default=0)

    actual_minutes = db.Column(db.Integer, default=0)
    extra_charge = db.Column(db.Float, default=0.0)

    final_amount = db.Column(db.Float, default=0.0)
    balance_due = db.Column(db.Float, default=0.0)

    payment_status = db.Column(
        db.String(50),
        default="Pending"
    )

    status = db.Column(db.String(30), default="Active")


# ------------------ LOGIN ------------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()

        if user and user.password == password:
            session["user"] = user.username
            return redirect(url_for("home"))

        flash("Invalid Username or Password", "danger")

    return render_template("login.html")


# ------------------ LOGOUT ------------------

@app.route("/logout")
def logout():

    session.pop("user", None)

    return redirect(url_for("login"))


# ------------------ HOME PAGE ------------------

@app.route("/")
def home():

    if "user" not in session:
        return redirect(url_for("login"))

    slots = Slot.query.all()

    available_count = Slot.query.filter_by(
        status="available"
    ).count()

    booked_count = Slot.query.filter_by(
        status="booked"
    ).count()

    return render_template(
        "index.html",
        slots=slots,
        available_count=available_count,
        booked_count=booked_count,
        user=session["user"]
    )


# ------------------ BOOK PARKING SLOT ------------------

@app.route("/book/<int:slot_id>", methods=["GET", "POST"])
def book(slot_id):

    if "user" not in session:
        return redirect(url_for("login"))

    slot = db.get_or_404(Slot, slot_id)

    user = User.query.filter_by(
        username=session["user"]
    ).first()

    if request.method == "POST":

        if slot.status != "available":
            flash("This parking slot is already booked.", "danger")
            return redirect(url_for("home"))

        vehicle_number = request.form.get(
            "vehicle", ""
        ).strip()

        if not vehicle_number:
            flash("Please enter your vehicle number.", "danger")
            return render_template(
                "booking.html",
                slot_id=slot_id
            )

        slot.status = "booked"
        slot.vehicle = vehicle_number

        booking_record = Booking(
            user_id=user.id,
            slot_id=slot.id,
            vehicle=vehicle_number,
            status="booked"
        )

        db.session.add(booking_record)
        db.session.commit()

        flash(
            "Parking slot booked successfully! Select your parking duration.",
            "success"
        )

        return redirect(
            url_for(
                "create_bill",
                booking_id=booking_record.id
            )
        )

    return render_template(
        "booking.html",
        slot_id=slot_id
    )


# ------------------ CREATE BILL ------------------

@app.route("/billing/<int:booking_id>", methods=["GET", "POST"])
def create_bill(booking_id):

    if "user" not in session:
        return redirect(url_for("login"))

    user = User.query.filter_by(
        username=session["user"]
    ).first()

    booking = db.session.get(Booking, booking_id)

    if (
        not booking
        or booking.user_id != user.id
        or booking.status != "booked"
    ):
        flash("Valid active booking not found.", "danger")
        return redirect(url_for("home"))

    existing_bill = Bill.query.filter_by(
        booking_id=booking_id
    ).first()

    if existing_bill:
        return redirect(
            url_for("view_bill", bill_id=existing_bill.id)
        )

    if request.method == "POST":

        try:
            hours = int(request.form.get("hours", 1))
        except (ValueError, TypeError):
            flash("Please select a valid duration.", "danger")
            return redirect(
                url_for("create_bill", booking_id=booking_id)
            )

        if hours < 1 or hours > 24:
            flash(
                "Please select between 1 and 24 hours.",
                "danger"
            )
            return redirect(
                url_for("create_bill", booking_id=booking_id)
            )

        entry = datetime.utcnow()

        estimated = round(hours * PARKING_RATE, 2)

        advance = round(estimated * 0.50, 2)

        bill = Bill(
            booking_id=booking.id,
            user_id=user.id,
            slot_id=booking.slot_id,
            rate_per_hour=PARKING_RATE,
            booked_hours=hours,
            entry_time=entry,
            expected_exit=entry + timedelta(hours=hours),
            estimated_amount=estimated,
            advance_paid=0,
            payment_status="Pending",
            status="Active"
        )

        db.session.add(bill)
        db.session.commit()

        flash(
            "Bill generated successfully! Please select a payment method.",
            "success"
        )

        return redirect(
            url_for("view_bill", bill_id=bill.id)
        )

    return render_template(
        "billing_form.html",
        booking=booking,
        rate=PARKING_RATE
    )


# ------------------ VIEW BILL ------------------

@app.route("/bill/<int:bill_id>")
def view_bill(bill_id):

    if "user" not in session:
        return redirect(url_for("login"))

    user = User.query.filter_by(
        username=session["user"]
    ).first()

    bill = db.session.get(Bill, bill_id)

    if not bill or bill.user_id != user.id:
        flash("Bill not found.", "danger")
        return redirect(url_for("home"))

    return render_template(
        "bill.html",
        bill=bill
    )


# ------------------ DEMO PAYMENT GATEWAY ------------------

@app.route("/pay/<int:bill_id>", methods=["GET", "POST"])
def pay_advance(bill_id):

    if "user" not in session:
        return redirect(url_for("login"))

    user = User.query.filter_by(
        username=session["user"]
    ).first()

    bill = db.session.get(Bill, bill_id)

    if not bill or bill.user_id != user.id:
        flash("Bill not found.", "danger")
        return redirect(url_for("home"))

    if bill.status == "Completed":
        return redirect(
            url_for("view_bill", bill_id=bill.id)
        )

    if bill.payment_status != "Pending":
        flash(
            "A payment option has already been recorded.",
            "info"
        )
        return redirect(
            url_for("view_bill", bill_id=bill.id)
        )

    if request.method == "POST":

        method = request.form.get("payment_method")

        if method not in ["UPI", "Card", "Cash"]:
            flash(
                "Please select a valid payment method.",
                "danger"
            )
            return redirect(
                url_for("pay_advance", bill_id=bill.id)
            )

        if method in ["UPI", "Card"]:

            # DEMO ONLY: no real payment is processed.
            bill.advance_paid = round(
                bill.estimated_amount * 0.50,
                2
            )

            bill.payment_status = f"Paid - Demo {method}"

        elif method == "Cash":

            # Cash is payable at the parking counter.
            bill.advance_paid = 0

            bill.payment_status = "Cash - Pay at Counter"

        db.session.commit()

        return render_template(
            "payment_success.html",
            bill=bill,
            method=method
        )

    return render_template(
        "payment.html",
        bill=bill
    )


# ------------------ CHECKOUT AND FINAL BILL ------------------

@app.route("/checkout/<int:bill_id>", methods=["POST"])
def checkout(bill_id):

    if "user" not in session:
        return redirect(url_for("login"))

    user = User.query.filter_by(
        username=session["user"]
    ).first()

    bill = db.session.get(Bill, bill_id)

    if not bill or bill.user_id != user.id:
        flash("Bill not found.", "danger")
        return redirect(url_for("home"))

    if bill.status == "Completed":
        return redirect(
            url_for("view_bill", bill_id=bill.id)
        )

    if bill.payment_status == "Pending":
        flash(
            "Please select a payment method before checkout.",
            "warning"
        )
        return redirect(
            url_for("view_bill", bill_id=bill.id)
        )

    checkout_time = datetime.utcnow()

    actual_minutes = max(
        1,
        math.ceil(
            (checkout_time - bill.entry_time).total_seconds() / 60
        )
    )

    # Calculate actual parking charge.
    final_amount = round(
        actual_minutes * bill.rate_per_hour / 60,
        2
    )

    # Extra charge beyond estimated amount.
    extra_charge = round(
        max(0, final_amount - bill.estimated_amount),
        2
    )

    # Calculate remaining balance.
    balance_due = round(
        final_amount - bill.advance_paid,
        2
    )

    bill.checkout_time = checkout_time
    bill.actual_minutes = actual_minutes
    bill.final_amount = final_amount
    bill.extra_charge = extra_charge
    bill.balance_due = balance_due
    bill.status = "Completed"

    if balance_due > 0:
        bill.payment_status = "Balance Due"

    elif balance_due < 0:
        bill.payment_status = "Refund Due"

    else:
        bill.payment_status = "Paid"

    # Make parking slot available again.
    slot = db.session.get(Slot, bill.slot_id)

    if slot:
        slot.status = "available"
        slot.vehicle = None

    # Record checkout in booking history.
    booking = db.session.get(
        Booking,
        bill.booking_id
    )

    if booking:
        checkout_record = Booking(
            user_id=booking.user_id,
            slot_id=booking.slot_id,
            vehicle=booking.vehicle,
            status="checkout"
        )

        db.session.add(checkout_record)

    db.session.commit()

    flash(
        "Checkout completed and final bill generated!",
        "success"
    )

    return redirect(
        url_for("view_bill", bill_id=bill.id)
    )


# ------------------ BILLING HISTORY ------------------

@app.route("/billing-history")
def billing_history():

    if "user" not in session:
        return redirect(url_for("login"))

    user = User.query.filter_by(
        username=session["user"]
    ).first()

    bills = Bill.query.filter_by(
        user_id=user.id
    ).order_by(
        Bill.id.desc()
    ).all()

    return render_template(
        "billing_history.html",
        bills=bills
    )


# ------------------ CANCEL BOOKING ------------------

@app.route("/unbook/<int:slot_id>")
def unbook(slot_id):

    if "user" not in session:
        return redirect(url_for("login"))

    slot = db.get_or_404(Slot, slot_id)

    user = User.query.filter_by(
        username=session["user"]
    ).first()

    if slot.status == "booked":

        active_bill = Bill.query.join(
            Booking,
            Bill.booking_id == Booking.id
        ).filter(
            Bill.slot_id == slot.id,
            Bill.status == "Active"
        ).first()

        if active_bill:
            flash(
                "Please complete checkout before cancelling this booking.",
                "warning"
            )
            return redirect(url_for("home"))

        booking_record = Booking(
            user_id=user.id,
            slot_id=slot.id,
            vehicle=slot.vehicle or "",
            status="unbooked"
        )

        slot.status = "available"
        slot.vehicle = None

        db.session.add(booking_record)
        db.session.commit()

        flash(
            "Parking booking cancelled.",
            "success"
        )

    return redirect(url_for("home"))


# ------------------ SEARCH VEHICLE ------------------

@app.route("/search", methods=["POST"])
def search():

    if "user" not in session:
        return redirect(url_for("login"))

    query = request.form.get(
        "vehicle_search", ""
    ).strip()

    found_slot = Slot.query.filter_by(
        vehicle=query
    ).first()

    return render_template(
        "index.html",
        slots=Slot.query.all(),
        available_count=Slot.query.filter_by(
            status="available"
        ).count(),
        booked_count=Slot.query.filter_by(
            status="booked"
        ).count(),
        search_result=found_slot,
        query=query,
        user=session["user"]
    )


# ------------------ EDIT PARKING SLOT ------------------

@app.route("/edit/<int:slot_id>", methods=["GET", "POST"])
def edit_slot(slot_id):

    if "user" not in session:
        return redirect(url_for("login"))

    slot = db.get_or_404(Slot, slot_id)

    if request.method == "POST":

        vehicle_number = request.form.get(
            "vehicle", ""
        ).strip()

        status = request.form.get(
            "status", "available"
        )

        if status not in ["available", "booked"]:
            flash("Invalid parking slot status.", "danger")
            return redirect(
                url_for("edit_slot", slot_id=slot.id)
            )

        if status == "booked" and not vehicle_number:
            flash(
                "Please enter a vehicle number for a booked slot.",
                "danger"
            )
            return redirect(
                url_for("edit_slot", slot_id=slot.id)
            )

        user = User.query.filter_by(
            username=session["user"]
        ).first()

        old_status = slot.status
        old_vehicle = slot.vehicle or ""

        if status == "booked" and (
            old_status != "booked"
            or old_vehicle != vehicle_number
        ):

            booking_record = Booking(
                user_id=user.id,
                slot_id=slot.id,
                vehicle=vehicle_number,
                status="booked"
            )

            db.session.add(booking_record)

        elif old_status == "booked" and status == "available":

            active_bill = Bill.query.filter_by(
                slot_id=slot.id,
                status="Active"
            ).first()

            if active_bill:
                flash(
                    "Complete checkout before making this slot available.",
                    "warning"
                )
                return redirect(
                    url_for("edit_slot", slot_id=slot.id)
                )

            booking_record = Booking(
                user_id=user.id,
                slot_id=slot.id,
                vehicle=old_vehicle,
                status="unbooked"
            )

            db.session.add(booking_record)

        slot.vehicle = (
            vehicle_number if status == "booked" else None
        )

        slot.status = status

        db.session.commit()

        flash(
            "Parking slot updated successfully!",
            "success"
        )

        return redirect(url_for("home"))

    return render_template(
        "slot.html",
        slot=slot
    )


# ------------------ DELETE PARKING SLOT ------------------

@app.route("/delete/<int:slot_id>", methods=["POST"])
def delete_slot(slot_id):

    if "user" not in session:
        return redirect(url_for("login"))

    slot = db.get_or_404(Slot, slot_id)

    active_bill = Bill.query.filter_by(
        slot_id=slot.id,
        status="Active"
    ).first()

    if active_bill:
        flash(
            "Complete checkout before deleting this slot.",
            "warning"
        )
        return redirect(url_for("home"))

    db.session.delete(slot)
    db.session.commit()

    flash(
        "Parking slot deleted successfully!",
        "success"
    )

    return redirect(url_for("home"))


# ------------------ BOOKING HISTORY ------------------

@app.route("/history")
def history():

    if "user" not in session:
        return redirect(url_for("login"))

    user = User.query.filter_by(
        username=session["user"]
    ).first()

    records = Booking.query.filter_by(
        user_id=user.id
    ).order_by(
        Booking.timestamp.desc()
    ).all()

    return render_template(
        "history.html",
        records=records
    )


# ------------------ DATABASE INITIALIZATION ------------------

if __name__ == "__main__":

    with app.app_context():

        db.create_all()

        # Create 10 parking slots if none exist.
        if Slot.query.count() == 0:

            for i in range(1, 11):
                db.session.add(
                    Slot(
                        id=i,
                        status="available"
                    )
                )

        # Login credentials.
        username = "Subhashree Rout"
        password = "subha@77"

        user = User.query.filter_by(
            username=username
        ).first()

        old_user = User.query.filter_by(
            username="Vartik Tripathi"
        ).first()

        if user:
            user.password = password

        elif old_user:
            old_user.username = username
            old_user.password = password

        else:
            user = User(
                username=username,
                password=password
            )

            db.session.add(user)

        db.session.commit()

    # Automatically open browser.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":

        threading.Timer(
            1.0,
            lambda: webbrowser.open_new(
                "http://127.0.0.1:5000"
            )
        ).start()

    app.run(debug=True)
