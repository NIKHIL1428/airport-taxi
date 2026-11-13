"""The 4-minute demo script, run against the real data pack in ../data (skipped if it is missing).

Run from backend/:  python -m pytest -q
"""
from pathlib import Path

import pytest

from app import services
from app.data_store import Catalog
from app.db import connect, init_db, seed_open_requests

DATA = Path(__file__).resolve().parents[2] / "data"
pytestmark = pytest.mark.skipif(not (DATA / "problem-2").exists(), reason="data pack not copied into data/")

MENON = {"traveler_name": "Menon family", "flight_id": "FL-401", "hotel_id": "HTL-TYO-004",
         "adults": 2, "child_ages": [6], "large_bags": 3, "small_bags": 2,
         "pickup": "2027-04-10T11:30", "car_type": None, "price_inr": 12000}


@pytest.fixture
def env(tmp_path):
    catalog = Catalog.load(DATA)
    conn = connect(tmp_path / "real.db")
    init_db(conn)
    seed_open_requests(conn, catalog.open_requests)
    yield conn, catalog
    conn.close()


def test_menon_demo_script(env):
    conn, catalog = env
    req = services.create_request(conn, catalog, MENON)
    assert req["request_id"] == "REQ-0004"
    assert req["route"]["price_min_inr"] == 10200 and req["route"]["price_max_inr"] == 16800

    # Two suppliers see it: Sakura Cabs and Edo Premium Cars
    seen = [c for c in catalog.companies if any(
        r["request_id"] == "REQ-0004" for r in services.supplier_dashboard(conn, catalog, c)["requests"])]
    assert seen == ["TX-JP-01", "TX-JP-03"]

    # One refused car: SC-2 is busy 11:00-14:00 (RIDE-0001)
    with pytest.raises(services.ApiError) as exc:
        services.create_offer(conn, catalog, {"request_id": "REQ-0004", "company_id": "TX-JP-01",
                                              "vehicle_id": "SC-2", "price_inr": 12000})
    assert "R6" in {e.rule for e in exc.value.errors}

    sakura = services.create_offer(conn, catalog, {"request_id": "REQ-0004", "company_id": "TX-JP-01",
                                                   "vehicle_id": "SC-3", "price_inr": 12500})
    edo = services.create_offer(conn, catalog, {"request_id": "REQ-0004", "company_id": "TX-JP-03",
                                                "vehicle_id": "EP-2", "price_inr": 13000})
    services.reject_offer(conn, catalog, edo["offer_id"])
    booking = services.book_offer(conn, catalog, sakura["offer_id"])
    assert booking["vehicle"]["vehicle_id"] == "SC-3"
    assert services.booking_summary(conn, catalog, booking["booking_no"])["hotel"]["name"] == "Ueno Garden Inn"


def test_seeded_request_with_no_ride(env):
    conn, catalog = env
    view = services.request_detail(conn, catalog, "REQ-0002")   # Osaka, SEDAN only: no Kansai sedan
    assert view["availability"]["available"] is False
    assert view["availability"]["message"] == "No ride is available for your request."


def test_menon_change_request_on_real_data(env):
    conn, catalog = env
    services.create_request(conn, catalog, MENON)
    o = services.create_offer(conn, catalog, {"request_id": "REQ-0004", "company_id": "TX-JP-01",
                                              "vehicle_id": "SC-3", "price_inr": 12500})
    no = services.book_offer(conn, catalog, o["offer_id"])["booking_no"]
    ch = services.create_change(conn, catalog, no, {"new_flight_id": "FL-402"})     # NRT, 11 Apr 10:30
    assert ch["resulting_pickup"] == "2027-04-11T11:30"
    services.accept_change(conn, catalog, ch["change_id"], "TX-JP-01")
    b = services.booking_summary(conn, catalog, no)
    assert (b["flight"]["flight_id"], b["pickup"]) == ("FL-402", "2027-04-11T11:30")
