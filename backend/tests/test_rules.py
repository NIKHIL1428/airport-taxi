"""Rule tests on a small sample data set (tests/fixtures/data), built from DATA_DICTIONARY examples.

Run from backend/:  python -m pytest -q
"""
from datetime import datetime
from pathlib import Path

import pytest

from app import rules, services
from app.data_store import Catalog
from app.db import connect, init_db, seed_open_requests

FIXTURES = Path(__file__).parent / "fixtures" / "data"


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


_names = iter(range(1, 10_000))


def menon(**overrides):
    """The Menon request. Each call gets its own name, because names must be unique."""
    p = {"traveler_name": f"Menon family {next(_names)}", "flight_id": "FL-401", "hotel_id": "HTL-TYO-004",
         "adults": 2, "child_ages": [6], "large_bags": 3, "small_bags": 2,
         "pickup": "2027-04-10T11:30", "car_type": None, "price_inr": 12000}
    p.update(overrides)
    return p


def rules_of(errors):
    return {e.rule for e in errors}


# --- M1: R1, R2, R3 --------------------------------------------------------

def test_menon_request_is_valid(catalog):
    errors, ctx = rules.validate_request(menon(), catalog)
    assert errors == []
    assert ctx.passengers == 3
    assert ctx.busy_start == datetime(2027, 4, 10, 11, 30)
    assert ctx.busy_end == datetime(2027, 4, 10, 14, 30)


def test_no_pickup_uses_earliest(catalog):
    _, ctx = rules.validate_request(menon(pickup=None), catalog)
    assert ctx.pickup == datetime(2027, 4, 10, 11, 30)


def test_pickup_59_minutes_after_landing_is_refused(catalog):
    errors, _ = rules.validate_request(menon(pickup="2027-04-10T11:29"), catalog)
    assert rules_of(errors) == {"R2"}


@pytest.mark.parametrize("price,ok", [(10199, False), (10200, True), (16800, True), (16801, False)])
def test_price_range_edges(catalog, price, ok):
    errors, _ = rules.validate_request(menon(price_inr=price), catalog)
    assert (errors == []) == ok
    if not ok:
        assert "₹10,200 – ₹16,800" in errors[0].message


def test_zero_adults_and_bad_child_age(catalog):
    errors, _ = rules.validate_request(menon(adults=0, child_ages=[6, 18]), catalog)
    assert rules_of(errors) == {"R1"}
    assert len(errors) == 2


def test_airport_must_serve_hotel_city(catalog):
    errors, _ = rules.validate_request(menon(hotel_id="HTL-OSA-001"), catalog)
    assert rules_of(errors) == {"R1"} and "serves Tokyo" in errors[0].message


def test_flight_to_india_is_refused(catalog):
    errors, _ = rules.validate_request(menon(flight_id="FL-002"), catalog)
    assert rules_of(errors) == {"R1"}


def test_unknown_flight_and_hotel(catalog):
    errors, _ = rules.validate_request(menon(flight_id="FL-XXX", hotel_id="HTL-XXX"), catalog)
    assert {e.field for e in errors} == {"flight_id", "hotel_id"}


# --- Time helpers -----------------------------------------------------------

def test_touching_busy_times_do_not_overlap():
    t = lambda h: datetime(2027, 4, 10, h)
    assert not rules.overlaps(t(11), t(14), t(14), t(16))
    assert rules.overlaps(t(11), t(14), t(13), t(16))


@pytest.mark.parametrize("hhmm,open_", [("00:30", True), ("01:00", True), ("01:01", False),
                                         ("03:00", False), ("05:00", True), ("23:59", True)])
def test_opening_hours_past_midnight(hhmm, open_):
    h, m = map(int, hhmm.split(":"))
    assert rules.is_open_at("05:00", "01:00", datetime(2027, 4, 10, h, m)) == open_


# --- R4 / R5 / R6: who sees the Menon request --------------------------------

