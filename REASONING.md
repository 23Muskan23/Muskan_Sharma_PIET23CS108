# Reasoning

## Reading the problem

Stripped of the framing story, the paper register is failing at four separate jobs
that were being done by one sheet of paper:

1. A **catalog** — what exists, and how many of each.
2. A **ledger** — who has what, since when, and when it's due.
3. A **policy enforcer** — nobody was stopping one club from taking everything, and
   nobody was charging for lateness or protecting the room with a deposit.
4. A **communication channel** — "is a DSLR free this weekend?" is a question the
   register can't answer without someone manually checking every row.

The brief is explicit that the *order* matters: get borrowing, availability, and
returns solid first, then layer deposits and limits on top. I built and tested it in
that order (see commit history / AI log), rather than designing the deposit and limit
logic first and bolting borrowing on afterward.

## Modelling decision: individual units, not just item types

The single biggest design choice was to track **each physical copy separately**
(`DC-01`, `DC-02`, `DC-03` for three DSLRs) instead of just a count of "DSLRs: 3".
A count-only model can answer "how many DSLRs are free" but can't answer "which
specific DSLR did Ananya take, and is *that one* back yet" — and the paper register's
actual failure mode (two clubs both think they have "the projector") is a unit-identity
problem, not a count problem. Individual units also make the transfer requirement
sensible: you transfer *a specific unit's* active loan, not an abstract quantity.

## Why a due date + late fee is the deterrent, not a hard block

The problem statement says borrowers "hang onto things far too long." I considered
hard-blocking checkout past the due date but decided against auto-punishing — the desk
still needs judgment calls (a professor's shoot ran long, etc.). Instead the system
makes lateness *visible and costed*: the dashboard surfaces overdue items sorted by
how late they are, and the late fee is calculated transparently (days late × per-day
rate) and previewed before the return is confirmed, so the person at the desk isn't
doing mental math or trusting the borrower's word for how late they were.

## Why deposits are refunded, not just "kept or given back"

The brief says the deposit is refundable "minus any late fee" — not forfeited outright
on any lateness. I modelled it as `refund = max(0, deposit − late_fee)`, clamped at
zero so a very late return can't leave the borrower owing the room money through this
flow (that's a separate, manual conversation, not something the register should silently
compute as a negative refund).

## Why the borrowing limit is per-borrower, not per-item-type

"One person shouldn't be able to book out half the room at once" is a statement about
a person's total footprint, not about hoarding one item type. A cap of 3 *active loans
total*, checked at checkout, stops someone from taking 2 DSLRs + a projector + 2 mics
just as much as it stops them taking 5 tripods. The number itself is a constant at the
top of `app.py` specifically so it's a one-line policy change, not a schema change.

## The transfer feature

This was the one place the spec gave an exact, testable contract: the due date must
carry over **unchanged**, and the item's availability must be **unaffected**. I
implemented transfer as *only* changing `Loan.borrower_id` (plus writing an audit row
to a `TransferLog` table so there's a trail of who handed off to whom and when) —
`due_date` and `Unit.status` are never touched by the transfer route. I wrote an
automated test (see AI_LOGS.md / commit history) that checks out an item, transfers it,
and asserts both the due date and the unit's `on_loan` status survived the transfer
byte-for-byte, rather than just eyeballing it in the browser.

## Extras beyond the minimum ask

The brief says: "Notice the questions people ask and the gaps in the paper register —
solving those is the job." Two questions came up directly in the prompt text, so I
built for them specifically:

- *"is a DSLR free this weekend?"* → the catalog page shows live availability per unit,
  and for fully-booked item types shows the soonest return date instead of just "0 free."
- People "keep asking" → a **waitlist** lets someone register interest in a fully-booked
  item type instead of having to keep asking at the desk; on return, the desk sees a
  flag naming who's waiting.

I also added a dashboard stock chart and a per-borrower history page — not required,
but they're what turn "a database with forms" into something a real desk volunteer
would actually keep open during a shift.

## What I deliberately left out

- **Formal date-range reservations** (book a DSLR for a specific future weekend while
  it's still out on a different loan) — the brief's example is answerable with "when is
  it next free," which the availability hint covers; a full reservation calendar with
  conflict detection felt like scope creep for the time available and isn't asked for.
- **Auth / login** — the register today has none; adding accounts would be solving a
  problem the brief doesn't raise, at the cost of time better spent on the core flows.
- **Email sending** — "nudge people to return it" is satisfied by the dashboard
  surfacing overdue items prominently for the desk to act on; wiring real SMTP felt
  like infrastructure risk for a 2.5-hour window, not a functional gap in the core idea.
