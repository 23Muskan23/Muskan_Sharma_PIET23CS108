"""
AV Room Gear Tracker
--------------------
A lending-desk system for the college AV room: tracks equipment units,
borrowing, availability, returns, late fees, refundable deposits,
per-borrower limits, and loan transfers.

Run:
    pip install -r requirements.txt
    python app.py
Then open http://localhost:5000
"""
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(BASE_DIR, 'rental.db')}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = "av-room-dev-secret"  # fine for a demo/assessment build

db = SQLAlchemy(app)

# ---------------------------------------------------------------------------
# Business rules (kept as constants so they're easy to point at / justify)
# ---------------------------------------------------------------------------
DEFAULT_LOAN_DAYS = 3          # default borrow window if none picked
MAX_ACTIVE_LOANS_PER_BORROWER = 3   # "one person shouldn't book out half the room"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ItemType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)          # e.g. "DSLR Camera"
    category = db.Column(db.String(40), nullable=False)       # Camera/Projector/Audio/Support
    late_fee_per_day = db.Column(db.Float, nullable=False, default=20.0)
    deposit_amount = db.Column(db.Float, nullable=False, default=500.0)
    description = db.Column(db.String(255), default="")

    units = db.relationship("Unit", backref="item_type", cascade="all, delete-orphan")

    def available_units(self):
        return [u for u in self.units if u.status == "available"]

    def total_units(self):
        return len(self.units)


class Unit(db.Model):
    """A single physical, trackable copy of an item type (e.g. DSLR-02)."""
    id = db.Column(db.Integer, primary_key=True)
    item_type_id = db.Column(db.Integer, db.ForeignKey("item_type.id"), nullable=False)
    code = db.Column(db.String(30), unique=True, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="available")  # available/on_loan/maintenance

    loans = db.relationship("Loan", backref="unit")

    def active_loan(self):
        return next((l for l in self.loans if l.status == "active"), None)


class Borrower(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), default="")

    loans = db.relationship("Loan", backref="borrower")

    def active_loan_count(self):
        return sum(1 for l in self.loans if l.status == "active")


class Loan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    unit_id = db.Column(db.Integer, db.ForeignKey("unit.id"), nullable=False)
    borrower_id = db.Column(db.Integer, db.ForeignKey("borrower.id"), nullable=False)

    checkout_date = db.Column(db.Date, nullable=False, default=date.today)
    due_date = db.Column(db.Date, nullable=False)
    return_date = db.Column(db.Date, nullable=True)

    deposit_collected = db.Column(db.Float, nullable=False, default=0.0)
    late_fee_charged = db.Column(db.Float, nullable=True)
    deposit_refunded = db.Column(db.Float, nullable=True)

    status = db.Column(db.String(20), nullable=False, default="active")  # active/returned
    notes = db.Column(db.String(255), default="")

    transfers = db.relationship("TransferLog", backref="loan", cascade="all, delete-orphan")

    def is_overdue(self):
        return self.status == "active" and date.today() > self.due_date

    def days_overdue(self, as_of=None):
        as_of = as_of or date.today()
        if as_of <= self.due_date:
            return 0
        return (as_of - self.due_date).days


class TransferLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey("loan.id"), nullable=False)
    from_borrower_id = db.Column(db.Integer, db.ForeignKey("borrower.id"), nullable=False)
    to_borrower_id = db.Column(db.Integer, db.ForeignKey("borrower.id"), nullable=False)
    transferred_at = db.Column(db.DateTime, default=datetime.utcnow)
    note = db.Column(db.String(255), default="")

    from_borrower = db.relationship("Borrower", foreign_keys=[from_borrower_id])
    to_borrower = db.relationship("Borrower", foreign_keys=[to_borrower_id])


class Waitlist(db.Model):
    """If every unit of a type is out, people can queue instead of nagging the register."""
    id = db.Column(db.Integer, primary_key=True)
    item_type_id = db.Column(db.Integer, db.ForeignKey("item_type.id"), nullable=False)
    borrower_name = db.Column(db.String(120), nullable=False)
    borrower_email = db.Column(db.String(120), nullable=False)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    notified = db.Column(db.Boolean, default=False)

    item_type = db.relationship("ItemType")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def calc_late_fee(loan: Loan, return_date: date) -> float:
    days_late = max(0, (return_date - loan.due_date).days)
    return round(days_late * loan.unit.item_type.late_fee_per_day, 2)