def test_menon_suppliers(conn, catalog):
    _, ctx = rules.validate_request(menon(), catalog)
    busy = services.busy_times_by_vehicle(conn, catalog)
    evs = {e.company_id: e for e in services.evaluate_all_suppliers(ctx, catalog, busy)}
    # Sakura: SC-1 too small (2 large bags), SC-2 busy 11:00-14:00 (RIDE-0001) -> R6
    assert not evs["TX-JP-01"].can_serve and evs["TX-JP-01"].rule == "R6"
    assert evs["TX-JP-02"].can_serve
    assert evs["TX-AE-01"].rule == "R4"


def test_car_free_once_previous_ride_ends(conn, catalog):
    _, ctx = rules.validate_request(menon(pickup="2027-04-10T14:00"), catalog)
    busy = services.busy_times_by_vehicle(conn, catalog)
    ev = rules.evaluate_supplier(catalog.companies["TX-JP-01"], ctx, busy)
    assert ev.can_serve  # SC-2 free from exactly 14:00


def test_car_type_filter(conn, catalog):
    _, ctx = rules.validate_request(menon(car_type="SEDAN", large_bags=1, pickup="2027-04-10T15:00"), catalog)
    busy = services.busy_times_by_vehicle(conn, catalog)
    ev = rules.evaluate_supplier(catalog.companies["TX-JP-02"], ctx, busy)
    assert ev.rule == "R5"  # Fuji Vans only has an SUV


def test_no_ride_gives_simple_message_and_one_plain_reason(conn, catalog):
    _, ctx = rules.validate_request(menon(adults=8, child_ages=[], price_inr=12000), catalog)
    busy = services.busy_times_by_vehicle(conn, catalog)
    result = rules.traveler_availability(services.evaluate_all_suppliers(ctx, catalog, busy), ctx)
    assert result["available"] is False
    assert result["message"] == "No ride is available for your request."
    assert "8 passengers" in result["reason"]          # furthest stage reached = car fit
    assert "Sakura" not in result["reason"] and "R5" not in result["reason"]


def test_available_ride(conn, catalog):
    _, ctx = rules.validate_request(menon(), catalog)
    busy = services.busy_times_by_vehicle(conn, catalog)
    assert rules.traveler_availability(services.evaluate_all_suppliers(ctx, catalog, busy), ctx)["available"]


# --- R7 ------------------------------------------------------------------------

def test_assignment_checks(conn, catalog):
    _, ctx = rules.validate_request(menon(), catalog)
    busy = services.busy_times_by_vehicle(conn, catalog)
    sakura, fuji = catalog.companies["TX-JP-01"], catalog.companies["TX-JP-02"]
    assert rules_of(rules.check_assignment(sakura, "SC-1", 12000, ctx, busy)) >= {"R5"}
    assert "R6" in rules_of(rules.check_assignment(sakura, "SC-2", 12000, ctx, busy))
    assert rules.check_assignment(fuji, "FV-1", 13000, ctx, busy) == []
    assert rules_of(rules.check_assignment(fuji, "FV-1", 9000, ctx, busy)) == {"R3"}
    assert rules_of(rules.check_assignment(fuji, "SC-1", 12000, ctx, busy)) == {"R7"}


# --- Services: storage + dashboards ------------------------------------------

def test_create_request_and_dashboards(conn, catalog):
    view = services.create_request(conn, catalog, menon())
    assert view["request_id"] == "REQ-0003"   # after seeded REQ-0002
    assert view["availability"]["available"] is True
    assert "busy_window" not in view           # traveler view hides supplier details
    fuji = services.supplier_dashboard(conn, catalog, "TX-JP-02")
    assert [r["request_id"] for r in fuji["requests"]] == ["REQ-0003"]
    marina = services.supplier_dashboard(conn, catalog, "TX-AE-01")
    assert [r["request_id"] for r in marina["requests"]] == ["REQ-0002"]  # 00:30 pickup, open till 01:00
    sakura = services.supplier_dashboard(conn, catalog, "TX-JP-01")
    assert sakura["requests"] == []


def test_invalid_request_is_not_saved(conn, catalog):
    with pytest.raises(services.ApiError) as exc:
        services.create_request(conn, catalog, menon(price_inr=5))
    assert exc.value.status == 422
    assert conn.execute("SELECT COUNT(*) FROM ride_requests").fetchone()[0] == 1


# --- M3 / M4 / M5 / M6: offers and bookings ------------------------------------

