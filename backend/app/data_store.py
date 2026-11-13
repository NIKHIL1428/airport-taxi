"""Loads the read-only JSON data pack into memory once, with lookup indexes.

The files are never written to. Everything the app creates lives in SQLite (db.py).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .config import DATA_DIR


def _read(path: Path):
    if not path.exists():
        raise FileNotFoundError(
            f"Data file not found: {path}. Copy the data pack's `data/` folder "
            f"(with problem-2/ and catalog/) into the project root."
        )
    with path.open(encoding="utf-8") as f:
        return json.load(f)


@dataclass
class Catalog:
    flights: dict[str, dict] = field(default_factory=dict)       # flight_id -> flight
    hotels: dict[str, dict] = field(default_factory=dict)        # hotel_id -> hotel
    airports: dict[str, dict] = field(default_factory=dict)      # code -> airport
    routes: dict[tuple, dict] = field(default_factory=dict)      # (airport, city, area) -> route
    companies: dict[str, dict] = field(default_factory=dict)     # company_id -> supplier
    vehicles: dict[str, dict] = field(default_factory=dict)      # vehicle_id -> car (+ company_id)
    booked_rides: list[dict] = field(default_factory=list)
    open_requests: list[dict] = field(default_factory=list)

    @property
    def arrival_airports(self) -> list[str]:
        """Airports where taxis pick up: the ones that serve at least one city."""
        return sorted(code for code, a in self.airports.items() if a.get("serves_cities"))

    def arriving_flights(self) -> list[dict]:
        """Only flights that land at an airport we serve (NRT, HND, KIX, DXB, AUH)."""
        codes = set(self.arrival_airports)
        flights = [f for f in self.flights.values() if f["to"] in codes]
        return sorted(flights, key=lambda f: (f["arrival_local"], f["flight_id"]))

    @classmethod
    def load(cls, data_dir: Path) -> "Catalog":
        p2, cat = data_dir / "problem-2", data_dir / "catalog"
        c = cls()
        c.flights = {f["flight_id"]: f for f in _read(cat / "flights.json")}
        c.hotels = {h["hotel_id"]: h for h in _read(cat / "hotels.json")}
        c.airports = {a["code"]: a for a in _read(cat / "airports.json")}
        c.routes = {(r["airport"], r["city"], r["area"]): r for r in _read(p2 / "routes.json")}
        c.companies = {s["company_id"]: s for s in _read(p2 / "taxi_companies.json")}
        for company in c.companies.values():
            for v in company["vehicles"]:
                c.vehicles[v["vehicle_id"]] = {**v, "company_id": company["company_id"]}
        c.booked_rides = _read(p2 / "booked_rides.json")
        c.open_requests = _read(p2 / "open_requests.json")
        return c


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    return Catalog.load(DATA_DIR)