def next_available_date(unit: Unit) -> date:
    """Best-effort answer to 'when is this free?' — the due date of its active loan."""
    loan = unit.active_loan()
    if loan:
        return loan.due_date
    return date.today()


# ---------------------------------------------------------------------------
# Routes: Dashboard
# ---------------------------------------------------------------------------
@app.route("/")
def dashboard():
    item_types = ItemType.query.all()
    active_loans = Loan.query.filter_by(status="active").order_by(Loan.due_date).all()
    overdue = [l for l in active_loans if l.is_overdue()]
    due_soon = [l for l in active_loans
                if not l.is_overdue() and (l.due_date - date.today()).days <= 1]

    total_units = Unit.query.count()
    on_loan = Unit.query.filter_by(status="on_loan").count()
    available = Unit.query.filter_by(status="available").count()

    stats = {
        "total_units": total_units,
        "on_loan": on_loan,
        "available": available,
        "overdue_count": len(overdue),
        "active_loans": len(active_loans),
    }

    chart_labels = [it.name for it in item_types]
    chart_available = [len(it.available_units()) for it in item_types]
    chart_on_loan = [it.total_units() - len(it.available_units()) for it in item_types]

    return render_template(
        "dashboard.html",
        stats=stats, overdue=overdue, due_soon=due_soon,
        chart_labels=chart_labels, chart_available=chart_available, chart_on_loan=chart_on_loan,
    )


# ---------------------------------------------------------------------------
# Routes: Catalog / Availability
# ---------------------------------------------------------------------------
@app.route("/catalog")
def catalog():
    q = request.args.get("q", "").strip().lower()
    item_types = ItemType.query.all()
    if q:
        item_types = [it for it in item_types if q in it.name.lower() or q in it.category.lower()]
    # attach a "free from" hint for fully-booked types
    hints = {}
    for it in item_types:
        if not it.available_units() and it.units:
            soonest = min(next_available_date(u) for u in it.units)
            hints[it.id] = soonest
    return render_template("catalog.html", item_types=item_types, q=q, hints=hints)


@app.route("/catalog/<int:item_type_id>")
def catalog_detail(item_type_id):
    it = ItemType.query.get_or_404(item_type_id)
    units = sorted(it.units, key=lambda u: u.code)
    waitlist = Waitlist.query.filter_by(item_type_id=it.id, notified=False).all()
    return render_template("catalog_detail.html", it=it, units=units, waitlist=waitlist)


@app.route("/join_waitlist/<int:item_type_id>", methods=["POST"])
def join_waitlist(item_type_id):
    w = Waitlist(
        item_type_id=item_type_id,
        borrower_name=request.form["name"].strip(),
        borrower_email=request.form["email"].strip(),
    )
    db.session.add(w)
    db.session.commit()
    flash(f"Added to the waitlist — you'll be first in line when one frees up.", "success")
    return redirect(url_for("catalog_detail", item_type_id=item_type_id))