def offer(**overrides):
    p = {"request_id": "REQ-0003", "company_id": "TX-JP-02", "vehicle_id": "FV-1", "price_inr": 13000}
    p.update(overrides)
    return p


def test_assign_refused_with_reason(conn, catalog):
    services.create_request(conn, catalog, menon())
    with pytest.raises(services.ApiError) as exc:
        services.create_offer(conn, catalog, offer(company_id="TX-JP-01", vehicle_id="SC-1"))
    assert "R5" in rules_of(exc.value.errors)
    with pytest.raises(services.ApiError) as exc:
        services.create_offer(conn, catalog, offer(price_inr=20000))
    assert rules_of(exc.value.errors) == {"R3"}


def test_assign_book_and_summary(conn, catalog):
    services.create_request(conn, catalog, menon())
    a = services.create_offer(conn, catalog, offer())
    # same car twice on one request is refused (R7)
    with pytest.raises(services.ApiError):
        services.create_offer(conn, catalog, offer())
    booking = services.book_offer(conn, catalog, a["offer_id"])
    no = booking["booking_no"]
    assert len(no) == 10 and no.isdigit() and no[0] != "0"
    assert booking["supplier"]["name"] == "Fuji Vans" and booking["price_inr"] == 13000
    assert services.booking_summary(conn, catalog, no)["booking_no"] == no
    with pytest.raises(services.ApiError) as exc:
        services.booking_summary(conn, catalog, "1234567890")
    assert exc.value.status == 404
    # request is now booked: no more offers, gone from the dashboard
    assert services.supplier_dashboard(conn, catalog, "TX-JP-02")["requests"] == []
    with pytest.raises(services.ApiError):
        services.create_offer(conn, catalog, offer())


def test_reject_then_book_other_marks_not_chosen(conn, catalog):
    services.create_request(conn, catalog, menon(pickup="2027-04-10T15:00"))   # SC-2 free again
    sakura = services.create_offer(conn, catalog, offer(company_id="TX-JP-01", vehicle_id="SC-2", price_inr=11000))
    fuji = services.create_offer(conn, catalog, offer())
    services.reject_offer(conn, catalog, sakura["offer_id"])
    with pytest.raises(services.ApiError) as exc:
        services.book_offer(conn, catalog, sakura["offer_id"])
    assert "rejected" in exc.value.errors[0].message
    services.book_offer(conn, catalog, fuji["offer_id"])
    statuses = {o["company_id"]: o["status"] for o in services.request_offers(conn, catalog, "REQ-0003")}
    assert statuses == {"TX-JP-01": "REJECTED", "TX-JP-02": "BOOKED"}


def test_other_offers_become_not_chosen(conn, catalog):
    services.create_request(conn, catalog, menon(pickup="2027-04-10T15:00"))
    sakura = services.create_offer(conn, catalog, offer(company_id="TX-JP-01", vehicle_id="SC-2", price_inr=11000))
    fuji = services.create_offer(conn, catalog, offer())
    services.book_offer(conn, catalog, fuji["offer_id"])
    assert services.get_offer_row(conn, sakura["offer_id"])["status"] == "NOT_CHOSEN"


def test_no_double_booking(conn, catalog, monkeypatch):
    # Two families on the same flight, same pickup. Fuji's only car is offered to both:
    # to the second only after the first offer's guaranteed window is over.
    from datetime import timedelta
    services.create_request(conn, catalog, menon())                          # REQ-0003
    services.create_request(conn, catalog, menon(traveler_name="Second"))    # REQ-0004
    second = services.create_offer(conn, catalog, offer(request_id="REQ-0004"))
    start = services.now()
    monkeypatch.setattr(services, "now", lambda: start + timedelta(minutes=6))
    first = services.create_offer(conn, catalog, offer())
    services.book_offer(conn, catalog, first["offer_id"])
    offers = services.request_offers(conn, catalog, "REQ-0004")
    assert offers[0]["status"] == "CAR_TAKEN"                                 # shown to traveler
    with pytest.raises(services.ApiError) as exc:
        services.book_offer(conn, catalog, second["offer_id"])
    assert rules_of(exc.value.errors) == {"R6"} and exc.value.status == 409
    assert services.get_request_row(conn, "REQ-0004")["status"] == "OPEN"     # nothing changed


