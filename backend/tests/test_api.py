"""API tests: the real FastAPI app (main.py) called over HTTP with TestClient, like the frontend does.

They check status codes, the JSON the frontend reads, and the error format {"errors": [{rule, field, message}]}.
Each test gets its own empty database in a temporary folder; the real taxi.db is never touched.
Uses the real data pack in ../data (skipped if it is missing).

Run from backend/:  python -m pytest -q tests/test_api.py
"""
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi", reason="FastAPI is not installed")
pytest.importorskip("httpx", reason="TestClient needs httpx: pip install -r requirements.txt")
from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402

DATA = Path(__file__).resolve().parents[2] / "data"
pytestmark = pytest.mark.skipif(not (DATA / "problem-2").exists(), reason="data pack not copied into data/")

MENON = {"traveler_name": "Menon family", "flight_id": "FL-401", "hotel_id": "HTL-TYO-004",
         "adults": 2, "child_ages": [6], "large_bags": 3, "small_bags": 2,
         "pickup": "2027-04-10T11:30", "car_type": None, "price_inr": 12000}


@pytest.fixture
def client(tmp_path, monkeypatch):
    """The app with a fresh database: startup creates the tables and loads the 3 open requests."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    from app.main import app
    with TestClient(app) as c:
        yield c


def post_menon(client, **overrides):
    r = client.post("/api/requests", json={**MENON, **overrides})
    assert r.status_code == 201, r.text
    return r.json()


def assign(client, request_id, company_id, vehicle_id, price, **extra):
    return client.post("/api/offers", json={"request_id": request_id, "company_id": company_id,
                                            "vehicle_id": vehicle_id, "price_inr": price, **extra})


def book_menon(client):
    """Menon books Sakura Cabs SC-3 for ₹12,500. Returns the booking."""
    post_menon(client)
    offer = assign(client, "REQ-0004", "TX-JP-01", "SC-3", 12500).json()
    r = client.post(f"/api/offers/{offer['offer_id']}/book")
    assert r.status_code == 201, r.text
    return r.json()


# --- Catalog and price range ---------------------------------------------------------

def test_health_and_catalog(client):
    assert client.get("/api/health").json() == {"ok": True}
    catalog = client.get("/api/catalog").json()
    assert [a["code"] for a in catalog["arrival_airports"]] == ["AUH", "DXB", "HND", "KIX", "NRT"]
    assert all(f["to"] in {"AUH", "DXB", "HND", "KIX", "NRT"} for f in catalog["flights"])
    assert len(catalog["suppliers"]) == 11
    assert catalog["car_types"] == ["HATCHBACK", "SEDAN", "SUV", "BUS"]


def test_price_range(client):
    r = client.get("/api/price-range", params={"flight_id": "FL-401", "hotel_id": "HTL-TYO-004"})
    assert r.status_code == 200
    body = r.json()
    assert (body["price_min_inr"], body["price_max_inr"]) == (10200, 16800)
    assert body["earliest_pickup"] == "2027-04-10T11:30"


def test_price_range_refuses_wrong_city(client):
    r = client.get("/api/price-range", params={"flight_id": "FL-401", "hotel_id": "HTL-OSA-001"})
    assert r.status_code == 422
    assert r.json()["errors"][0]["rule"] == "R1"


# --- M1: ride requests ---------------------------------------------------------------

def test_create_request(client):
    body = post_menon(client)
    assert body["request_id"] == "REQ-0004"
    assert body["availability"]["available"] is True
    assert "busy_window" not in body                    # the traveler does not see the car's busy time


def test_request_errors_name_the_rule_and_field(client):
    r = client.post("/api/requests", json={**MENON, "price_inr": 5, "adults": 0})
    assert r.status_code == 422
    errors = {(e["rule"], e["field"]) for e in r.json()["errors"]}
    assert ("R3", "price_inr") in errors and ("R1", "adults") in errors


def test_wrong_value_type_gives_a_clear_message(client):
    r = client.post("/api/requests", json={**MENON, "adults": "two"})
    assert r.status_code == 422
    assert r.json()["errors"][0] == {"rule": "INPUT", "field": "adults", "message": "Adults must be a whole number."}


def test_unique_names(client):
    post_menon(client)
    assert client.get("/api/names/check", params={"name": "menon FAMILY"}).json()["available"] is False
    assert client.get("/api/names/check", params={"name": "Menon family 2"}).json()["available"] is True
    r = client.post("/api/requests", json=MENON)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "traveler_name"


def test_list_and_find_requests(client):
    post_menon(client)
    assert [r["request_id"] for r in client.get("/api/requests", params={"ids": "REQ-0004"}).json()] == ["REQ-0004"]
    assert client.get("/api/requests/by-name", params={"name": "Menon family"}).json()["request_id"] == "REQ-0004"
    assert client.get("/api/requests/REQ-9999").status_code == 404


def test_no_ride_available_message(client):
    body = client.get("/api/requests/REQ-0002").json()           # preloaded: no Kansai sedan fits
    assert body["availability"]["available"] is False
    assert body["availability"]["message"] == "No ride is available for your request."


# --- M2, M3: supplier dashboard and assigning a car ------------------------------------

def test_dashboard_shows_only_requests_the_supplier_can_serve(client):
    post_menon(client)
    sakura = client.get("/api/suppliers/TX-JP-01/dashboard").json()
    assert "REQ-0004" in [r["request_id"] for r in sakura["requests"]]
    narita_star = client.get("/api/suppliers/TX-JP-02/dashboard").json()    # does not drive to Ueno
    assert "REQ-0004" not in [r["request_id"] for r in narita_star["requests"]]
    cars = {v["vehicle_id"]: v["availability"]["state"]
            for v in next(r for r in sakura["requests"] if r["request_id"] == "REQ-0004")["vehicles"]}
    assert cars["SC-2"] == "BUSY" and cars["SC-3"] == "AVAILABLE" and cars["SC-1"] == "DOES_NOT_FIT"


def test_assign_refused_with_rule(client):
    post_menon(client)
    r = assign(client, "REQ-0004", "TX-JP-01", "SC-2", 12000)            # busy 11:00-14:00 (RIDE-0001)
    assert r.status_code == 422 and r.json()["errors"][0]["rule"] == "R6"
    r = assign(client, "REQ-0004", "TX-JP-01", "SC-3", 20000)            # price above ₹16,800
    assert r.status_code == 422 and r.json()["errors"][0]["rule"] == "R3"


def test_assign_gives_a_guaranteed_window(client):
    post_menon(client)
    r = assign(client, "REQ-0004", "TX-JP-01", "SC-3", 12500)
    assert r.status_code == 201
    offer = r.json()
    assert offer["status"] == "OPEN" and offer["guaranteed"] is True
    assert 290 <= offer["guarantee_seconds_left"] <= 300


# --- M4, M5, M6: book, reject, booking summary -----------------------------------------

def test_reject_then_book_other(client):
    post_menon(client)
    sakura = assign(client, "REQ-0004", "TX-JP-01", "SC-3", 12500).json()
    edo = assign(client, "REQ-0004", "TX-JP-03", "EP-2", 13000).json()
    assert client.post(f"/api/offers/{edo['offer_id']}/reject").json()["status"] == "REJECTED"
    assert client.post(f"/api/offers/{edo['offer_id']}/book").status_code == 409     # rejected: cannot book
    booking = client.post(f"/api/offers/{sakura['offer_id']}/book").json()
    assert len(booking["booking_no"]) == 10 and booking["booking_no"].isdigit()
    statuses = {o["company_id"]: o["status"] for o in client.get("/api/requests/REQ-0004/offers").json()}
    assert statuses == {"TX-JP-01": "BOOKED", "TX-JP-03": "REJECTED"}


def test_booking_summary_and_not_found(client):
    booking = book_menon(client)
    summary = client.get(f"/api/bookings/{booking['booking_no']}").json()
    assert summary["supplier"]["name"] == "Sakura Cabs" and summary["vehicle"]["vehicle_id"] == "SC-3"
    assert summary["price_inr"] == 12500 and summary["hotel"]["name"] == "Ueno Garden Inn"
    assert client.get("/api/bookings/1234567890").status_code == 404


def test_track_booking_needs_name_and_number(client):
    booking = book_menon(client)
    ok = client.post("/api/bookings/lookup", json={"traveler_name": "menon family", "booking_no": booking["booking_no"]})
    assert ok.status_code == 200 and ok.json()["booking_no"] == booking["booking_no"]
    wrong = client.post("/api/bookings/lookup", json={"traveler_name": "Someone", "booking_no": booking["booking_no"]})
    assert wrong.status_code == 404


def test_no_double_booking(client):
    # Two families, same flight and pickup; Sakura offers SC-3 to both (one minute guarantee each).
    post_menon(client)
    post_menon(client, traveler_name="Second family")
    first = assign(client, "REQ-0004", "TX-JP-01", "SC-3", 12500, hold_minutes=1).json()
    second = assign(client, "REQ-0005", "TX-JP-01", "SC-3", 12500, hold_minutes=1)
    assert second.status_code == 422                                   # held for the first family
    assert client.post(f"/api/offers/{first['offer_id']}/book").status_code == 201
    third = assign(client, "REQ-0005", "TX-JP-01", "SC-3", 12500)
    assert third.status_code == 422 and third.json()["errors"][0]["rule"] == "R6"   # now booked


# --- M7: change requests; cancelling ---------------------------------------------------

def test_change_request_accepted(client):
    booking = book_menon(client)
    no = booking["booking_no"]
    change = client.post(f"/api/bookings/{no}/changes", json={"new_flight_id": "FL-402"})
    assert change.status_code == 201 and change.json()["resulting_pickup"] == "2027-04-11T11:30"
    waiting = client.get("/api/suppliers/TX-JP-01/changes").json()
    assert waiting[0]["status"] == "WAITING" and waiting[0]["can_accept"] is True
    r = client.post(f"/api/changes/{change.json()['change_id']}/accept", json={"company_id": "TX-JP-01"})
    assert r.status_code == 200 and r.json()["status"] == "ACCEPTED"
    summary = client.get(f"/api/bookings/{no}").json()
    assert (summary["flight"]["flight_id"], summary["pickup"]) == ("FL-402", "2027-04-11T11:30")


def test_change_request_refused_and_rejected(client):
    booking = book_menon(client)
    no = booking["booking_no"]
    too_early = client.post(f"/api/bookings/{no}/changes", json={"new_pickup": "2027-04-10T11:00"})
    assert too_early.status_code == 422 and too_early.json()["errors"][0]["rule"] == "R2"
    change = client.post(f"/api/bookings/{no}/changes", json={"new_pickup": "2027-04-10T12:30"}).json()
    other = client.post(f"/api/changes/{change['change_id']}/accept", json={"company_id": "TX-JP-03"})
    assert other.status_code == 403                                     # not their booking
    r = client.post(f"/api/changes/{change['change_id']}/reject", json={"company_id": "TX-JP-01", "reason": "No driver"})
    assert r.json()["status"] == "REJECTED"
    assert client.get(f"/api/bookings/{no}").json()["pickup"] == "2027-04-10T11:30"   # unchanged


def test_cancel_booking_frees_the_car(client):
    booking = book_menon(client)
    no = booking["booking_no"]
    r = client.post(f"/api/bookings/{no}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"
    assert client.post(f"/api/bookings/{no}/cancel").status_code == 409            # only once
    assert client.get("/api/requests/REQ-0004").json()["status"] == "CANCELLED"
    post_menon(client, traveler_name="Next family")                                   # REQ-0005, same time
    assert assign(client, "REQ-0005", "TX-JP-01", "SC-3", 12500).status_code == 201  # SC-3 free again


# --- S1: shared ride ------------------------------------------------------------------

def test_shared_ride(client):
    # Menon (3 people, 3 large + 2 small bags) and a couple (2 people, 1 + 1 bags) on FL-401 to Ueno.
    post_menon(client)
    post_menon(client, traveler_name="Rao couple", child_ages=[], large_bags=1, small_bags=1, price_inr=11000)
    sakura = client.get("/api/suppliers/TX-JP-01/dashboard").json()
    menon = next(r for r in sakura["requests"] if r["request_id"] == "REQ-0004")
    partner = next(p for p in menon["share_with"] if p["request_id"] == "REQ-0005")
    assert partner["total_passengers"] == 5
    states = {v["vehicle_id"]: v["availability"]["state"] for v in partner["vehicles"]}
    assert states["SC-3"] == "AVAILABLE" and states["SC-1"] == "DOES_NOT_FIT"

    bad = client.post("/api/offers/shared", json={"request_ids": ["REQ-0004", "REQ-0005"], "company_id": "TX-JP-01",
                                                  "vehicle_id": "SC-1", "prices": [12500, 11500]})
    assert bad.status_code == 422 and bad.json()["errors"][0]["rule"] == "R5"     # 4 seats for 5 people
    r = client.post("/api/offers/shared", json={"request_ids": ["REQ-0004", "REQ-0005"], "company_id": "TX-JP-01",
                                                "vehicle_id": "SC-3", "prices": [12500, 11500]})
    assert r.status_code == 201
    a, b = r.json()["offers"]
    traveler_offer = client.get("/api/requests/REQ-0004/offers").json()[0]
    assert traveler_offer["shared"]["other_passengers"] == 2
    assert "with_traveler_name" not in traveler_offer["shared"]
    assert client.post(f"/api/offers/{a['offer_id']}/book").status_code == 201
    second = client.post(f"/api/offers/{b['offer_id']}/book")                  # same car, same ride: allowed
    assert second.status_code == 201 and second.json()["shared"]["total_passengers"] == 5
