"""The business rules R1–R7, as small pure functions.

No database and no HTTP here: every function takes plain data and returns a result.
All endpoints call these functions, so each rule is written exactly once.

All times are local times of the arrival airport (no time zone conversion needed).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, time, timedelta

CAR_TYPES = ("HATCHBACK", "SEDAN", "SUV", "BUS")
MIN_MINUTES_AFTER_LANDING = 60   # R2
MAX_CHILD_AGE = 17               # R1
SHARE_MAX_WAIT_MINUTES = 60      # S1: two pickups this close can share one car


# ---------------------------------------------------------------------------
# Small data types
# ---------------------------------------------------------------------------

@dataclass
class Violation:
    """One broken rule. `rule` is R1..R9 or INPUT (bad value), `field` is the form field."""
    rule: str
    message: str
    field: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BusyTime:
    """A time when a car is busy. `source` says why: a ride_id, a booking, or a guarantee hold.

    `request_id` is set only for a hold: a guaranteed offer keeps the car for that one request,
    so the hold blocks every OTHER request but never the request it was made for.
    `share_group` is set for a shared ride (S1), and `riders` are the requests that still have an open
    offer in that shared car: the families of one shared car do not block each other.
    """
    start: datetime
    end: datetime
    source: str
    request_id: str | None = None
    share_group: str | None = None
    riders: frozenset = frozenset()


@dataclass
class Trip:
    """A flight + hotel pair that passed R1, with its route (R3, R6)."""
    flight: dict
    hotel: dict
    airport: dict
    route: dict
    arrival: datetime
    earliest_pickup: datetime


@dataclass
class RideContext:
    """A fully valid ride request: everything the supplier checks need."""
    trip: Trip
    pickup: datetime
    busy_start: datetime
    busy_end: datetime
    adults: int
    child_ages: list[int]
    passengers: int
    large_bags: int
    small_bags: int
    car_type: str | None
    price_inr: int

    @property
    def airport_code(self) -> str:
        return self.trip.flight["to"]

    @property
    def city(self) -> str:
        return self.trip.hotel["city"]

    @property
    def area(self) -> str:
        return self.trip.hotel["area"]


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def parse_datetime(value: str) -> datetime:
    """Accepts YYYY-MM-DDTHH:MM or YYYY-MM-DDTHH:MM:SS (local time, no offset)."""
    return datetime.fromisoformat(value.strip())


def fmt_dt(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M")


def human_dt(value: datetime) -> str:
    return value.strftime("%d %b %Y, %H:%M")


def parse_clock(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def is_open_at(service_from: str, service_until: str, at: datetime) -> bool:
    """R4 opening hours. Both ends included. A window like 05:00–01:00 runs past midnight."""
    start, end = parse_clock(service_from), parse_clock(service_until)
    t = at.time().replace(second=0, microsecond=0)
    if start <= end:
        return start <= t <= end
    return t >= start or t <= end


def busy_window(pickup: datetime, drive_minutes: int) -> tuple[datetime, datetime]:
    """R6: busy from pickup until pickup + 2 x drive time (to the hotel and back)."""
    return pickup, pickup + timedelta(minutes=2 * drive_minutes)


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """R6: one starts before the other ends. 11:00–14:00 and 14:00–16:00 do NOT overlap."""
    return a_start < b_end and b_start < a_end


def find_conflict(start: datetime, end: datetime, busy: list[BusyTime]) -> BusyTime | None:
    for b in busy:
        if overlaps(start, end, b.start, b.end):
            return b
    return None


def inr(amount: int) -> str:
    return f"₹{amount:,}"


# ---------------------------------------------------------------------------
# R1 + route lookup (R3): flight and hotel
# ---------------------------------------------------------------------------

def resolve_trip(flight_id: str | None, hotel_id: str | None, catalog) -> tuple[list[Violation], Trip | None]:
    errors: list[Violation] = []
    flight = catalog.flights.get(flight_id) if flight_id else None
    hotel = catalog.hotels.get(hotel_id) if hotel_id else None

    if not flight_id:
        errors.append(Violation("R1", "Choose your arrival flight.", "flight_id"))
    elif not flight:
        errors.append(Violation("R1", f"Flight '{flight_id}' is not in the catalog.", "flight_id"))
    if not hotel_id:
        errors.append(Violation("R1", "Choose your hotel.", "hotel_id"))
    elif not hotel:
        errors.append(Violation("R1", f"Hotel '{hotel_id}' is not in the catalog.", "hotel_id"))
    if errors:
        return errors, None

    code = flight["to"]
    airport = catalog.airports.get(code) or {"code": code, "name": code}
    serves = airport.get("serves_cities") or []
    if not serves:
        return [Violation(
            "R1",
            f"Flight {flight_id} lands at {code}, where there is no taxi service. "
            f"Choose a flight that lands at {', '.join(catalog.arrival_airports)}.",
            "flight_id",
        )], None
    if hotel["city"] not in serves:
        return [Violation(
            "R1",
            f"Flight {flight_id} lands at {code} ({airport['name']}), which serves "
            f"{', '.join(serves)}, not {hotel['city']} where {hotel['name']} is.",
            "hotel_id",
        )], None

    route = catalog.routes.get((code, hotel["city"], hotel["area"]))
    if not route:
        return [Violation("R3", f"No route from {code} to {hotel['city']} / {hotel['area']}.", "hotel_id")], None

    arrival = parse_datetime(flight["arrival_local"])
    return [], Trip(
        flight=flight, hotel=hotel, airport=airport, route=route, arrival=arrival,
        earliest_pickup=arrival + timedelta(minutes=MIN_MINUTES_AFTER_LANDING),
    )


# ---------------------------------------------------------------------------
# M1: validate a whole ride request (R1, R2, R3 + input checks)
# ---------------------------------------------------------------------------

def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def check_price_in_range(price: int, route: dict, field: str = "price_inr") -> Violation | None:
    """R3 (also used by R7). Both ends of the range are allowed."""
    lo, hi = route["price_min_inr"], route["price_max_inr"]
    if price < lo or price > hi:
        return Violation(
            "R3",
            f"Price {inr(price)} is outside the suggested range {inr(lo)} – {inr(hi)} "
            f"for {route['airport']} → {route['city']} / {route['area']}.",
            field,
        )
    return None


def validate_request(p: dict, catalog) -> tuple[list[Violation], RideContext | None]:
    """Returns (errors, context). Context is None when there is any error."""
    errors: list[Violation] = []

    adults = p.get("adults")
    if not _is_int(adults) or adults < 1:
        errors.append(Violation("R1", "At least 1 adult is needed.", "adults"))

    child_ages = p.get("child_ages") or []
    for i, age in enumerate(child_ages, start=1):
        if not _is_int(age) or age < 0 or age > MAX_CHILD_AGE:
            errors.append(Violation(
                "R1", f"Child {i}: age {age} is not valid. A child is 0 to {MAX_CHILD_AGE} years old "
                      f"(18 or older counts as an adult).", "child_ages"))

    for bag_field, label in (("large_bags", "Large bags"), ("small_bags", "Small bags")):
        value = p.get(bag_field, 0)
        if not _is_int(value) or value < 0:
            errors.append(Violation("INPUT", f"{label} must be 0 or more.", bag_field))

    car_type = p.get("car_type") or None
    if car_type is not None and car_type not in CAR_TYPES:
        errors.append(Violation("INPUT", f"Car type must be one of {', '.join(CAR_TYPES)}, or any.", "car_type"))

    price = p.get("price_inr")
    price_ok = _is_int(price) and price > 0
    if price is None:
        errors.append(Violation("INPUT", "Enter your price in INR.", "price_inr"))
    elif not price_ok:
        errors.append(Violation("INPUT", "Price must be a whole number of rupees above 0.", "price_inr"))

    trip_errors, trip = resolve_trip(p.get("flight_id"), p.get("hotel_id"), catalog)
    errors.extend(trip_errors)

    pickup = None
    if trip:
        raw_pickup = p.get("pickup")
        if raw_pickup:
            try:
                pickup = parse_datetime(raw_pickup)
            except (ValueError, TypeError):
                errors.append(Violation("INPUT", "Pickup time must look like 2027-04-10T11:30.", "pickup"))
            else:
                if pickup < trip.earliest_pickup:
                    errors.append(Violation(
                        "R2",
                        f"Pickup {human_dt(pickup)} is too early. The flight lands at {human_dt(trip.arrival)}, "
                        f"so the earliest pickup is {human_dt(trip.earliest_pickup)} "
                        f"({MIN_MINUTES_AFTER_LANDING} minutes after landing).",
                        "pickup",
                    ))
        else:
            pickup = trip.earliest_pickup  # no pickup given -> earliest pickup

        if price_ok:
            price_error = check_price_in_range(price, trip.route)
            if price_error:
                errors.append(price_error)

    if errors:
        return errors, None

    pickup = pickup.replace(second=0, microsecond=0)
    start, end = busy_window(pickup, trip.route["drive_minutes"])
    return [], RideContext(
        trip=trip, pickup=pickup, busy_start=start, busy_end=end,
        adults=adults, child_ages=list(child_ages), passengers=adults + len(child_ages),
        large_bags=p.get("large_bags", 0), small_bags=p.get("small_bags", 0),
        car_type=car_type, price_inr=price,
    )


# ---------------------------------------------------------------------------
# R5 car fits, R6 car free, R4 which suppliers see a request
# ---------------------------------------------------------------------------

def car_fit_problems(vehicle: dict, ctx: RideContext) -> list[str]:
    """R5 (+ G2 car type). Empty list = the car fits. Bag sizes are checked separately."""
    problems = []
    if ctx.car_type and vehicle["type"] != ctx.car_type:
        problems.append(f"it is a {vehicle['type']}, the traveler asked for a {ctx.car_type}")
    if vehicle["seats"] < ctx.passengers:
        problems.append(f"{vehicle['seats']} seats for {ctx.passengers} passengers")
    if vehicle["large_bags"] < ctx.large_bags:
        problems.append(f"room for {vehicle['large_bags']} large bags, needs {ctx.large_bags}")
    if vehicle["small_bags"] < ctx.small_bags:
        problems.append(f"room for {vehicle['small_bags']} small bags, needs {ctx.small_bags}")
    return problems


@dataclass
class VehicleCheck:
    vehicle_id: str
    type: str
    seats: int
    large_bags: int
    small_bags: int
    fit_problems: list[str]
    conflict: str | None  # description of the overlapping busy time, if any

    @property
    def fits(self) -> bool:
        return not self.fit_problems

    @property
    def free(self) -> bool:
        return self.conflict is None

    @property
    def usable(self) -> bool:
        return self.fits and self.free

    @property
    def availability(self) -> dict:
        """The car's state in plain words, for the supplier's screen."""
        if not self.fits:
            return {"state": "DOES_NOT_FIT", "label": "Does not fit"}
        if not self.free:
            held = self.conflict and "held for another traveler" in self.conflict
            return {"state": "BUSY", "label": "Held for another traveler" if held else "Busy at this time"}
        return {"state": "AVAILABLE", "label": "Available"}

    def to_dict(self) -> dict:
        return {**asdict(self), "fits": self.fits, "free": self.free, "usable": self.usable,
                "availability": self.availability}


def check_vehicle(vehicle: dict, ctx: RideContext, busy: list[BusyTime]) -> VehicleCheck:
    clash = find_conflict(ctx.busy_start, ctx.busy_end, busy)
    conflict = None
    if clash:
        conflict = (f"busy {human_dt(clash.start)} – {clash.end.strftime('%H:%M')} ({clash.source}), "
                    f"this ride needs it {human_dt(ctx.busy_start)} – {ctx.busy_end.strftime('%H:%M')}")
    return VehicleCheck(
        vehicle_id=vehicle["vehicle_id"], type=vehicle["type"], seats=vehicle["seats"],
        large_bags=vehicle["large_bags"], small_bags=vehicle["small_bags"],
        fit_problems=car_fit_problems(vehicle, ctx), conflict=conflict,
    )


# How far a supplier got in the R4 checks, in order. Used to explain "no ride" to the traveler.
STAGES = ("airport", "area", "hours", "fit", "busy")


@dataclass
class SupplierEvaluation:
    company_id: str
    name: str
    can_serve: bool
    rule: str | None = None      # first broken rule (R4/R5/R6) when it cannot serve
    reason: str | None = None
    stage: str | None = None     # which check failed: one of STAGES
    vehicles: list[VehicleCheck] = field(default_factory=list)

    def to_dict(self, with_vehicles: bool = False) -> dict:
        d = {"company_id": self.company_id, "name": self.name, "can_serve": self.can_serve,
             "rule": self.rule, "reason": self.reason}
        if with_vehicles:
            d["vehicles"] = [v.to_dict() for v in self.vehicles]
        return d


def serves_area(company: dict, city: str, area: str) -> bool:
    return any(a["city"] == city and a["area"] == area for a in company["areas"])


def evaluate_supplier(company: dict, ctx: RideContext,
                      busy_by_vehicle: dict[str, list[BusyTime]]) -> SupplierEvaluation:
    """R4: works at the airport, drives to the city/area, open at pickup, has a car that fits (R5) and is free (R6)."""
    ev = SupplierEvaluation(company_id=company["company_id"], name=company["name"], can_serve=False)
    ev.vehicles = [check_vehicle(v, ctx, busy_by_vehicle.get(v["vehicle_id"], [])) for v in company["vehicles"]]

    if ctx.airport_code not in company["airports"]:
        ev.stage, ev.rule, ev.reason = "airport", "R4", f"does not work at {ctx.airport_code}"
    elif not serves_area(company, ctx.city, ctx.area):
        ev.stage, ev.rule, ev.reason = "area", "R4", f"does not drive to {ctx.city} / {ctx.area}"
    elif not is_open_at(company["service_from"], company["service_until"], ctx.pickup):
        ev.stage, ev.rule, ev.reason = "hours", "R4", (
            f"closed at {ctx.pickup.strftime('%H:%M')} (open {company['service_from']}–{company['service_until']})")
    elif not any(v.fits for v in ev.vehicles):
        need = f"{ctx.passengers} seats, {ctx.large_bags} large + {ctx.small_bags} small bags"
        if ctx.car_type:
            need += f", type {ctx.car_type}"
        ev.stage, ev.rule, ev.reason = "fit", "R5", f"no car fits ({need})"
    elif not any(v.usable for v in ev.vehicles):
        ev.stage, ev.rule, ev.reason = "busy", "R6", (
            f"every car that fits is busy between {human_dt(ctx.busy_start)} and {ctx.busy_end.strftime('%H:%M')}")
    else:
        ev.can_serve = True
    return ev


NO_RIDE_MESSAGE = "No ride is available for your request."


def traveler_availability(evaluations: list[SupplierEvaluation], ctx: RideContext) -> dict:
    """What the TRAVELER sees (M2): a simple yes/no, plus one plain reason when no ride is available.

    No supplier names or rule codes. The reason comes from the supplier that got furthest
    through the checks, because that is the closest the request came to being served.
    """
    if any(e.can_serve for e in evaluations):
        return {"available": True, "message": "Taxi companies can now offer you a car.", "reason": None}

    reached = [STAGES.index(e.stage) for e in evaluations if e.stage in STAGES]
    stage = STAGES[max(reached)] if reached else "airport"
    car = f" ({ctx.car_type.title()})" if ctx.car_type else ""
    reasons = {
        "airport": f"No taxi company picks up at {ctx.airport_code}.",
        "area": f"No taxi company from {ctx.airport_code} drives to {ctx.city} / {ctx.area}.",
        "hours": f"No taxi company for this route works at {ctx.pickup.strftime('%H:%M')}.",
        "fit": (f"No car{car} has room for {ctx.passengers} passengers with "
                f"{ctx.large_bags} large and {ctx.small_bags} small bags."),
        "busy": (f"Every car that fits is already booked between {ctx.busy_start.strftime('%H:%M')} "
                 f"and {ctx.busy_end.strftime('%H:%M')}."),
    }
    return {"available": False, "message": NO_RIDE_MESSAGE, "reason": reasons[stage]}


# ---------------------------------------------------------------------------
# R7: a supplier assigns a car with a price (used in part 2)
# ---------------------------------------------------------------------------

def check_assignment(company: dict, vehicle_id: str, price, ctx: RideContext,
                     busy_by_vehicle: dict[str, list[BusyTime]]) -> list[Violation]:
    """Refuses a car that breaks R4, R5, R6, or a price outside the range, and says which rule."""
    errors: list[Violation] = []
    vehicle = next((v for v in company["vehicles"] if v["vehicle_id"] == vehicle_id), None)
    if vehicle is None:
        return [Violation("R7", f"Car {vehicle_id} does not belong to {company['name']}.", "vehicle_id")]

    ev = evaluate_supplier(company, ctx, busy_by_vehicle)
    if ev.rule == "R4":
        errors.append(Violation("R4", f"{company['name']} {ev.reason}.", "vehicle_id"))

    check = check_vehicle(vehicle, ctx, busy_by_vehicle.get(vehicle_id, []))
    if check.fit_problems:
        errors.append(Violation("R5", f"Car {vehicle_id} does not fit: {'; '.join(check.fit_problems)}.", "vehicle_id"))
    if check.conflict:
        errors.append(Violation("R6", f"Car {vehicle_id} is not free: {check.conflict}.", "vehicle_id"))

    if not _is_int(price) or price <= 0:
        errors.append(Violation("INPUT", "Price must be a whole number of rupees above 0.", "price_inr"))
    else:
        price_error = check_price_in_range(price, ctx.trip.route)
        if price_error:
            errors.append(price_error)
    return errors


# ---------------------------------------------------------------------------
# R9: change request (new flight or new pickup) for a booking
# ---------------------------------------------------------------------------

@dataclass
class ChangePlan:
    """What a booking would become if a change were accepted."""
    trip: Trip
    pickup: datetime
    busy_start: datetime
    busy_end: datetime


def plan_change(current_flight_id: str, hotel_id: str, new_flight_id: str | None,
                new_pickup: str | None, catalog) -> tuple[list[Violation], ChangePlan | None]:
    """R9 part 1: the new flight and pickup are valid and the pickup follows R2.

    The new flight must land at the SAME airport as the booking: the supplier, its car and the
    price were agreed for that airport (a different airport is a new ride request).
    Part 2, "the same car is free at the new time", needs the bookings, so services.py checks it.
    """
    if not new_flight_id and not new_pickup:
        return [Violation("INPUT", "Choose a new flight or a new pickup time.", None)], None

    flight_id = new_flight_id or current_flight_id
    errors, trip = resolve_trip(flight_id, hotel_id, catalog)
    if errors:
        return [Violation("R9", e.message, "new_flight_id") for e in errors], None
    old_airport = catalog.flights.get(current_flight_id, {}).get("to")
    if trip.flight["to"] != old_airport:
        return [Violation("R9", f"The new flight lands at {trip.flight['to']}, but this taxi picks up at "
                                f"{old_airport}. Choose a flight to {old_airport}, or post a new ride request.",
                          "new_flight_id")], None

    if new_pickup:
        try:
            pickup = parse_datetime(new_pickup)
        except (ValueError, TypeError):
            return [Violation("INPUT", "Pickup time must look like 2027-04-10T11:30.", "new_pickup")], None
    else:
        pickup = trip.earliest_pickup   # new flight, no time given: earliest pickup
    pickup = pickup.replace(second=0, microsecond=0)

    if pickup < trip.earliest_pickup:
        return [Violation(
            "R2", f"Pickup {human_dt(pickup)} is too early. Flight {trip.flight['flight_id']} lands at "
                  f"{human_dt(trip.arrival)}, so the earliest pickup is {human_dt(trip.earliest_pickup)}.",
            "new_pickup")], None
    start, end = busy_window(pickup, trip.route["drive_minutes"])
    return [], ChangePlan(trip=trip, pickup=pickup, busy_start=start, busy_end=end)


# ---------------------------------------------------------------------------
# S1: shared ride. Two requests on the same flight to the same area share one car.
# ---------------------------------------------------------------------------

def at_pickup(ctx: RideContext, pickup: datetime) -> RideContext:
    """The same ride with another pickup time (and so another busy time, R6)."""
    start, end = busy_window(pickup, ctx.trip.route["drive_minutes"])
    return replace(ctx, pickup=pickup, busy_start=start, busy_end=end)


def plan_shared_ride(a: RideContext, b: RideContext) -> tuple[list[Violation], RideContext | None]:
    """Can two requests share one car? Returns the combined ride the car must carry.

    Same flight, same city and area (so the same route and drive time), pickups at most
    SHARE_MAX_WAIT_MINUTES apart. The car picks up at the LATER pickup, which still follows R2
    for both. The car must fit everyone together (R5): all passengers, all bags, and the car
    type if a traveler chose one.
    """
    errors = []
    if a.trip.flight["flight_id"] != b.trip.flight["flight_id"]:
        errors.append(Violation("S1", f"The two travelers are on different flights "
                                      f"({a.trip.flight['flight_id']} and {b.trip.flight['flight_id']}).", None))
    if (a.city, a.area) != (b.city, b.area):
        errors.append(Violation("S1", f"The two hotels are in different areas ({a.city} / {a.area} and "
                                      f"{b.city} / {b.area}).", None))
    wait = abs(a.pickup - b.pickup)
    if wait > timedelta(minutes=SHARE_MAX_WAIT_MINUTES):
        errors.append(Violation("S1", f"The pickups are {int(wait.total_seconds() // 60)} minutes apart "
                                      f"(at most {SHARE_MAX_WAIT_MINUTES} minutes to share).", None))
    if a.car_type and b.car_type and a.car_type != b.car_type:
        errors.append(Violation("S1", f"The travelers asked for different car types ({a.car_type} and "
                                      f"{b.car_type}).", None))
    if errors:
        return errors, None
    together = replace(
        at_pickup(a, max(a.pickup, b.pickup)),
        adults=a.adults + b.adults, child_ages=a.child_ages + b.child_ages, passengers=a.passengers + b.passengers,
        large_bags=a.large_bags + b.large_bags, small_bags=a.small_bags + b.small_bags,
        car_type=a.car_type or b.car_type)
    return [], together