def test_traveler_list_by_ids(conn, catalog):
    services.create_request(conn, catalog, menon())
    assert [r["request_id"] for r in services.list_requests(conn, catalog, ["REQ-0003"])] == ["REQ-0003"]
    assert services.list_requests(conn, catalog, []) == []


def test_db_connection_can_cross_threads(tmp_path):
    """FastAPI may open the connection and run the endpoint on different threads (the 500 bug)."""
    import threading
    c = connect(tmp_path / "t.db")
    errors = []
    t = threading.Thread(target=lambda: errors.extend([] if c.execute("SELECT 1").fetchone() else ["no row"]))
    t.start(); t.join()
    c.close()
    assert errors == []


# --- Guaranteed window: the car is held for the traveler, then released to everyone ------

def move_clock(monkeypatch, minutes):
    from datetime import timedelta
    start = services.now()
    monkeypatch.setattr(services, "now", lambda: start + timedelta(minutes=minutes))


def two_menons(conn, catalog):
    """Two families on the same flight and pickup; Fuji Vans has one car (FV-1) that fits both."""
    services.create_request(conn, catalog, menon())    # REQ-0003
    services.create_request(conn, catalog, menon())    # REQ-0004


def test_offer_guaranteed_for_5_minutes(conn, catalog):
    services.create_request(conn, catalog, menon())
    o = services.create_offer(conn, catalog, offer())
    assert o["guaranteed"] and 295 <= o["guarantee_seconds_left"] <= 300


def test_held_car_is_not_available_to_others(conn, catalog):
    two_menons(conn, catalog)
    services.create_offer(conn, catalog, offer())                         # FV-1 held for REQ-0003
    # Fuji can no longer serve REQ-0004 (its only car is held) ...
    assert services.supplier_dashboard(conn, catalog, "TX-JP-02")["requests"][0]["request_id"] == "REQ-0003"
    assert [r["request_id"] for r in services.supplier_dashboard(conn, catalog, "TX-JP-02")["requests"]] == ["REQ-0003"]
    # ... and cannot assign it there
    with pytest.raises(services.ApiError) as exc:
        services.create_offer(conn, catalog, offer(request_id="REQ-0004"))
    assert "R6" in rules_of(exc.value.errors) and "held for another traveler" in exc.value.errors[0].message


def test_book_inside_window_is_guaranteed(conn, catalog, monkeypatch):
    services.create_request(conn, catalog, menon())
    o = services.create_offer(conn, catalog, offer())
    move_clock(monkeypatch, 4)
    assert services.book_offer(conn, catalog, o["offer_id"])["booking_no"]


def test_after_window_offer_stays_open_and_car_is_released(conn, catalog, monkeypatch):
    two_menons(conn, catalog)
    first = services.create_offer(conn, catalog, offer())                 # held for REQ-0003
    move_clock(monkeypatch, 6)                                            # guarantee over
    view = services.request_offers(conn, catalog, "REQ-0003")[0]
    assert view["status"] == "OPEN" and not view["guaranteed"] and view["guarantee_seconds_left"] == 0
    # the car is now available to everyone: Fuji offers it to REQ-0004 (with a new hold) ...
    second = services.create_offer(conn, catalog, offer(request_id="REQ-0004"))
    # ... so REQ-0003 sees a warning and its booking is refused while REQ-0004 holds the car
    assert "held for another traveler" in services.request_offers(conn, catalog, "REQ-0003")[0]["warning"]
    with pytest.raises(services.ApiError) as exc:
        services.book_offer(conn, catalog, first["offer_id"])
    assert exc.value.status == 409 and "held for another traveler" in exc.value.errors[0].message
    services.book_offer(conn, catalog, second["offer_id"])
    assert services.get_offer_row(conn, first["offer_id"])["status"] == "CAR_TAKEN"
    with pytest.raises(services.ApiError) as exc:                         # booked by the other traveler
        services.book_offer(conn, catalog, first["offer_id"])
    assert "booked by another traveler" in exc.value.errors[0].message


