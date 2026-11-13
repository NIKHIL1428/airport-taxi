"""S1 shared ride: two requests on the same flight to the same area share one car, if it fits everyone.

Sample data (tests/fixtures/data): flight FL-401 lands at Narita 10 Apr 10:30, Ueno is 90 minutes away.
Fuji Vans has one SUV, FV-1 (7 seats, 5 large + 4 small bags). Sakura's SC-2 is busy 11:00-14:00.
The Menon family (3 people, 3 large + 2 small bags) and the Rao couple (2 people, 1 large + 1 small bag)
together need 5 seats and 4 large + 3 small bags: FV-1 fits them.

Run from backend/:  python -m pytest -q tests/test_shared_rides.py
"""
from datetime import datetime
from pathlib import Path

import pytest

from app import rules, services
from app.data_store import Catalog
from app.db import connect, init_db, seed_open_requests

FIXTURES = Path(__file__).parent / "fixtures" / "data"
MENON, RAO, THIRD = "REQ-0003", "REQ-0004", "REQ-0005"   # REQ-0001/0002 come from open_requests.json


@pytest.fixture(scope="module")
def catalog():
    return Catalog.load(FIXTURES)


@pytest.fixture
def conn(tmp_path, catalog):
    c = connect(tmp_path / "test.db")
    init_db(c)
    seed_open_requests(c, catalog.open_requests)
    yield c
    c.close()


def request(name, **overrides):
    p = {"traveler_name": name, "flight_id": "FL-401", "hotel_id": "HTL-TYO-004",
         "adults": 2, "child_ages": [6], "large_bags": 3, "small_bags": 2,
         "pickup": "2027-04-10T11:30", "car_type": None, "price_inr": 12000}
    p.update(overrides)
    return p


def couple(name="Rao couple", **overrides):
    return request(name, **{"child_ages": [], "large_bags": 1, "small_bags": 1, "price_inr": 11000, **overrides})


def post_both(conn, catalog, **couple_overrides):
    services.create_request(conn, catalog, request("Menon family"))       # REQ-0003
    services.create_request(conn, catalog, couple(**couple_overrides))    # REQ-0004


def shared(**overrides):
    p = {"request_ids": [MENON, RAO], "company_id": "TX-JP-02", "vehicle_id": "FV-1",
         "prices": [12500, 11500]}
    p.update(overrides)
    return p


def ctx_of(catalog, payload):
    errors, ctx = rules.validate_request(payload, catalog)
    assert errors == []
    return ctx


def rules_of(exc):
    return {e.rule for e in exc.value.errors}


# --- The rule itself --------------------------------------------------------------------

def test_plan_adds_everyone_and_uses_the_later_pickup(catalog):
    a = ctx_of(catalog, request("A"))
    b = ctx_of(catalog, couple("B", pickup="2027-04-10T12:00"))
    errors, together = rules.plan_shared_ride(a, b)
    assert errors == []
    assert (together.passengers, together.large_bags, together.small_bags) == (5, 4, 3)
    assert together.pickup == datetime(2027, 4, 10, 12, 0)                       # the later pickup
    assert (together.busy_start, together.busy_end) == (datetime(2027, 4, 10, 12, 0), datetime(2027, 4, 10, 15, 0))


@pytest.mark.parametrize("change,why", [
    ({"flight_id": "FL-403", "pickup": "2027-04-10T17:00"}, "different flights"),
    ({"area": "Asakusa"}, "different areas"),
    ({"pickup": "2027-04-10T12:31"}, "61 minutes apart"),
    ({"car_type": "SEDAN"}, "different car types"),
])
def test_plan_refused(catalog, change, why):
    from dataclasses import replace
    a = ctx_of(catalog, request("A", car_type="SUV"))
    area = change.pop("area", None)
    b = ctx_of(catalog, couple("B", **change))
    if area:   # the sample data has one Tokyo hotel: move it to another area for this check
        b = replace(b, trip=replace(b.trip, hotel={**b.trip.hotel, "area": area}))
    errors, together = rules.plan_shared_ride(a, b)
    assert together is None and errors[0].rule == "S1" and why in errors[0].message


def test_one_hour_apart_can_still_share(catalog):
    a = ctx_of(catalog, request("A"))
    b = ctx_of(catalog, couple("B", pickup="2027-04-10T12:30"))
    assert rules.plan_shared_ride(a, b)[0] == []


# --- Supplier dashboard -----------------------------------------------------------------

