"""Glue between the database, the data pack, and the rules.

Endpoints in main.py call these functions. The rules themselves live in rules.py.
Traveler and supplier get different views: a traveler never sees other suppliers'
reasons, rule codes, or busy times; a supplier sees everything it needs to assign a car.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta

from . import rules
from .data_store import Catalog
from .db import now_iso
from .rules import BusyTime, RideContext, Violation


HOLD_MINUTES = 5        # guaranteed window: the car is held for the traveler this long
MAX_HOLD_MINUTES = 60   # the longest guarantee a supplier may give


def now() -> datetime:
    """The current time. One place for it, so tests can move the clock."""
    return datetime.now().replace(microsecond=0)


def _stamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


class ApiError(Exception):
    """Raised by services; main.py turns it into a JSON error response."""

    def __init__(self, status: int, errors: list[Violation]):
        super().__init__("; ".join(e.message for e in errors))
        self.status = status
        self.errors = errors


def _fail(status: int, rule: str, message: str, field: str | None = None):
    raise ApiError(status, [Violation(rule, message, field)])


# ---------------------------------------------------------------------------
# Busy times (R6): booked_rides.json + confirmed bookings in our database
# ---------------------------------------------------------------------------

def busy_times_by_vehicle(conn: sqlite3.Connection, catalog: Catalog,
                          exclude_booking: str | None = None) -> dict[str, list[BusyTime]]:
    """Every time each car is taken: pre-booked rides, our bookings, and guarantee holds.

    A hold = an OPEN offer whose guaranteed window has not ended. It is tagged with its request,
    and `for_request()` removes a request's own holds before that request is checked.
    """
    busy: dict[str, list[BusyTime]] = defaultdict(list)
    riders: dict[str, set] = defaultdict(set)   # S1: shared group -> requests with an open offer in it
    for row in conn.execute("SELECT share_group, request_id FROM offers WHERE share_group IS NOT NULL "
                            "AND status = 'OPEN'"):
        riders[row["share_group"]].add(row["request_id"])
    for ride in catalog.booked_rides:
        busy[ride["vehicle_id"]].append(BusyTime(
            rules.parse_datetime(ride["start"]), rules.parse_datetime(ride["end"]), ride["ride_id"]))
    rows = conn.execute(
        "SELECT booking_no, vehicle_id, busy_start, busy_end, share_group FROM bookings WHERE status = 'CONFIRMED'")
    for row in rows:
        if row["booking_no"] == exclude_booking:
            continue  # a change request checks the car against its *other* rides
        busy[row["vehicle_id"]].append(BusyTime(
            rules.parse_datetime(row["busy_start"]), rules.parse_datetime(row["busy_end"]),
            f"booking {row['booking_no']}", share_group=row["share_group"],
            riders=frozenset(riders.get(row["share_group"], ()))))
    holds = conn.execute(
        """SELECT o.vehicle_id, o.hold_until, o.share_group, o.shared_pickup, r.*
           FROM offers o JOIN ride_requests r USING (request_id)
           WHERE o.status = 'OPEN' AND r.status = 'OPEN' AND o.hold_until > ?""", (_stamp(now()),)).fetchall()
    for row in holds:
        _, ctx = context_for_row(row, catalog)
        if ctx:
            ctx = shared_ctx(ctx, row["shared_pickup"])
            until = rules.parse_datetime(row["hold_until"]).strftime("%H:%M:%S")
            busy[row["vehicle_id"]].append(BusyTime(
                ctx.busy_start, ctx.busy_end, f"held for another traveler until {until}", row["request_id"],
                row["share_group"], frozenset(riders.get(row["share_group"], ()))))
    return busy


def for_request(busy: dict[str, list[BusyTime]], request_id, share_group: str | None = None
                ) -> dict[str, list[BusyTime]]:
    """The busy times as request `request_id` sees them: its own holds do not block it.

    `request_id` may be one id or several (a shared ride checks both requests).
    S1: a shared ride does not block a family that still has an open offer in that same car, and
    with `share_group` nothing of that shared ride blocks it.
    """
    ids = {request_id} if isinstance(request_id, str) else set(request_id)

    def blocks(b: BusyTime) -> bool:
        if b.request_id in ids or (share_group and b.share_group == share_group):
            return False
        return not (ids & b.riders)

    return {v: [b for b in times if blocks(b)] for v, times in busy.items()}


def shared_ctx(ctx: RideContext, shared_pickup: str | None) -> RideContext:
    """A shared ride's car picks up at the shared pickup time; a private ride at the request's own."""
    return rules.at_pickup(ctx, rules.parse_datetime(shared_pickup)) if shared_pickup else ctx


# ---------------------------------------------------------------------------
# Ride requests
# ---------------------------------------------------------------------------

def row_to_payload(row: sqlite3.Row) -> dict:
    return {
        "flight_id": row["flight_id"], "hotel_id": row["hotel_id"], "adults": row["adults"],
        "child_ages": json.loads(row["child_ages"]), "large_bags": row["large_bags"],
        "small_bags": row["small_bags"], "pickup": row["pickup"], "car_type": row["car_type"],
        "price_inr": row["price_inr"],
    }


def context_for_row(row: sqlite3.Row, catalog: Catalog) -> tuple[list[Violation], RideContext | None]:
    return rules.validate_request(row_to_payload(row), catalog)


def request_view(row: sqlite3.Row, catalog: Catalog, ctx: RideContext | None = None,
                 audience: str = "supplier") -> dict:
    """Every detail of a request. The supplier view adds the car's busy time (R6)."""
    flight = catalog.flights.get(row["flight_id"], {})
    hotel = catalog.hotels.get(row["hotel_id"], {})
    child_ages = json.loads(row["child_ages"])
    view = {
        "request_id": row["request_id"],
        "traveler_name": row["traveler_name"],
        "status": row["status"],
        "created_at": row["created_at"],
        "flight": {k: flight.get(k) for k in
                   ("flight_id", "airline", "flight_number", "from", "to", "arrival_local")},
        "hotel": {k: hotel.get(k) for k in ("hotel_id", "name", "city", "area")},
        "adults": row["adults"],
        "child_ages": child_ages,
        "passengers": row["adults"] + len(child_ages),
        "large_bags": row["large_bags"],
        "small_bags": row["small_bags"],
        "pickup": row["pickup"],
        "car_type": row["car_type"],
        "price_inr": row["price_inr"],
        "route": None,
    }
    if ctx:
        r = ctx.trip.route
        view["route"] = {k: r[k] for k in
                         ("airport", "city", "area", "distance_km", "drive_minutes", "price_min_inr", "price_max_inr")}
        if audience == "supplier":
            view["busy_window"] = {"start": rules.fmt_dt(ctx.busy_start), "end": rules.fmt_dt(ctx.busy_end)}
    return view