def test_after_window_original_traveler_can_still_book_if_free(conn, catalog, monkeypatch):
    services.create_request(conn, catalog, menon())
    o = services.create_offer(conn, catalog, offer())
    move_clock(monkeypatch, 30)
    assert services.book_offer(conn, catalog, o["offer_id"])["booking_no"]


def test_rejecting_releases_the_hold(conn, catalog):
    two_menons(conn, catalog)
    o = services.create_offer(conn, catalog, offer())
    services.reject_offer(conn, catalog, o["offer_id"])
    assert services.create_offer(conn, catalog, offer(request_id="REQ-0004"))["status"] == "OPEN"


def test_traveler_availability_ignores_own_hold(conn, catalog):
    two_menons(conn, catalog)
    services.create_offer(conn, catalog, offer())
    assert services.request_detail(conn, catalog, "REQ-0003")["availability"]["available"]


def test_custom_guarantee_time(conn, catalog):
    services.create_request(conn, catalog, menon())
    o = services.create_offer(conn, catalog, offer(hold_minutes=2))
    assert 115 <= o["guarantee_seconds_left"] <= 120
    for bad in (0, 61):
        with pytest.raises(services.ApiError) as exc:
            services.create_offer(conn, catalog, offer(hold_minutes=bad, vehicle_id="FV-1"))
        assert "hold_minutes" in {e.field for e in exc.value.errors}


def test_old_database_is_migrated(tmp_path):
    import sqlite3
    c = sqlite3.connect(tmp_path / "old.db")
    c.executescript("""CREATE TABLE offers (offer_id INTEGER PRIMARY KEY, request_id TEXT, company_id TEXT,
                       vehicle_id TEXT, price_inr INTEGER, status TEXT, expires_at TEXT, created_at TEXT);
                       INSERT INTO offers VALUES (1,'R','C','V',1,'EXPIRED',NULL,'x');""")
    c.commit(); c.close()
    conn = connect(tmp_path / "old.db"); init_db(conn)
    assert tuple(conn.execute("SELECT status, hold_until FROM offers").fetchone()) == ("OPEN", None)


# --- Unique traveler names + find my ride by name -------------------------------

def test_name_is_required_and_unique(conn, catalog):
    services.create_request(conn, catalog, menon(traveler_name="Menon family"))
    for taken in ("Menon family", "  menon   FAMILY "):            # same name, other spacing/capitals
        with pytest.raises(services.ApiError) as exc:
            services.create_request(conn, catalog, menon(traveler_name=taken))
        assert exc.value.errors[0].field == "traveler_name" and "already taken" in exc.value.errors[0].message
    for bad in ("", "   ", "A", "x" * 61):
        with pytest.raises(services.ApiError) as exc:
            services.create_request(conn, catalog, menon(traveler_name=bad))
        assert exc.value.errors[0].field == "traveler_name"
    # seeded names are taken too
    assert not services.name_availability(conn, "Arjun and Meera")["available"]
    assert services.name_availability(conn, "Menon family 2")["available"]


def test_name_and_rule_errors_together(conn, catalog):
    services.create_request(conn, catalog, menon(traveler_name="Menon family"))
    with pytest.raises(services.ApiError) as exc:
        services.create_request(conn, catalog, menon(traveler_name="Menon family", price_inr=5))
    assert {e.rule for e in exc.value.errors} == {"NAME", "R3"}


def test_find_ride_by_name_shows_booking_number(conn, catalog):
    services.create_request(conn, catalog, menon(traveler_name="Menon family"))
    o = services.create_offer(conn, catalog, offer())
    booking = services.book_offer(conn, catalog, o["offer_id"])
    found = services.find_request_by_name(conn, catalog, "menon FAMILY")
    assert found["request_id"] == "REQ-0003" and found["booking_no"] == booking["booking_no"]
    with pytest.raises(services.ApiError) as exc:
        services.find_request_by_name(conn, catalog, "Nobody here")
    assert exc.value.status == 404


# --- After a booking: other offers of the same car; two Book clicks at the same moment ----