# ---------------------------------------------------------------------------
# Routes: Checkout (borrow)
# ---------------------------------------------------------------------------
@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    item_types = ItemType.query.all()
    preselect_unit = request.args.get("unit_id", type=int)

    if request.method == "POST":
        unit_id = int(request.form["unit_id"])
        unit = Unit.query.get_or_404(unit_id)

        if unit.status != "available":
            flash("That unit is no longer available — someone beat you to it.", "danger")
            return redirect(url_for("checkout"))

        name = request.form["name"].strip()
        email = request.form["email"].strip()
        phone = request.form.get("phone", "").strip()

        borrower = Borrower.query.filter_by(email=email).first()
        if not borrower:
            borrower = Borrower(name=name, email=email, phone=phone)
            db.session.add(borrower)
            db.session.flush()

        # Borrowing limit — "one person shouldn't book out half the room"
        if borrower.active_loan_count() >= MAX_ACTIVE_LOANS_PER_BORROWER:
            flash(
                f"{borrower.name} already has {borrower.active_loan_count()} items out "
                f"(limit is {MAX_ACTIVE_LOANS_PER_BORROWER}). Return something first.",
                "danger",
            )
            return redirect(url_for("checkout"))

        due_date_str = request.form.get("due_date")
        due = datetime.strptime(due_date_str, "%Y-%m-%d").date() if due_date_str else \
            date.today() + timedelta(days=DEFAULT_LOAN_DAYS)

        loan = Loan(
            unit_id=unit.id,
            borrower_id=borrower.id,
            checkout_date=date.today(),
            due_date=due,
            deposit_collected=unit.item_type.deposit_amount,
            status="active",
        )
        unit.status = "on_loan"
        db.session.add(loan)
        db.session.commit()
        flash(
            f"Checked out {unit.code} to {borrower.name}. Due back {due.strftime('%d %b')}. "
            f"Deposit collected: ₹{unit.item_type.deposit_amount:.0f}.",
            "success",
        )
        return redirect(url_for("dashboard"))

    return render_template(
        "checkout.html",
        item_types=item_types,
        preselect_unit=preselect_unit,
        default_due=(date.today() + timedelta(days=DEFAULT_LOAN_DAYS)).isoformat(),
        max_loans=MAX_ACTIVE_LOANS_PER_BORROWER,
    )


# ---------------------------------------------------------------------------
# Routes: Return
# ---------------------------------------------------------------------------
@app.route("/returns")
def returns_list():
    active_loans = Loan.query.filter_by(status="active").order_by(Loan.due_date).all()
    return render_template("returns.html", loans=active_loans, today=date.today())


@app.route("/return/<int:loan_id>", methods=["GET", "POST"])
def return_loan(loan_id):
    loan = Loan.query.get_or_404(loan_id)
    if loan.status != "active":
        flash("This loan is already closed.", "warning")
        return redirect(url_for("returns_list"))

    preview_fee = calc_late_fee(loan, date.today())
    preview_refund = round(max(0.0, loan.deposit_collected - preview_fee), 2)

    if request.method == "POST":
        ret_date = date.today()
        fee = calc_late_fee(loan, ret_date)
        refund = round(max(0.0, loan.deposit_collected - fee), 2)

        loan.return_date = ret_date
        loan.late_fee_charged = fee
        loan.deposit_refunded = refund
        loan.status = "returned"
        loan.unit.status = "available"
        db.session.commit()

        msg = f"{loan.unit.code} marked returned. "
        msg += f"Late fee: ₹{fee:.0f}. " if fee else "Returned on time — no late fee. "
        msg += f"Deposit refunded: ₹{refund:.0f}."
        flash(msg, "success")

        waiter = Waitlist.query.filter_by(item_type_id=loan.unit.item_type_id, notified=False).first()
        if waiter:
            flash(f"Note: {waiter.borrower_name} ({waiter.borrower_email}) is waiting for this item — notify them.", "info")

        return redirect(url_for("returns_list"))

    return render_template("return_confirm.html", loan=loan, preview_fee=preview_fee, preview_refund=preview_refund)


@app.route("/api/loan/<int:loan_id>/preview")
def api_preview(loan_id):
    loan = Loan.query.get_or_404(loan_id)
    fee = calc_late_fee(loan, date.today())
    refund = round(max(0.0, loan.deposit_collected - fee), 2)
    return jsonify({"late_fee": fee, "refund": refund, "days_overdue": loan.days_overdue()})


