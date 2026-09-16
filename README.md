# AV Room Gear Tracker

A lending-desk web app for the college AV room — replaces the paper register with
live tracking of cameras, projectors, mics and tripods: who has what, when it's due,
late fees, refundable deposits, a per-borrower limit, and the ability to hand an
active loan off to someone else mid-loan.

## Features

- **Catalog & availability** — every physical unit (e.g. `DC-01`, `DC-02` for two DSLRs)
  is tracked individually, so "is a DSLR free this weekend?" has a real answer instead
  of a shrug.
- **Checkout / borrowing** — pick a unit, borrower, and due date; a deposit is collected
  automatically based on the item type.
- **Returns** — one click marks an item back; the late fee (if any) and deposit refund
  are calculated and shown before you confirm.
- **Deposits** — collected at checkout, refunded minus any late fee at return.
- **Borrowing limit** — a borrower can't hold more than 3 active items at once, so one
  club can't walk out with half the room.
- **Transfers** — an active loan can move from one borrower to another. The due date
  carries over unchanged and the unit stays marked "on loan" the whole time, so
  availability is never affected by the handoff.
- **Dashboard with nudges** — overdue and due-soon items are surfaced up front instead
  of being buried in a register.
- **Waitlist** — when every unit of a type is checked out, people can join a waitlist
  instead of pestering the desk.
- **Borrower history** — a running ledger per borrower of everything they've had, late
  fees paid, and current standing.

## Tech stack

- **Backend:** Python, Flask, Flask-SQLAlchemy
- **Database:** SQLite (file-based, zero setup — `rental.db` is created automatically)
- **Frontend:** Server-rendered Jinja2 templates + Bootstrap 5 + a little vanilla JS
  (Chart.js for the stock chart, fetch-free — forms post normally so it degrades
  gracefully)

## Setup

```bash
# 1. Clone and enter the repo
git clone <this-repo-url>
cd equipment_rental

# 2. Create a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the app
python app.py
```

The app starts at **http://localhost:5000** (or the forwarded port if you're in
GitHub Codespaces — Codespaces will prompt you to open it in the browser).

On first run, `app.py` automatically creates `rental.db` and seeds it with:
- 4 item types: DSLR Camera (3 units), Projector (2), Wireless Mic (5), Tripod (4)
- 2 demo borrowers and 2 demo loans (one deliberately overdue, so the dashboard
  nudges aren't empty on first look)

## Project structure

```
equipment_rental/
├── app.py                  # routes, models, business rules, seed data
├── requirements.txt
├── templates/               # Jinja2 pages (dashboard, catalog, checkout, returns, transfer...)
├── static/style.css
├── README.md
├── REASONING.md
└── AI_LOGS.md
```

## Debugging notes

- **"No module named flask"** — you likely forgot to activate the virtual
  environment or run `pip install -r requirements.txt`.
- **Port already in use** — another process is on 5000; run
  `python app.py` after editing the last line of `app.py` to use a different
  `port=`, or kill the other process.
- **Want a clean slate?** Delete `rental.db` and restart the app — it will
  reseed automatically.
- **Codespaces port not opening** — check the "Ports" tab in the Codespaces
  terminal panel and make sure port 5000 is set to "Public" or "Forwarded".

## Business rules (where to find them / how to change them)

All the tunable rules live as constants at the top of `app.py`:

```python
DEFAULT_LOAN_DAYS = 3                 # default due date if none picked
MAX_ACTIVE_LOANS_PER_BORROWER = 3     # per-borrower limit
```

Per-item-type late fee (`late_fee_per_day`) and `deposit_amount` are stored on
each `ItemType` row, since a DSLR should cost more to lose than a tripod.