def test_offers_of_a_booked_car_become_car_taken(conn, catalog, monkeypatch):
    from datetime import timedelta
    two_menons(conn, catalog)                                              # same flight, same time
    services.create_request(conn, catalog, menon(pickup="2027-04-10T18:00"))  # REQ-0005: later the same day
    a = services.create_offer(conn, catalog, offer(hold_minutes=1))
    start = services.now()
    monkeypatch.setattr(services, "now", lambda: start + timedelta(minutes=2))
    b = services.create_offer(conn, catalog, offer(request_id="REQ-0004"))
    later = services.create_offer(conn, catalog, offer(request_id="REQ-0005"))
    services.book_offer(conn, catalog, b["offer_id"])
    status = lambda o: services.get_offer_row(conn, o["offer_id"])["status"]
    assert status(a) == "CAR_TAKEN"          # overlapping time: can never be booked now
    assert status(later) == "OPEN"           # 18:00 does not overlap 11:30-14:30: still bookable
    with pytest.raises(services.ApiError) as exc:
        services.book_offer(conn, catalog, a["offer_id"])
    assert "booked by another traveler" in exc.value.errors[0].message
    assert services.list_requests(conn, catalog, ["REQ-0003"])[0]["open_offer_count"] == 0
    assert services.book_offer(conn, catalog, later["offer_id"])["booking_no"]


def test_two_book_clicks_at_the_same_moment(tmp_path, catalog, monkeypatch):
    """Two travelers book the same car at the same instant: exactly one wins."""
    import threading
    from datetime import timedelta
    db = tmp_path / "race.db"
    c = connect(db); init_db(c); seed_open_requests(c, catalog.open_requests)
    services.create_request(c, catalog, menon()); services.create_request(c, catalog, menon())
    o1 = services.create_offer(c, catalog, offer(hold_minutes=1))
    start = services.now()
    monkeypatch.setattr(services, "now", lambda: start + timedelta(minutes=2))  # both unheld
    o2 = services.create_offer(c, catalog, offer(request_id="REQ-0004", hold_minutes=1))
    monkeypatch.setattr(services, "now", lambda: start + timedelta(minutes=5))
    c.close()

    # slow down the check so both threads are inside it at the same time
    real = services.busy_times_by_vehicle
    gate = threading.Barrier(2, timeout=0.5)
    def slow(*a, **k):
        try:
            gate.wait()
        except threading.BrokenBarrierError:
            pass
        return real(*a, **k)
    monkeypatch.setattr(services, "busy_times_by_vehicle", slow)

    results = []
    def book(offer_id):
        conn = connect(db)
        try:
            results.append(services.book_offer(conn, catalog, offer_id)["booking_no"])
        except services.ApiError as e:
            results.append(e.errors[0].rule)
        finally:
            conn.close()
    threads = [threading.Thread(target=book, args=(o,)) for o in (o1["offer_id"], o2["offer_id"])]
    for t in threads: t.start()
    for t in threads: t.join()
    c = connect(db)
    assert c.execute("SELECT COUNT(*) FROM bookings WHERE vehicle_id = 'FV-1'").fetchone()[0] == 1
    assert sorted(len(r) for r in results) == [2, 10]      # one booking number, one "R6"/"R8" refusal


# --- M7 / R9: change requests ---------------------------------------------------

def booked_menon(conn, catalog, **overrides):
    """REQ-0003 booked on Fuji Vans FV-1, 10 Apr 11:30 (car busy 11:30-14:30)."""
    services.create_request(conn, catalog, menon(**overrides))
    o = services.create_offer(conn, catalog, offer())
    return services.book_offer(conn, catalog, o["offer_id"])["booking_no"]


def test_change_pickup_accepted(conn, catalog):
    no = booked_menon(conn, catalog)
    ch = services.create_change(conn, catalog, no, {"new_pickup": "2027-04-10T12:30"})
    assert ch["status"] == "WAITING" and ch["resulting_pickup"] == "2027-04-10T12:30"
    waiting = services.supplier_changes(conn, catalog, "TX-JP-02")
    assert waiting[0]["can_accept"] and waiting[0]["traveler_name"].startswith("Menon")
    assert services.accept_change(conn, catalog, ch["change_id"], "TX-JP-02")["status"] == "ACCEPTED"
    b = services.booking_summary(conn, catalog, no)
    assert b["pickup"] == "2027-04-10T12:30" and b["changes"][0]["status"] == "ACCEPTED"
    assert b["changes"][0]["old_pickup"] == "2027-04-10T11:30"
    row = conn.execute("SELECT busy_start, busy_end FROM bookings").fetchone()
    assert tuple(row) == ("2027-04-10T12:30", "2027-04-10T15:30")      # the car's busy time moved too