def test_dashboard_suggests_a_partner_and_the_cars_that_fit_both(conn, catalog):
    post_both(conn, catalog)
    fuji = services.supplier_dashboard(conn, catalog, "TX-JP-02")
    menon = next(r for r in fuji["requests"] if r["request_id"] == MENON)
    [partner] = menon["share_with"]
    assert partner["request_id"] == RAO and partner["traveler_name"] == "Rao couple"
    assert (partner["total_passengers"], partner["total_large_bags"], partner["total_small_bags"]) == (5, 4, 3)
    assert {v["vehicle_id"]: v["availability"]["state"] for v in partner["vehicles"]} == {"FV-1": "AVAILABLE"}


def test_no_partner_when_no_car_fits_both(conn, catalog):
    post_both(conn, catalog, large_bags=3)          # 6 large bags together: FV-1 takes 5
    fuji = services.supplier_dashboard(conn, catalog, "TX-JP-02")
    assert all(r["share_with"] == [] for r in fuji["requests"])


# --- Assigning a shared ride ------------------------------------------------------------

def test_assign_shared_ride(conn, catalog):
    post_both(conn, catalog, pickup="2027-04-10T12:00")
    result = services.create_shared_offer(conn, catalog, shared())
    a, b = result["offers"]
    assert result["pickup"] == "2027-04-10T12:00"
    assert (a["request_id"], a["price_inr"], b["request_id"], b["price_inr"]) == (MENON, 12500, RAO, 11500)
    assert a["shared"]["with_traveler_name"] == "Rao couple"           # the supplier sees who
    traveler_view = services.request_offers(conn, catalog, MENON)[0]["shared"]
    assert traveler_view["other_passengers"] == 2 and traveler_view["pickup"] == "2027-04-10T12:00"
    assert "with_traveler_name" not in traveler_view                    # the traveler does not


def test_assign_shared_refused_with_rules(conn, catalog):
    post_both(conn, catalog, large_bags=3)
    with pytest.raises(services.ApiError) as exc:
        services.create_shared_offer(conn, catalog, shared(prices=[12500, 99000]))
    assert rules_of(exc) == {"R5", "R3"}
    price = next(e for e in exc.value.errors if e.rule == "R3")
    assert price.field == "price_inr_2" and price.message.startswith("Rao couple:")


def test_assign_shared_refused_bad_input(conn, catalog):
    post_both(conn, catalog)
    for bad in (shared(request_ids=[MENON, MENON]), shared(request_ids=[MENON])):
        with pytest.raises(services.ApiError) as exc:
            services.create_shared_offer(conn, catalog, bad)
        assert rules_of(exc) == {"S1"}
    with pytest.raises(services.ApiError) as exc:
        services.create_shared_offer(conn, catalog, shared(company_id="TX-JP-01", vehicle_id="SC-2"))
    assert "R6" in rules_of(exc)                                         # SC-2 busy 11:00-14:00


# --- Booking: both families in one car, nobody else ---------------------------------------

def test_both_families_book_the_same_car(conn, catalog):
    post_both(conn, catalog)
    a, b = services.create_shared_offer(conn, catalog, shared())["offers"]
    first = services.book_offer(conn, catalog, a["offer_id"])
    second = services.book_offer(conn, catalog, b["offer_id"])      # not a double booking: same shared ride
    assert first["vehicle"]["vehicle_id"] == second["vehicle"]["vehicle_id"] == "FV-1"
    assert first["shared"]["other_booked"] is False                    # Rao had not booked yet
    assert second["shared"]["other_booked"] and second["shared"]["total_passengers"] == 5
    # A third family at the same time cannot get FV-1.
    services.create_request(conn, catalog, couple("Third family"))
    with pytest.raises(services.ApiError) as exc:
        services.create_offer(conn, catalog, {"request_id": THIRD, "company_id": "TX-JP-02",
                                              "vehicle_id": "FV-1", "price_inr": 12000})
    assert rules_of(exc) == {"R6"}


def test_shared_hold_blocks_others_but_not_the_partner(conn, catalog):
    post_both(conn, catalog)
    services.create_request(conn, catalog, couple("Third family"))
    a, b = services.create_shared_offer(conn, catalog, shared())["offers"]
    assert a["guaranteed"] and b["guaranteed"]
    with pytest.raises(services.ApiError) as exc:
        services.create_offer(conn, catalog, {"request_id": THIRD, "company_id": "TX-JP-02",
                                              "vehicle_id": "FV-1", "price_inr": 12000})
    assert "held for another traveler" in exc.value.errors[0].message
    assert services.request_offers(conn, catalog, RAO)[0]["warning"] is None