# ---------------------------------------------------------------------------
# Routes: Transfer  (loan moves to a new borrower; due date & availability unchanged)
# ---------------------------------------------------------------------------
@app.route("/transfer/<int:loan_id>", methods=["GET", "POST"])
def transfer_loan(loan_id):
    loan = Loan.query.get_or_404(loan_id)
    if loan.status != "active":
        flash("Only active loans can be transferred.", "warning")
        return redirect(url_for("returns_list"))

    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip()
        phone = request.form.get("phone", "").strip()

        if email.lower() == loan.borrower.email.lower():
            flash("That's the same borrower — nothing to transfer.", "warning")
            return redirect(url_for("transfer_loan", loan_id=loan.id))

        new_borrower = Borrower.query.filter_by(email=email).first()
        if not new_borrower:
            new_borrower = Borrower(name=name, email=email, phone=phone)
            db.session.add(new_borrower)
            db.session.flush()

        # New borrower still has to respect the room limit
        if new_borrower.active_loan_count() >= MAX_ACTIVE_LOANS_PER_BORROWER:
            flash(
                f"Can't transfer — {new_borrower.name} is already at the {MAX_ACTIVE_LOANS_PER_BORROWER}-item limit.",
                "danger",
            )
            return redirect(url_for("transfer_loan", loan_id=loan.id))

        old_borrower = loan.borrower
        log = TransferLog(loan_id=loan.id, from_borrower_id=old_borrower.id, to_borrower_id=new_borrower.id)
        loan.borrower_id = new_borrower.id
        # due_date is deliberately left untouched; unit.status is deliberately left untouched
        db.session.add(log)
        db.session.commit()

        flash(
            f"Transferred {loan.unit.code} from {old_borrower.name} to {new_borrower.name}. "
            f"Due date stays {loan.due_date.strftime('%d %b')} — item stays marked on loan throughout.",
            "success",
        )
        return redirect(url_for("returns_list"))

    return render_template("transfer.html", loan=loan)


# ---------------------------------------------------------------------------
# Routes: Borrowers
# ---------------------------------------------------------------------------
@app.route("/borrowers")
def borrowers_list():
    borrowers = Borrower.query.order_by(Borrower.name).all()
    return render_template("borrowers.html", borrowers=borrowers)


@app.route("/borrowers/<int:borrower_id>")
def borrower_detail(borrower_id):
    b = Borrower.query.get_or_404(borrower_id)
    loans = sorted(b.loans, key=lambda l: l.checkout_date, reverse=True)
    return render_template("borrower_detail.html", b=b, loans=loans)


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------
def seed():
    if ItemType.query.first():
        return

    catalog_seed = [
        ("DSLR Camera", "Camera", 50.0, 2000.0, 3),
        ("Projector", "Projector", 40.0, 1500.0, 2),
        ("Wireless Mic", "Audio", 15.0, 500.0, 5),
        ("Tripod", "Support", 10.0, 300.0, 4),
    ]
    for name, cat, fee, dep, count in catalog_seed:
        it = ItemType(name=name, category=cat, late_fee_per_day=fee, deposit_amount=dep,
                      description=f"{name} available for booking from the AV room.")
        db.session.add(it)
        db.session.flush()
        prefix = "".join(w[0] for w in name.split())[:4].upper()
        for i in range(1, count + 1):
            db.session.add(Unit(item_type_id=it.id, code=f"{prefix}-{i:02d}", status="available"))

    db.session.commit()

    # A couple of demo loans so the dashboard isn't empty, incl. one overdue
    b1 = Borrower(name="Ananya Rao", email="ananya@college.edu", phone="9990001111")
    b2 = Borrower(name="Rohit Verma", email="rohit@college.edu", phone="9990002222")
    db.session.add_all([b1, b2])
    db.session.flush()

    dslr_unit = Unit.query.filter(Unit.code.like("DC-%")).first()
    mic_unit = Unit.query.filter(Unit.code.like("WM-%")).first()

    loan1 = Loan(unit_id=dslr_unit.id, borrower_id=b1.id,
                 checkout_date=date.today() - timedelta(days=5),
                 due_date=date.today() - timedelta(days=2),  # overdue demo
                 deposit_collected=dslr_unit.item_type.deposit_amount, status="active")
    dslr_unit.status = "on_loan"

    loan2 = Loan(unit_id=mic_unit.id, borrower_id=b2.id,
                 checkout_date=date.today() - timedelta(days=1),
                 due_date=date.today() + timedelta(days=2),
                 deposit_collected=mic_unit.item_type.deposit_amount, status="active")
    mic_unit.status = "on_loan"

    db.session.add_all([loan1, loan2])
    db.session.commit()


with app.app_context():
    db.create_all()
    seed()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