def test_change_flight_uses_earliest_pickup(conn, catalog):
    no = booked_menon(conn, catalog)
    ch = services.create_change(conn, catalog, no, {"new_flight_id": "FL-403"})   # NRT, lands 16:00
    assert ch["resulting_pickup"] == "2027-04-10T17:00"
    services.accept_change(conn, catalog, ch["change_id"], "TX-JP-02")
    b = services.booking_summary(conn, catalog, no)
    assert b["flight"]["flight_id"] == "FL-403" and b["pickup"] == "2027-04-10T17:00"
    assert services.get_request_row(conn, "REQ-0003")["flight_id"] == "FL-403"


def test_change_refused_r2_and_wrong_airport(conn, catalog):
    no = booked_menon(conn, catalog)
    for payload, rule in (({"new_pickup": "2027-04-10T11:00"}, "R2"),            # 30 min after landing
                          ({"new_flight_id": "FL-403", "new_pickup": "2027-04-10T16:30"}, "R2"),
                          ({"new_flight_id": "FL-900"}, "R9"),                    # lands at DXB
                          ({"new_flight_id": "FL-XXX"}, "R9"),
                          ({}, "INPUT"),
                          ({"new_pickup": "2027-04-10T11:30"}, "INPUT")):        # nothing changes
        with pytest.raises(services.ApiError) as exc:
            services.create_change(conn, catalog, no, payload)
        assert exc.value.errors[0].rule == rule, payload
    assert conn.execute("SELECT COUNT(*) FROM change_requests").fetchone()[0] == 0


def test_change_refused_when_car_busy_then_rejected_keeps_booking(conn, catalog):
    no = booked_menon(conn, catalog)
    # another family books the same car at 15:00 (busy 15:00-18:00)
    services.create_request(conn, catalog, menon(pickup="2027-04-10T15:00"))      # REQ-0004
    o = services.create_offer(conn, catalog, offer(request_id="REQ-0004"))
    services.book_offer(conn, catalog, o["offer_id"])
    ch = services.create_change(conn, catalog, no, {"new_pickup": "2027-04-10T13:00"})  # needs 13:00-16:00
    view = services.supplier_changes(conn, catalog, "TX-JP-02")[0]
    assert view["can_accept"] is False and view["problems"][0]["rule"] == "R6"
    with pytest.raises(services.ApiError) as exc:
        services.accept_change(conn, catalog, ch["change_id"], "TX-JP-02")
    assert exc.value.status == 409 and exc.value.errors[0].rule == "R6"
    services.reject_change(conn, catalog, ch["change_id"], "TX-JP-02", "Car is booked then")
    b = services.booking_summary(conn, catalog, no)
    assert b["pickup"] == "2027-04-10T11:30"                                      # old booking kept
    assert b["changes"][0]["status"] == "REJECTED" and b["changes"][0]["reason"] == "Car is booked then"


def test_change_back_to_back_is_allowed(conn, catalog):
    no = booked_menon(conn, catalog)
    services.create_request(conn, catalog, menon(pickup="2027-04-10T15:00"))
    o = services.create_offer(conn, catalog, offer(request_id="REQ-0004"))
    services.book_offer(conn, catalog, o["offer_id"])
    ch = services.create_change(conn, catalog, no, {"new_pickup": "2027-04-10T12:00"})   # 12:00-15:00: touches
    assert services.accept_change(conn, catalog, ch["change_id"], "TX-JP-02")["status"] == "ACCEPTED"