def test_booking_uses_the_shared_pickup(conn, catalog):
    post_both(conn, catalog, pickup="2027-04-10T12:00")
    a, _ = services.create_shared_offer(conn, catalog, shared())["offers"]
    booking = services.book_offer(conn, catalog, a["offer_id"])
    assert booking["pickup"] == "2027-04-10T12:00"                    # Menon asked 11:30, the car comes at 12:00
    assert services.request_detail(conn, catalog, MENON)["pickup"] == "2027-04-10T12:00"


def test_partner_rejects_the_other_family_still_rides(conn, catalog):
    post_both(conn, catalog)
    a, b = services.create_shared_offer(conn, catalog, shared())["offers"]
    services.reject_offer(conn, catalog, b["offer_id"])
    booking = services.book_offer(conn, catalog, a["offer_id"])
    assert booking["vehicle"]["vehicle_id"] == "FV-1" and booking["shared"]["other_booked"] is False


def test_partner_books_another_taxi_shared_offer_becomes_not_chosen(conn, catalog):
    post_both(conn, catalog)
    _, b = services.create_shared_offer(conn, catalog, shared())["offers"]
    own = services.create_offer(conn, catalog, {"request_id": RAO, "company_id": "TX-JP-01",
                                               "vehicle_id": "SC-1", "price_inr": 11000})
    services.book_offer(conn, catalog, own["offer_id"])
    assert services.get_offer_row(conn, b["offer_id"])["status"] == "NOT_CHOSEN"


# --- After booking: change and cancel -----------------------------------------------------

def test_cancel_one_family_keeps_the_other(conn, catalog):
    post_both(conn, catalog)
    a, b = services.create_shared_offer(conn, catalog, shared())["offers"]
    first = services.book_offer(conn, catalog, a["offer_id"])["booking_no"]
    second = services.book_offer(conn, catalog, b["offer_id"])["booking_no"]
    services.cancel_booking(conn, catalog, first)
    assert services.booking_summary(conn, catalog, second)["status"] == "CONFIRMED"


def test_change_on_a_shared_ride(conn, catalog):
    post_both(conn, catalog)
    a, b = services.create_shared_offer(conn, catalog, shared())["offers"]
    first = services.book_offer(conn, catalog, a["offer_id"])["booking_no"]
    services.book_offer(conn, catalog, b["offer_id"])
    # One hour later: the car still carries the other family then, so the change is refused (R6).
    clash = services.create_change(conn, catalog, first, {"new_pickup": "2027-04-10T12:30"})
    with pytest.raises(services.ApiError) as exc:
        services.accept_change(conn, catalog, clash["change_id"], "TX-JP-02")
    assert rules_of(exc) == {"R6"}
    services.reject_change(conn, catalog, clash["change_id"], "TX-JP-02", "Car is full then")
    # After the shared ride is over the car is free: accepted, and the ride is no longer shared.
    later = services.create_change(conn, catalog, first, {"new_pickup": "2027-04-10T14:30"})
    services.accept_change(conn, catalog, later["change_id"], "TX-JP-02")
    assert services.booking_summary(conn, catalog, first)["shared"] is None


def test_both_families_stay_visible_while_they_share(conn, catalog):
    # Regression: each family's hold on the shared car must not hide the OTHER family.
    services.create_request(conn, catalog, request("Menon family"))
    services.create_request(conn, catalog, couple(large_bags=2, small_bags=2))   # only FV-1 fits them together
    a, _ = services.create_shared_offer(conn, catalog, shared())["offers"]
    seen = lambda: {r["request_id"] for r in services.supplier_dashboard(conn, catalog, "TX-JP-02")["requests"]}
    assert {MENON, RAO} <= seen()
    services.book_offer(conn, catalog, a["offer_id"])                # Menon booked: Rao can still ride
    assert RAO in seen()
    assert services.request_detail(conn, catalog, RAO)["availability"]["available"] is True
    with pytest.raises(services.ApiError) as exc:                    # but not as a private ride in FV-1
        services.create_offer(conn, catalog, {"request_id": RAO, "company_id": "TX-JP-02",
                                              "vehicle_id": "FV-1", "price_inr": 12000})
    assert rules_of(exc) == {"R7"}
