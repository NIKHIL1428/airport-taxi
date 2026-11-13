"""FastAPI app: HTTP endpoints only. Logic lives in services.py and rules.py."""
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import services
from .config import FRONTEND_ORIGINS
from .data_store import get_catalog
from .db import connect, get_db, init_db, seed_open_requests
from .rules import CAR_TYPES
from .schemas import BookingLookupIn, ChangeIn, DecisionIn, OfferIn, RideRequestIn, SharedOfferIn
from .services import ApiError


@asynccontextmanager
async def lifespan(app: FastAPI):
    catalog = get_catalog()  # fails fast with a clear message if data/ is missing
    conn = connect()
    try:
        init_db(conn)
        seed_open_requests(conn, catalog.open_requests)
    finally:
        conn.close()
    yield


app = FastAPI(title="Airport Taxi → Ride Offers", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=FRONTEND_ORIGINS, allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------------------
# Errors: always {"errors": [{"rule", "message", "field"}]}
# ---------------------------------------------------------------------------

@app.exception_handler(ApiError)
async def api_error_handler(_: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status, content={"errors": [e.to_dict() for e in exc.errors]})


@app.exception_handler(Exception)
async def unexpected_error_handler(_: Request, exc: Exception):
    """Any bug: log the full traceback in the backend window, show a clear message on screen."""
    logging.getLogger("uvicorn.error").exception("Unexpected error")
    return JSONResponse(status_code=500, content={"errors": [{
        "rule": "SERVER", "field": None,
        "message": f"Server error: {type(exc).__name__}: {exc}. See the backend window for details."}]})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        loc = [str(x) for x in err["loc"] if x != "body"]
        field = loc[0] if loc else None
        label = (field or "value").replace("_", " ")
        if err["type"].startswith("int"):
            message = f"{label.capitalize()} must be a whole number."
        else:
            message = f"{label.capitalize()}: {err['msg']}."
        errors.append({"rule": "INPUT", "field": field, "message": message})
    return JSONResponse(status_code=422, content={"errors": errors})


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/catalog")
def catalog_endpoint():
    """Everything the request form and role picker need, in one call."""
    c = get_catalog()
    return {
        "arrival_airports": [
            {k: c.airports[code].get(k) for k in ("code", "name", "city", "serves_cities")}
            for code in c.arrival_airports
        ],
        "flights": [
            {k: f[k] for k in ("flight_id", "airline", "flight_number", "from", "to", "arrival_local")}
            for f in c.arriving_flights()
        ],
        "hotels": sorted(
            ({k: h[k] for k in ("hotel_id", "name", "city", "area")} for h in c.hotels.values()),
            key=lambda h: (h["city"], h["area"], h["name"]),
        ),
        "suppliers": [services.supplier_summary(s) for s in c.companies.values()],
        "car_types": list(CAR_TYPES),
    }


@app.get("/api/price-range")
def price_range(flight_id: str | None = None, hotel_id: str | None = None):
    return services.price_range(get_catalog(), flight_id, hotel_id)


# ---------------------------------------------------------------------------
# Traveler: ride requests (M1, M2 traveler side)
# ---------------------------------------------------------------------------

@app.post("/api/requests", status_code=201)
def create_request(body: RideRequestIn, conn=Depends(get_db)):
    return services.create_request(conn, get_catalog(), body.model_dump())


@app.get("/api/requests")
def list_requests(ids: str | None = None, conn=Depends(get_db)):
    """`ids` = comma-separated request IDs this traveler posted. Without it: all requests."""
    id_list = [i.strip() for i in ids.split(",") if i.strip()] if ids is not None else None
    return services.list_requests(conn, get_catalog(), id_list)


@app.get("/api/requests/by-name")
def find_request_by_name(name: str = "", conn=Depends(get_db)):
    """Find a ride by the traveler's unique name (declared before /{request_id} so it matches first)."""
    return services.find_request_by_name(conn, get_catalog(), name)


@app.get("/api/names/check")
def check_name(name: str = "", conn=Depends(get_db)):
    """Is this traveler name still free? Used live by the request form."""
    return services.name_availability(conn, name)


@app.get("/api/requests/{request_id}")
def get_request(request_id: str, conn=Depends(get_db)):
    return services.request_detail(conn, get_catalog(), request_id)


@app.get("/api/requests/{request_id}/offers")
def get_request_offers(request_id: str, conn=Depends(get_db)):
    """M4: every taxi assigned to this request, from all suppliers."""
    return services.request_offers(conn, get_catalog(), request_id)


# ---------------------------------------------------------------------------
# Offers (M3, M4, M6) and bookings (M5)
# ---------------------------------------------------------------------------

@app.post("/api/offers", status_code=201)
def create_offer(body: OfferIn, conn=Depends(get_db)):
    return services.create_offer(conn, get_catalog(), body.model_dump())


@app.post("/api/offers/shared", status_code=201)
def create_shared_offer(body: SharedOfferIn, conn=Depends(get_db)):
    """S1: one car for two families on the same flight to the same area."""
    return services.create_shared_offer(conn, get_catalog(), body.model_dump())


@app.post("/api/offers/{offer_id}/reject")
def reject_offer(offer_id: int, conn=Depends(get_db)):
    return services.reject_offer(conn, get_catalog(), offer_id)


@app.post("/api/offers/{offer_id}/book", status_code=201)
def book_offer(offer_id: int, conn=Depends(get_db)):
    return services.book_offer(conn, get_catalog(), offer_id)


@app.post("/api/bookings/lookup")
def lookup_booking(body: BookingLookupIn, conn=Depends(get_db)):
    """Track a booking: name and booking number must both match (declared before /{booking_no})."""
    return services.lookup_booking(conn, get_catalog(), body.traveler_name, body.booking_no)


@app.get("/api/bookings/{booking_no}")
def get_booking(booking_no: str, conn=Depends(get_db)):
    return services.booking_summary(conn, get_catalog(), booking_no)


# ---------------------------------------------------------------------------
# Change requests (M7, R9)
# ---------------------------------------------------------------------------

@app.post("/api/bookings/{booking_no}/changes", status_code=201)
def create_change(booking_no: str, body: ChangeIn, conn=Depends(get_db)):
    return services.create_change(conn, get_catalog(), booking_no, body.model_dump())


@app.post("/api/bookings/{booking_no}/cancel")
def cancel_booking(booking_no: str, conn=Depends(get_db)):
    """The traveler cancels the booking; the car is free again."""
    return services.cancel_booking(conn, get_catalog(), booking_no)


@app.post("/api/changes/{change_id}/accept")
def accept_change(change_id: int, body: DecisionIn, conn=Depends(get_db)):
    return services.accept_change(conn, get_catalog(), change_id, body.company_id or "")


@app.post("/api/changes/{change_id}/reject")
def reject_change(change_id: int, body: DecisionIn, conn=Depends(get_db)):
    return services.reject_change(conn, get_catalog(), change_id, body.company_id or "", body.reason)


# ---------------------------------------------------------------------------
# Supplier (M2)
# ---------------------------------------------------------------------------

@app.get("/api/suppliers")
def list_suppliers():
    return [services.supplier_summary(s) for s in get_catalog().companies.values()]


@app.get("/api/suppliers/{company_id}/dashboard")
def supplier_dashboard(company_id: str, conn=Depends(get_db)):
    return services.supplier_dashboard(conn, get_catalog(), company_id)


@app.get("/api/suppliers/{company_id}/changes")
def supplier_changes(company_id: str, conn=Depends(get_db)):
    return services.supplier_changes(conn, get_catalog(), company_id)


@app.get("/api/suppliers/{company_id}/offers")
def supplier_offers(company_id: str, conn=Depends(get_db)):
    return services.supplier_offers(conn, get_catalog(), company_id)