def test_change_rules_one_waiting_and_only_own_supplier(conn, catalog):
    no = booked_menon(conn, catalog)
    ch = services.create_change(conn, catalog, no, {"new_pickup": "2027-04-10T12:30"})
    with pytest.raises(services.ApiError):                                          # one at a time
        services.create_change(conn, catalog, no, {"new_pickup": "2027-04-10T13:30"})
    with pytest.raises(services.ApiError) as exc:                                   # not their booking
        services.accept_change(conn, catalog, ch["change_id"], "TX-JP-01")
    assert exc.value.status == 403
    services.reject_change(conn, catalog, ch["change_id"], "TX-JP-02")
    with pytest.raises(services.ApiError):                                          # already decided
        services.accept_change(conn, catalog, ch["change_id"], "TX-JP-02")
    # after a decision the traveler can ask again
    assert services.create_change(conn, catalog, no, {"new_pickup": "2027-04-10T13:30"})["status"] == "WAITING"


# --- Cancel a booking ---------------------------------------------------------------

def test_cancel_frees_the_car_and_closes_everything(conn, catalog):
    no = booked_menon(conn, catalog)                                                # FV-1, 11:30-14:30
    ch = services.create_change(conn, catalog, no, {"new_pickup": "2027-04-10T12:30"})
    b = services.cancel_booking(conn, catalog, no)
    assert b["status"] == "CANCELLED"
    assert services.get_request_row(conn, "REQ-0003")["status"] == "CANCELLED"
    assert services.request_offers(conn, catalog, "REQ-0003")[0]["status"] == "CANCELLED"
    assert services.booking_summary(conn, catalog, no)["changes"][0]["status"] == "REJECTED"
    assert "FV-1" not in services.busy_times_by_vehicle(conn, catalog)              # car free again
    # another traveler can now get and book FV-1 for the same time
    services.create_request(conn, catalog, menon())                                 # REQ-0004
    o = services.create_offer(conn, catalog, offer(request_id="REQ-0004"))
    assert services.book_offer(conn, catalog, o["offer_id"])["booking_no"]
    # nothing more can happen to the cancelled booking or ride
    for action in (lambda: services.cancel_booking(conn, catalog, no),
                   lambda: services.create_change(conn, catalog, no, {"new_pickup": "2027-04-10T13:30"}),
                   lambda: services.accept_change(conn, catalog, ch["change_id"], "TX-JP-02"),
                   lambda: services.create_offer(conn, catalog, offer())):
        with pytest.raises(services.ApiError):
            action()


def test_cancel_reopens_car_taken_offers(conn, catalog, monkeypatch):
    from datetime import timedelta
    two_menons(conn, catalog)
    a = services.create_offer(conn, catalog, offer(hold_minutes=1))
    start = services.now()
    monkeypatch.setattr(services, "now", lambda: start + timedelta(minutes=2))
    b = services.create_offer(conn, catalog, offer(request_id="REQ-0004"))
    no = services.book_offer(conn, catalog, b["offer_id"])["booking_no"]
    assert services.get_offer_row(conn, a["offer_id"])["status"] == "CAR_TAKEN"
    services.cancel_booking(conn, catalog, no)
    assert services.get_offer_row(conn, a["offer_id"])["status"] == "OPEN"          # bookable again
    assert services.book_offer(conn, catalog, a["offer_id"])["booking_no"]


# --- Supplier car labels, booking lookup -------------------------------------------

def test_car_availability_labels(conn, catalog):
    _, ctx = rules.validate_request(menon(), catalog)
    busy = services.busy_times_by_vehicle(conn, catalog)
    ev = rules.evaluate_supplier(catalog.companies["TX-JP-01"], ctx, busy)
    states = {v.vehicle_id: v.to_dict()["availability"]["state"] for v in ev.vehicles}
    assert states == {"SC-1": "DOES_NOT_FIT", "SC-2": "BUSY"}


def test_lookup_booking_needs_name_and_number(conn, catalog):
    no = booked_menon(conn, catalog, traveler_name="Menon family")
    assert services.lookup_booking(conn, catalog, "  menon FAMILY ", no)["booking_no"] == no
    for name, number in (("Someone else", no), ("Menon family", "1234567890"), ("Menon family", "abc"), ("", "")):
        with pytest.raises(services.ApiError) as exc:
            services.lookup_booking(conn, catalog, name, number)
        assert exc.value.status == 404