def next_request_id(conn: sqlite3.Connection) -> str:
    highest = 0
    for (rid,) in conn.execute("SELECT request_id FROM ride_requests"):
        suffix = rid.rsplit("-", 1)[-1]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return f"REQ-{highest + 1:04d}"


def evaluate_all_suppliers(ctx: RideContext, catalog: Catalog,
                           busy: dict[str, list[BusyTime]]) -> list[rules.SupplierEvaluation]:
    return [rules.evaluate_supplier(c, ctx, busy) for c in catalog.companies.values()]


def get_request_row(conn: sqlite3.Connection, request_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM ride_requests WHERE request_id = ?", (request_id,)).fetchone()
    if row is None:
        _fail(404, "NOT_FOUND", f"Ride request {request_id} not found.")
    return row


def _traveler_summary(conn, catalog, row, busy) -> dict:
    """Traveler view of one request: details, availability, and how many taxis are offered."""
    problems, ctx = context_for_row(row, catalog)
    view = request_view(row, catalog, ctx, audience="traveler")
    if row["status"] != "OPEN":
        view["availability"] = None  # booked: the booking says it all
    elif ctx:
        own = for_request(busy, row["request_id"])
        view["availability"] = rules.traveler_availability(evaluate_all_suppliers(ctx, catalog, own), ctx)
    else:
        view["availability"] = {"available": False, "message": rules.NO_RIDE_MESSAGE,
                                "reason": "; ".join(p.message for p in problems)}
    counts = conn.execute(
        "SELECT COUNT(*) AS total, SUM(status = 'OPEN') AS open FROM offers WHERE request_id = ?",
        (row["request_id"],)).fetchone()
    view["offer_count"] = counts["total"] or 0
    view["open_offer_count"] = counts["open"] or 0
    booking = conn.execute("SELECT booking_no, status FROM bookings WHERE request_id = ? ORDER BY created_at DESC",
                           (row["request_id"],)).fetchone()
    view["booking_no"] = booking["booking_no"] if booking else None
    return view


def request_detail(conn: sqlite3.Connection, catalog: Catalog, request_id: str) -> dict:
    """Traveler view of one request (M2 traveler side)."""
    row = get_request_row(conn, request_id)
    return _traveler_summary(conn, catalog, row, busy_times_by_vehicle(conn, catalog))


# ---------------------------------------------------------------------------
# Traveler names: required and unique, so a traveler can find their ride by name
# ---------------------------------------------------------------------------

NAME_MIN_LENGTH, NAME_MAX_LENGTH = 2, 60


def clean_name(value) -> str:
    """Trim and collapse spaces: "  Menon   family " -> "Menon family"."""
    return " ".join(str(value or "").split())


def _find_by_name(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    """Names are compared without caring about capitals: "menon family" = "Menon Family"."""
    return conn.execute("SELECT * FROM ride_requests WHERE lower(traveler_name) = lower(?)",
                        (clean_name(name),)).fetchone()


def check_name(conn: sqlite3.Connection, raw) -> tuple[str, list[Violation]]:
    name = clean_name(raw)
    if not name:
        return name, [Violation("NAME", "Enter your name. It must be unique, so you can find your ride "
                                        "with it later.", "traveler_name")]
    if not NAME_MIN_LENGTH <= len(name) <= NAME_MAX_LENGTH:
        return name, [Violation("NAME", f"Your name must be {NAME_MIN_LENGTH} to {NAME_MAX_LENGTH} characters.",
                                "traveler_name")]
    if _find_by_name(conn, name):
        return name, [Violation("NAME", f'The name "{name}" is already taken. Please choose another, '
                                        f'for example "{name} 2".', "traveler_name")]
    return name, []


def name_availability(conn: sqlite3.Connection, raw) -> dict:
    """Live check for the form, while the traveler types."""
    name, errors = check_name(conn, raw)
    return {"name": name, "available": not errors, "message": errors[0].message if errors else "This name is free."}


def lookup_booking(conn: sqlite3.Connection, catalog: Catalog, name, booking_no) -> dict:
    """Track a booking: the traveler's name AND the 10-digit number must both match."""
    number = str(booking_no or "").strip()
    row = None
    if number.isdigit() and len(number) == 10:
        row = conn.execute(
            """SELECT b.booking_no FROM bookings b JOIN ride_requests r USING (request_id)
               WHERE b.booking_no = ? AND lower(r.traveler_name) = lower(?)""", (number, clean_name(name))).fetchone()
    if row is None:
        _fail(404, "NOT_FOUND", "No booking matches that name and booking number. Check both and try again.")
    return booking_summary(conn, catalog, row["booking_no"])


def find_request_by_name(conn: sqlite3.Connection, catalog: Catalog, raw) -> dict:
    """A traveler who lost their booking number finds their ride by their unique name."""
    name = clean_name(raw)
    row = _find_by_name(conn, name) if name else None
    if row is None:
        _fail(404, "NOT_FOUND", f'No ride request found for the name "{name}". Check the spelling.')
    return request_detail(conn, catalog, row["request_id"])


def create_request(conn: sqlite3.Connection, catalog: Catalog, payload: dict) -> dict:
    """M1: validate the name and R1, R2, R3, then save."""
    name, name_errors = check_name(conn, payload.get("traveler_name"))
    errors, ctx = rules.validate_request(payload, catalog)
    errors = name_errors + errors
    if errors:
        raise ApiError(422, errors)

    request_id = next_request_id(conn)
    conn.execute(
        """INSERT INTO ride_requests
           (request_id, traveler_name, flight_id, hotel_id, adults, child_ages, large_bags, small_bags,
            pickup, car_type, price_inr, status, source, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?, 'OPEN', 'APP', ?)""",
        (
            request_id, name,
            ctx.trip.flight["flight_id"], ctx.trip.hotel["hotel_id"], ctx.adults,
            json.dumps(ctx.child_ages), ctx.large_bags, ctx.small_bags,
            rules.fmt_dt(ctx.pickup), ctx.car_type, ctx.price_inr, now_iso(),
        ),
    )
    conn.commit()
    return request_detail(conn, catalog, request_id)


def list_requests(conn: sqlite3.Connection, catalog: Catalog, ids: list[str] | None = None) -> list[dict]:
    """Traveler list. `ids` = the requests this traveler posted (kept in their browser)."""
    if ids is not None:
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT * FROM ride_requests WHERE request_id IN ({marks}) ORDER BY created_at DESC, request_id DESC",
            ids).fetchall()
    else:
        rows = conn.execute("SELECT * FROM ride_requests ORDER BY created_at DESC, request_id DESC").fetchall()
    busy = busy_times_by_vehicle(conn, catalog)
    return [_traveler_summary(conn, catalog, row, busy) for row in rows]


def price_range(catalog: Catalog, flight_id: str | None, hotel_id: str | None) -> dict:
    """The suggested range shown in the form while the traveler types (R3)."""
    errors, trip = rules.resolve_trip(flight_id, hotel_id, catalog)
    if errors:
        raise ApiError(422, errors)
    r = trip.route
    return {
        "airport": r["airport"], "city": r["city"], "area": r["area"],
        "distance_km": r["distance_km"], "drive_minutes": r["drive_minutes"],
        "price_min_inr": r["price_min_inr"], "price_max_inr": r["price_max_inr"],
        "arrival_local": rules.fmt_dt(trip.arrival),
        "earliest_pickup": rules.fmt_dt(trip.earliest_pickup),
    }


# ---------------------------------------------------------------------------
# Offers = assigned taxis (M3, M4, G1, G4)
# ---------------------------------------------------------------------------

def get_offer_row(conn: sqlite3.Connection, offer_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM offers WHERE offer_id = ?", (offer_id,)).fetchone()
    if row is None:
        _fail(404, "NOT_FOUND", f"Taxi offer {offer_id} not found.")
    return row


def _guarantee_seconds_left(offer: sqlite3.Row) -> int | None:
    """Seconds left in the guaranteed window, 0 once it is over, None for a closed offer."""
    if offer["status"] != "OPEN" or not offer["hold_until"]:
        return None
    return max(0, int((rules.parse_datetime(offer["hold_until"]) - now()).total_seconds()))


def _shared_info(conn: sqlite3.Connection, catalog: Catalog, share_group: str | None, request_id: str,
                 audience: str = "traveler") -> dict | None:
    """S1: who rides along. A traveler sees only how many people and bags; a supplier also sees who."""
    if not share_group:
        return None
    other = conn.execute(
        """SELECT o.status AS offer_status, o.shared_pickup, r.* FROM offers o JOIN ride_requests r USING (request_id)
           WHERE o.share_group = ? AND o.request_id != ?""", (share_group, request_id)).fetchone()
    mine = conn.execute(
        "SELECT o.shared_pickup, r.* FROM offers o JOIN ride_requests r USING (request_id) "
        "WHERE o.share_group = ? AND o.request_id = ?", (share_group, request_id)).fetchone()
    if other is None or mine is None:
        return None
    other_passengers = other["adults"] + len(json.loads(other["child_ages"]))
    my_passengers = mine["adults"] + len(json.loads(mine["child_ages"]))
    info = {
        "share_group": share_group,
        "pickup": mine["shared_pickup"],
        "other_passengers": other_passengers,
        "other_large_bags": other["large_bags"],
        "other_small_bags": other["small_bags"],
        "other_hotel": catalog.hotels.get(other["hotel_id"], {}).get("name"),
        "total_passengers": my_passengers + other_passengers,
        "total_large_bags": mine["large_bags"] + other["large_bags"],
        "total_small_bags": mine["small_bags"] + other["small_bags"],
        "other_booked": other["offer_status"] == "BOOKED",
    }
    if audience == "supplier":
        info["with_request_id"] = other["request_id"]
        info["with_traveler_name"] = other["traveler_name"]
    return info


def offer_view(conn: sqlite3.Connection, catalog: Catalog, offer: sqlite3.Row,
               ctx: RideContext | None = None, busy: dict | None = None, audience: str = "traveler") -> dict:
    company = catalog.companies.get(offer["company_id"], {})
    vehicle = catalog.vehicles.get(offer["vehicle_id"], {})
    view = {
        "offer_id": offer["offer_id"],
        "request_id": offer["request_id"],
        "company_id": offer["company_id"],
        "company_name": company.get("name", offer["company_id"]),
        "rating": company.get("rating"),
        "vehicle": {k: vehicle.get(k) for k in ("vehicle_id", "type", "seats", "large_bags", "small_bags")},
        "price_inr": offer["price_inr"],
        "status": offer["status"],
        "guaranteed_until": offer["hold_until"],
        "guarantee_seconds_left": _guarantee_seconds_left(offer),  # countdown for the screen
        "guaranteed": bool(_guarantee_seconds_left(offer)),
        "created_at": offer["created_at"],
        "booking_no": None,
        "warning": None,  # why an OPEN offer would be refused if booked now
        "shared": _shared_info(conn, catalog, offer["share_group"], offer["request_id"], audience),
    }
    if offer["status"] in ("BOOKED", "CANCELLED"):
        b = conn.execute("SELECT booking_no FROM bookings WHERE offer_id = ?", (offer["offer_id"],)).fetchone()
        view["booking_no"] = b["booking_no"] if b else None
    elif offer["status"] == "OPEN" and ctx and busy is not None:
        ride = shared_ctx(ctx, offer["shared_pickup"])
        clash = rules.find_conflict(ride.busy_start, ride.busy_end, for_request(
            busy, offer["request_id"], offer["share_group"]).get(offer["vehicle_id"], []))
        if clash:
            view["warning"] = ("This car is being held for another traveler right now."
                               if clash.request_id else "This car has since been booked for another ride.")
    return view


def _hold_minutes(value) -> tuple[int, list[Violation]]:
    """How long the confirmation is guaranteed. Empty = the default 5 minutes."""
    if value is None:
        return HOLD_MINUTES, []
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= MAX_HOLD_MINUTES:
        return HOLD_MINUTES, [Violation(
            "INPUT", f"The guarantee must be between 1 and {MAX_HOLD_MINUTES} minutes.", "hold_minutes")]
    return value, []


def create_offer(conn: sqlite3.Connection, catalog: Catalog, payload: dict) -> dict:
    """M3 / R7: a supplier assigns one of its cars with a price. Refused with the rule it breaks."""
    request = get_request_row(conn, payload.get("request_id") or "")
    company = get_company(catalog, payload.get("company_id") or "")
    if request["status"] != "OPEN":
        state = "cancelled" if request["status"] == "CANCELLED" else "already booked"
        _fail(409, "R8", f"Request {request['request_id']} is {state}. No more taxis can be assigned.")

    problems, ctx = context_for_row(request, catalog)
    if not ctx:
        raise ApiError(422, problems)

    vehicle_id = payload.get("vehicle_id")
    if not vehicle_id:
        _fail(422, "INPUT", "Choose one of your cars.", "vehicle_id")

    # A car held for ANOTHER traveler is not free (R6); a hold on this same request does not count.
    busy = for_request(busy_times_by_vehicle(conn, catalog), request["request_id"])
    errors = rules.check_assignment(company, vehicle_id, payload.get("price_inr"), ctx, busy)
    minutes, minute_errors = _hold_minutes(payload.get("hold_minutes"))
    errors += minute_errors
    hold_until = _stamp(now() + timedelta(minutes=minutes))
    duplicate = conn.execute(
        "SELECT 1 FROM offers WHERE request_id = ? AND vehicle_id = ? AND status = 'OPEN'",
        (request["request_id"], vehicle_id)).fetchone()
    if duplicate:
        errors.append(Violation("R7", f"Car {vehicle_id} is already offered for this request.", "vehicle_id"))
    if errors:
        raise ApiError(422, errors)

    cur = conn.execute(
        """INSERT INTO offers (request_id, company_id, vehicle_id, price_inr, status, hold_until, created_at)
           VALUES (?,?,?,?, 'OPEN', ?, ?)""",
        (request["request_id"], company["company_id"], vehicle_id, payload["price_inr"], hold_until, _stamp(now())))
    conn.commit()
    return offer_view(conn, catalog, get_offer_row(conn, cur.lastrowid), ctx, busy)


def _open_request_ctx(conn: sqlite3.Connection, catalog: Catalog, request_id: str) -> tuple[sqlite3.Row, RideContext]:
    request = get_request_row(conn, request_id)
    if request["status"] != "OPEN":
        state = "cancelled" if request["status"] == "CANCELLED" else "already booked"
        _fail(409, "R8", f"Request {request_id} is {state}. No more taxis can be assigned.")
    problems, ctx = context_for_row(request, catalog)
    if not ctx:
        raise ApiError(422, problems)
    return request, ctx


def create_shared_offer(conn: sqlite3.Connection, catalog: Catalog, payload: dict) -> dict:
    """S1: a supplier assigns ONE car to TWO requests on the same flight to the same area.

    Each family gets its own offer, with its own price inside the route's range (R3), and books
    or rejects it on its own. The car must be free (R6) and fit both families together (R5).
    """
    ids = [str(i or "").strip() for i in (payload.get("request_ids") or [])]
    prices = list(payload.get("prices") or [])
    if len(ids) != 2 or ids[0] == ids[1] or not all(ids):
        _fail(422, "S1", "Choose two different ride requests to share one car.", "request_ids")
    if len(prices) != 2:
        _fail(422, "INPUT", "Enter a price for each of the two travelers.", "prices")
    company = get_company(catalog, payload.get("company_id") or "")
    (req_a, ctx_a), (req_b, ctx_b) = (_open_request_ctx(conn, catalog, i) for i in ids)
    vehicle_id = payload.get("vehicle_id")
    if not vehicle_id:
        _fail(422, "INPUT", "Choose one of your cars.", "vehicle_id")

    errors, together = rules.plan_shared_ride(ctx_a, ctx_b)
    if errors:
        raise ApiError(422, errors)
    busy = for_request(busy_times_by_vehicle(conn, catalog), ids)   # neither family's own holds block it
    errors = []
    for i, (request, price) in enumerate(zip((req_a, req_b), prices)):
        field = "price_inr" if i == 0 else "price_inr_2"
        if i == 0:   # R4, R5 (everyone together), R6, and the first price
            found = rules.check_assignment(company, vehicle_id, price, together, busy)
        else:        # the second price only
            found = [rules.Violation("INPUT", "Price must be a whole number of rupees above 0.", field)] \
                if not rules._is_int(price) or price <= 0 else \
                [e for e in [rules.check_price_in_range(price, together.trip.route, field)] if e]
        for e in found:
            if e.field in ("price_inr", "price_inr_2"):
                e = Violation(e.rule, f"{request['traveler_name']}: {e.message}", field)
            errors.append(e)
    minutes, minute_errors = _hold_minutes(payload.get("hold_minutes"))
    errors += minute_errors
    for request in (req_a, req_b):
        if conn.execute("SELECT 1 FROM offers WHERE request_id = ? AND vehicle_id = ? AND status = 'OPEN'",
                        (request["request_id"], vehicle_id)).fetchone():
            errors.append(Violation("R7", f"Car {vehicle_id} is already offered to {request['traveler_name']}.",
                                    "vehicle_id"))
    if errors:
        raise ApiError(422, errors)

    hold_until = _stamp(now() + timedelta(minutes=minutes))
    next_id = conn.execute("SELECT COALESCE(MAX(offer_id), 0) + 1 FROM offers").fetchone()[0]
    group, pickup = f"SH-{next_id:04d}", rules.fmt_dt(together.pickup)
    offer_ids = []
    for request, price in zip((req_a, req_b), prices):
        cur = conn.execute(
            """INSERT INTO offers (request_id, company_id, vehicle_id, price_inr, status, hold_until,
                                   share_group, shared_pickup, created_at) VALUES (?,?,?,?, 'OPEN', ?,?,?,?)""",
            (request["request_id"], company["company_id"], vehicle_id, price, hold_until, group, pickup,
             _stamp(now())))
        offer_ids.append(cur.lastrowid)
    conn.commit()
    busy_now = busy_times_by_vehicle(conn, catalog)
    return {"share_group": group, "pickup": pickup,
            "offers": [offer_view(conn, catalog, get_offer_row(conn, oid), ctx, busy_now, audience="supplier")
                       for oid, ctx in zip(offer_ids, (ctx_a, ctx_b))]}


def request_offers(conn: sqlite3.Connection, catalog: Catalog, request_id: str) -> list[dict]:
    """M4: every taxi assigned to a request, from all suppliers (traveler side)."""
    request = get_request_row(conn, request_id)
    _, ctx = context_for_row(request, catalog)
    busy = busy_times_by_vehicle(conn, catalog)
    rows = conn.execute("SELECT * FROM offers WHERE request_id = ? ORDER BY price_inr, offer_id",
                        (request_id,)).fetchall()
    return [offer_view(conn, catalog, r, ctx, busy) for r in rows]


def reject_offer(conn: sqlite3.Connection, catalog: Catalog, offer_id: int) -> dict:
    """R8: the traveler rejects one taxi. A rejected taxi cannot be booked (and its hold ends)."""
    offer = get_offer_row(conn, offer_id)
    if offer["status"] != "OPEN":
        _fail(409, "R8", f"This taxi can no longer be rejected (it is {offer['status'].replace('_', ' ').lower()}).")
    conn.execute("UPDATE offers SET status = 'REJECTED' WHERE offer_id = ?", (offer_id,))
    conn.commit()
    return offer_view(conn, catalog, get_offer_row(conn, offer_id))


def _close_offers_for_taken_car(conn: sqlite3.Connection, catalog: Catalog, vehicle_id: str,
                                ctx: RideContext, booked_request_id: str, share_group: str | None = None) -> None:
    """The car is now booked: other travelers' open offers of it for an overlapping time can
    never be booked, so they become CAR_TAKEN instead of staying "open" forever.
    Offers of the same car for another day stay open: one car can do both rides."""
    rows = conn.execute(
        """SELECT o.offer_id, o.share_group, o.shared_pickup, r.* FROM offers o JOIN ride_requests r USING (request_id)
           WHERE o.vehicle_id = ? AND o.status = 'OPEN' AND o.request_id != ?""",
        (vehicle_id, booked_request_id)).fetchall()
    for row in rows:
        if share_group and row["share_group"] == share_group:
            continue   # S1: the other family of this shared ride rides in the same car
        _, other = context_for_row(row, catalog)
        other = shared_ctx(other, row["shared_pickup"]) if other else None
        if other and rules.overlaps(ctx.busy_start, ctx.busy_end, other.busy_start, other.busy_end):
            conn.execute("UPDATE offers SET status = 'CAR_TAKEN' WHERE offer_id = ?", (row["offer_id"],))


def new_booking_no(conn: sqlite3.Connection) -> str:
    """A unique 10-digit number (first digit never 0)."""
    while True:
        number = str(secrets.randbelow(9_000_000_000) + 1_000_000_000)
        if not conn.execute("SELECT 1 FROM bookings WHERE booking_no = ?", (number,)).fetchone():
            return number


def book_offer(conn: sqlite3.Connection, catalog: Catalog, offer_id: int) -> dict:
    """R8 + M6: book one taxi.

    Inside the guaranteed window the car is held for this traveler, so the check below always passes.
    After it, the offer is still open, but the car may have gone to someone else: checked right now.
    """
    offer = get_offer_row(conn, offer_id)
    request = get_request_row(conn, offer["request_id"])

    if offer["status"] == "REJECTED":
        _fail(409, "R8", "You rejected this taxi, so it cannot be booked.")
    if offer["status"] == "CAR_TAKEN":
        _fail(409, "R6", "This car was booked by another traveler for the same time. Please choose another taxi.")
    if request["status"] == "CANCELLED":
        _fail(409, "CANCEL", "This ride was cancelled. Post a new ride request to book again.")
    if request["status"] != "OPEN" or offer["status"] != "OPEN":
        _fail(409, "R8", "This ride is already booked.")

    problems, ctx = context_for_row(request, catalog)
    if not ctx:
        raise ApiError(422, problems)
    ctx = shared_ctx(ctx, offer["shared_pickup"])   # S1: a shared car picks up at the shared time

    # BEGIN IMMEDIATE takes the database's write lock BEFORE the check below. If two travelers press
    # Book at the same moment, the second waits here until the first has saved its booking, then
    # sees it in its own check, so a car can never be booked twice.
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        if get_offer_row(conn, offer_id)["status"] != "OPEN" or \
                get_request_row(conn, request["request_id"])["status"] != "OPEN":
            _fail(409, "R8", "This ride is already booked.")
        # M6: no double booking. Check the car against every booking and every other traveler's hold now.
        # S1: the other family of the same shared ride is in the same car, so it does not count.
        busy = for_request(busy_times_by_vehicle(conn, catalog), request["request_id"], offer["share_group"])
        clash = rules.find_conflict(ctx.busy_start, ctx.busy_end, busy.get(offer["vehicle_id"], []))
        if clash:
            why = "it is being held for another traveler" if clash.request_id else "it was booked for another ride"
            _fail(409, "R6", f"Sorry, car {offer['vehicle_id']} is no longer available at your pickup time "
                             f"({why}). The guaranteed time for this offer is over. Please choose another taxi.")

        booking_no = new_booking_no(conn)
        conn.execute(
            """INSERT INTO bookings (booking_no, request_id, offer_id, company_id, vehicle_id, flight_id,
                                     pickup, busy_start, busy_end, price_inr, status, share_group, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?, 'CONFIRMED', ?, ?)""",
            (booking_no, request["request_id"], offer_id, offer["company_id"], offer["vehicle_id"],
             request["flight_id"], rules.fmt_dt(ctx.pickup), rules.fmt_dt(ctx.busy_start),
             rules.fmt_dt(ctx.busy_end), offer["price_inr"], offer["share_group"], now_iso()))
        conn.execute("UPDATE offers SET status = 'BOOKED' WHERE offer_id = ?", (offer_id,))
        conn.execute("UPDATE offers SET status = 'NOT_CHOSEN' WHERE request_id = ? AND offer_id != ? "
                     "AND status = 'OPEN'", (request["request_id"], offer_id))
        conn.execute("UPDATE ride_requests SET status = 'BOOKED', pickup = ? WHERE request_id = ?",
                     (rules.fmt_dt(ctx.pickup), request["request_id"]))
        _close_offers_for_taken_car(conn, catalog, offer["vehicle_id"], ctx, request["request_id"],
                                    offer["share_group"])
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return booking_summary(conn, catalog, booking_no)


# ---------------------------------------------------------------------------
# Bookings (M5)
# ---------------------------------------------------------------------------

def booking_summary(conn: sqlite3.Connection, catalog: Catalog, booking_no: str) -> dict:
    """M5: flight, hotel, pickup, supplier, car, price. Wrong number -> not found."""
    booking_no = (booking_no or "").strip()
    row = None
    if booking_no.isdigit() and len(booking_no) == 10:
        row = conn.execute("SELECT * FROM bookings WHERE booking_no = ?", (booking_no,)).fetchone()
    if row is None:
        _fail(404, "NOT_FOUND", f"Booking {booking_no or '(empty)'} not found.")

    request = get_request_row(conn, row["request_id"])
    flight = catalog.flights.get(row["flight_id"], {})
    hotel = catalog.hotels.get(request["hotel_id"], {})
    company = catalog.companies.get(row["company_id"], {})
    vehicle = catalog.vehicles.get(row["vehicle_id"], {})
    child_ages = json.loads(request["child_ages"])
    return {
        "booking_no": row["booking_no"],
        "status": row["status"],
        "created_at": row["created_at"],
        "request_id": row["request_id"],
        "traveler_name": request["traveler_name"],
        "flight": {k: flight.get(k) for k in
                   ("flight_id", "airline", "flight_number", "from", "to", "arrival_local")},
        "hotel": {k: hotel.get(k) for k in ("hotel_id", "name", "city", "area")},
        "pickup": row["pickup"],
        "adults": request["adults"],
        "child_ages": child_ages,
        "passengers": request["adults"] + len(child_ages),
        "large_bags": request["large_bags"],
        "small_bags": request["small_bags"],
        "supplier": {"company_id": row["company_id"], "name": company.get("name"), "rating": company.get("rating")},
        "vehicle": {k: vehicle.get(k) for k in ("vehicle_id", "type", "seats", "large_bags", "small_bags")},
        "price_inr": row["price_inr"],
        "shared": _shared_info(conn, catalog, row["share_group"], row["request_id"]),
        "changes": [change_view(conn, catalog, c) for c in conn.execute(
            "SELECT * FROM change_requests WHERE booking_no = ? ORDER BY change_id DESC", (row["booking_no"],))],
    }


# ---------------------------------------------------------------------------
# Change requests (M7, R9): the traveler asks for a new flight or pickup, the supplier decides
# ---------------------------------------------------------------------------

def _get_booking_row(conn: sqlite3.Connection, booking_no: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM bookings WHERE booking_no = ?", ((booking_no or "").strip(),)).fetchone()
    if row is None:
        _fail(404, "NOT_FOUND", f"Booking {booking_no} not found.")
    return row


def _get_change_row(conn: sqlite3.Connection, change_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM change_requests WHERE change_id = ?", (change_id,)).fetchone()
    if row is None:
        _fail(404, "NOT_FOUND", f"Change request {change_id} not found.")
    return row


def _plan(conn, catalog, booking, change) -> tuple[list[Violation], rules.ChangePlan | None]:
    hotel_id = get_request_row(conn, booking["request_id"])["hotel_id"]
    return rules.plan_change(booking["flight_id"], hotel_id, change["new_flight_id"], change["new_pickup"], catalog)


def check_change(conn: sqlite3.Connection, catalog: Catalog, booking: sqlite3.Row,
                 change: sqlite3.Row) -> tuple[list[Violation], rules.ChangePlan | None]:
    """R9: the new pickup follows R2, and the SAME car is free at the new time.
    The car's own current booking is left out (it moves); other bookings and other travelers'
    guarantee holds count."""
    errors, plan = _plan(conn, catalog, booking, change)
    if errors:
        return errors, None
    busy = busy_times_by_vehicle(conn, catalog, exclude_booking=booking["booking_no"])
    clash = rules.find_conflict(plan.busy_start, plan.busy_end, busy.get(booking["vehicle_id"], []))
    if clash:
        why = "held for another traveler" if clash.request_id else f"busy ({clash.source})"
        return [Violation("R6", f"Car {booking['vehicle_id']} is not free at the new time: it is {why} "
                                f"between {rules.human_dt(clash.start)} and {clash.end.strftime('%H:%M')}. "
                                f"The new ride needs it {rules.human_dt(plan.busy_start)} – "
                                f"{plan.busy_end.strftime('%H:%M')}.", None)], None
    return [], plan


def change_view(conn: sqlite3.Connection, catalog: Catalog, change: sqlite3.Row, with_check: bool = False) -> dict:
    booking = _get_booking_row(conn, change["booking_no"])
    view = {
        "change_id": change["change_id"],
        "booking_no": change["booking_no"],
        "status": change["status"],
        "new_flight_id": change["new_flight_id"],
        "new_pickup": change["new_pickup"],
        "reason": change["reason"],
        "created_at": change["created_at"],
        "decided_at": change["decided_at"],
        "old_flight_id": change["old_flight_id"],
        "old_pickup": change["old_pickup"],
    }
    flight = catalog.flights.get(change["new_flight_id"] or "", {})
    view["new_flight"] = {k: flight.get(k) for k in ("flight_id", "flight_number", "from", "to", "arrival_local")} \
        if flight else None
    _, plan = _plan(conn, catalog, booking, change)
    view["resulting_pickup"] = rules.fmt_dt(plan.pickup) if plan else None
    if with_check and change["status"] == "WAITING":
        errors, _ = check_change(conn, catalog, booking, change)
        view["can_accept"] = not errors
        view["problems"] = [e.to_dict() for e in errors]
    return view


def create_change(conn: sqlite3.Connection, catalog: Catalog, booking_no: str, payload: dict) -> dict:
    """The traveler asks for a change. A clearly invalid one (R2, wrong airport) is refused at once."""
    booking = _get_booking_row(conn, booking_no)
    if booking["status"] != "CONFIRMED":
        _fail(409, "R9", "Only a confirmed booking can be changed.")
    if conn.execute("SELECT 1 FROM change_requests WHERE booking_no = ? AND status = 'WAITING'",
                    (booking["booking_no"],)).fetchone():
        _fail(409, "R9", "You already have a change request waiting for the taxi company. "
                         "Wait for their answer before sending another.")
    new_flight_id = (payload.get("new_flight_id") or "").strip() or None
    new_pickup = (payload.get("new_pickup") or "").strip() or None
    probe = {"new_flight_id": new_flight_id, "new_pickup": new_pickup}
    errors, plan = _plan(conn, catalog, booking, probe)
    if errors:
        raise ApiError(422, errors)
    if plan.trip.flight["flight_id"] == booking["flight_id"] and rules.fmt_dt(plan.pickup) == booking["pickup"]:
        _fail(422, "INPUT", "That is the same flight and pickup as your booking.")
    cur = conn.execute(
        """INSERT INTO change_requests (booking_no, new_flight_id, new_pickup, old_flight_id, old_pickup,
                                        status, created_at) VALUES (?,?,?,?,?, 'WAITING', ?)""",
        (booking["booking_no"], new_flight_id, new_pickup, booking["flight_id"], booking["pickup"], now_iso()))
    conn.commit()
    return change_view(conn, catalog, _get_change_row(conn, cur.lastrowid))


def accept_change(conn: sqlite3.Connection, catalog: Catalog, change_id: int, company_id: str) -> dict:
    """R9: accepted only if the new pickup follows R2 and the same car is free at the new time."""
    change = _get_change_row(conn, change_id)
    booking = _get_booking_row(conn, change["booking_no"])
    if company_id != booking["company_id"]:
        _fail(403, "R9", "Only the taxi company of this booking can decide on its change requests.")
    if change["status"] != "WAITING":
        _fail(409, "R9", f"This change request is already {change['status'].lower()}.")

    conn.commit()
    conn.execute("BEGIN IMMEDIATE")   # same lock as booking: no other booking can slip in meanwhile
    try:
        errors, plan = check_change(conn, catalog, booking, change)
        if errors:
            raise ApiError(409, errors)
        new_flight_id = plan.trip.flight["flight_id"]
        pickup, start, end = rules.fmt_dt(plan.pickup), rules.fmt_dt(plan.busy_start), rules.fmt_dt(plan.busy_end)
        # After a change the car no longer carries the other family at the same time: not shared any more.
        conn.execute("UPDATE bookings SET flight_id = ?, pickup = ?, busy_start = ?, busy_end = ?, share_group = NULL "
                     "WHERE booking_no = ?",
                     (new_flight_id, pickup, start, end, booking["booking_no"]))
        conn.execute("UPDATE ride_requests SET flight_id = ?, pickup = ? WHERE request_id = ?",
                     (new_flight_id, pickup, booking["request_id"]))
        conn.execute("UPDATE change_requests SET status = 'ACCEPTED', decided_at = ? WHERE change_id = ?",
                     (now_iso(), change_id))
        moved = RideContext(trip=plan.trip, pickup=plan.pickup, busy_start=plan.busy_start, busy_end=plan.busy_end,
                            adults=0, child_ages=[], passengers=0, large_bags=0, small_bags=0, car_type=None,
                            price_inr=0)
        _close_offers_for_taken_car(conn, catalog, booking["vehicle_id"], moved, booking["request_id"])
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return change_view(conn, catalog, _get_change_row(conn, change_id))


def reject_change(conn: sqlite3.Connection, catalog: Catalog, change_id: int, company_id: str,
                  reason: str | None = None) -> dict:
    """The supplier says no. The booking keeps its old flight and pickup."""
    change = _get_change_row(conn, change_id)
    booking = _get_booking_row(conn, change["booking_no"])
    if company_id != booking["company_id"]:
        _fail(403, "R9", "Only the taxi company of this booking can decide on its change requests.")
    if change["status"] != "WAITING":
        _fail(409, "R9", f"This change request is already {change['status'].lower()}.")
    conn.execute("UPDATE change_requests SET status = 'REJECTED', reason = ?, decided_at = ? WHERE change_id = ?",
                 ((reason or "").strip() or "The taxi company could not make this change.", now_iso(), change_id))
    conn.commit()
    return change_view(conn, catalog, _get_change_row(conn, change_id))


# ---------------------------------------------------------------------------
# Cancel a booking: the traveler cancels, the car is free again
# ---------------------------------------------------------------------------

def cancel_booking(conn: sqlite3.Connection, catalog: Catalog, booking_no: str) -> dict:
    """The traveler cancels a confirmed booking.

    The car is free again at once (busy times only count CONFIRMED bookings), the ride and its
    taxi become CANCELLED, a waiting change request is closed, and other travelers' offers of
    that car that were "Car taken" because of this booking become bookable again.
    """
    booking = _get_booking_row(conn, booking_no)
    if booking["status"] != "CONFIRMED":
        _fail(409, "CANCEL", "This booking is already cancelled.")
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        when = now_iso()
        conn.execute("UPDATE bookings SET status = 'CANCELLED' WHERE booking_no = ?", (booking["booking_no"],))
        conn.execute("UPDATE ride_requests SET status = 'CANCELLED' WHERE request_id = ?", (booking["request_id"],))
        conn.execute("UPDATE offers SET status = 'CANCELLED' WHERE offer_id = ?", (booking["offer_id"],))
        conn.execute("""UPDATE change_requests SET status = 'REJECTED', reason = 'The booking was cancelled',
                        decided_at = ? WHERE booking_no = ? AND status = 'WAITING'""", (when, booking["booking_no"]))
        _reopen_offers_for_freed_car(conn, catalog, booking["vehicle_id"])
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return booking_summary(conn, catalog, booking["booking_no"])


def _reopen_offers_for_freed_car(conn: sqlite3.Connection, catalog: Catalog, vehicle_id: str) -> None:
    """After a cancellation: a "Car taken" offer whose car is now free for its time is open again
    (without a guarantee hold: the traveler can book it if it is still free when they do)."""
    busy = busy_times_by_vehicle(conn, catalog)
    rows = conn.execute(
        """SELECT o.offer_id, o.share_group, o.shared_pickup, r.* FROM offers o JOIN ride_requests r USING (request_id)
           WHERE o.vehicle_id = ? AND o.status = 'CAR_TAKEN' AND r.status = 'OPEN'""", (vehicle_id,)).fetchall()
    for row in rows:
        _, ctx = context_for_row(row, catalog)
        ctx = shared_ctx(ctx, row["shared_pickup"]) if ctx else None
        own = for_request(busy, row["request_id"], row["share_group"]).get(vehicle_id, [])
        if ctx and not rules.find_conflict(ctx.busy_start, ctx.busy_end, own):
            conn.execute("UPDATE offers SET status = 'OPEN', hold_until = NULL WHERE offer_id = ?", (row["offer_id"],))


def supplier_changes(conn: sqlite3.Connection, catalog: Catalog, company_id: str) -> list[dict]:
    """Change requests for this supplier's bookings, waiting ones first, each with the R9 check."""
    get_company(catalog, company_id)
    rows = conn.execute(
        """SELECT c.* FROM change_requests c JOIN bookings b USING (booking_no) WHERE b.company_id = ?
           ORDER BY c.status != 'WAITING', c.change_id DESC""", (company_id,)).fetchall()
    out = []
    for c in rows:
        view = change_view(conn, catalog, c, with_check=True)
        b = _get_booking_row(conn, c["booking_no"])
        r = get_request_row(conn, b["request_id"])
        view["traveler_name"] = r["traveler_name"]
        view["vehicle_id"] = b["vehicle_id"]
        view["hotel_name"] = catalog.hotels.get(r["hotel_id"], {}).get("name")
        out.append(view)
    return out


# ---------------------------------------------------------------------------
# Suppliers (M2, M3)
# ---------------------------------------------------------------------------

def get_company(catalog: Catalog, company_id: str) -> dict:
    company = catalog.companies.get(company_id)
    if company is None:
        _fail(404, "NOT_FOUND", f"Supplier {company_id or '(empty)'} not found.")
    return company


def supplier_summary(company: dict) -> dict:
    return {
        "company_id": company["company_id"], "name": company["name"], "airports": company["airports"],
        "areas": company["areas"], "service_from": company["service_from"],
        "service_until": company["service_until"], "rating": company.get("rating"),
        "vehicles": company["vehicles"],
    }


def supplier_dashboard(conn: sqlite3.Connection, catalog: Catalog, company_id: str) -> dict:
    """M2: only the OPEN requests this supplier can serve (R4), with its cars and its own offers."""
    company = get_company(catalog, company_id)
    busy = busy_times_by_vehicle(conn, catalog)
    rows = conn.execute(
        "SELECT * FROM ride_requests WHERE status = 'OPEN' ORDER BY pickup, request_id").fetchall()
    valid = [(row, ctx) for row in rows for _, ctx in [context_for_row(row, catalog)] if ctx]
    visible = []
    for row, ctx in valid:
        own = for_request(busy, row["request_id"])
        ev = rules.evaluate_supplier(company, ctx, own)
        if ev.can_serve:
            mine = conn.execute(
                "SELECT * FROM offers WHERE request_id = ? AND company_id = ? ORDER BY offer_id",
                (row["request_id"], company_id)).fetchall()
            visible.append({
                **request_view(row, catalog, ctx, audience="supplier"),
                "vehicles": [v.to_dict() for v in ev.vehicles],
                "my_offers": [offer_view(conn, catalog, o, ctx, busy, audience="supplier") for o in mine],
                "share_with": _share_candidates(company, row, ctx, valid, busy, catalog),
            })
    return {"company": supplier_summary(company), "requests": visible}


def _share_candidates(company: dict, row: sqlite3.Row, ctx: RideContext, valid: list, busy: dict,
                      catalog: Catalog) -> list[dict]:
    """S1: other open requests this request can share a car with, and which of my cars fit everyone."""
    out = []
    for other_row, other_ctx in valid:
        if other_row["request_id"] == row["request_id"]:
            continue
        errors, together = rules.plan_shared_ride(ctx, other_ctx)
        if errors:
            continue
        both = for_request(busy, (row["request_id"], other_row["request_id"]))
        ev = rules.evaluate_supplier(company, together, both)
        if not ev.can_serve:
            continue   # none of my cars fits both families, or none is free
        hotel = catalog.hotels.get(other_row["hotel_id"], {})
        out.append({
            "request_id": other_row["request_id"], "traveler_name": other_row["traveler_name"],
            "hotel_name": hotel.get("name"), "pickup": other_row["pickup"], "price_inr": other_row["price_inr"],
            "passengers": other_ctx.passengers, "large_bags": other_ctx.large_bags,
            "small_bags": other_ctx.small_bags, "car_type": other_ctx.car_type,
            "shared_pickup": rules.fmt_dt(together.pickup),
            "total_passengers": together.passengers, "total_large_bags": together.large_bags,
            "total_small_bags": together.small_bags,
            "busy_window": {"start": rules.fmt_dt(together.busy_start), "end": rules.fmt_dt(together.busy_end)},
            "vehicles": [v.to_dict() for v in ev.vehicles],
        })
    return out


def supplier_offers(conn: sqlite3.Connection, catalog: Catalog, company_id: str) -> list[dict]:
    """Every taxi this supplier assigned, newest first, with the request and booking (if any)."""
    get_company(catalog, company_id)
    rows = conn.execute("SELECT * FROM offers WHERE company_id = ? ORDER BY offer_id DESC",
                        (company_id,)).fetchall()
    out = []
    for o in rows:
        req = conn.execute("SELECT * FROM ride_requests WHERE request_id = ?", (o["request_id"],)).fetchone()
        view = offer_view(conn, catalog, o, audience="supplier")
        hotel = catalog.hotels.get(req["hotel_id"], {}) if req else {}
        view["request"] = {
            "traveler_name": req["traveler_name"] if req else None,
            "flight_id": req["flight_id"] if req else None,
            "hotel_name": hotel.get("name"),
            "pickup": req["pickup"] if req else None,
        }
        out.append(view)
    return out
