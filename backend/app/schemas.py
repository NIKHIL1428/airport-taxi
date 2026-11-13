"""Request bodies. Fields are loose on purpose: rules.py gives the clear, rule-based messages."""
from typing import Optional

from pydantic import BaseModel


class RideRequestIn(BaseModel):
    traveler_name: Optional[str] = None
    flight_id: Optional[str] = None
    hotel_id: Optional[str] = None
    adults: Optional[int] = None
    child_ages: list[int] = []
    large_bags: int = 0
    small_bags: int = 0
    pickup: Optional[str] = None      # YYYY-MM-DDTHH:MM, local time; empty = earliest pickup
    car_type: Optional[str] = None    # HATCHBACK | SEDAN | SUV | BUS | null (any)
    price_inr: Optional[int] = None


class OfferIn(BaseModel):
    """A supplier assigns one of its cars with a price (M3)."""
    request_id: Optional[str] = None
    company_id: Optional[str] = None
    vehicle_id: Optional[str] = None
    price_inr: Optional[int] = None
    hold_minutes: Optional[int] = None   # guaranteed window: car held for this traveler; empty = 5 minutes


class SharedOfferIn(BaseModel):
    """S1: a supplier assigns one car to two requests (same flight, same area), a price for each."""
    request_ids: list[str] = []
    company_id: Optional[str] = None
    vehicle_id: Optional[str] = None
    prices: list[Optional[int]] = []      # one price per request, in the same order
    hold_minutes: Optional[int] = None


class ChangeIn(BaseModel):
    """M7: a traveler asks to change a booking."""
    new_flight_id: Optional[str] = None   # empty = same flight
    new_pickup: Optional[str] = None      # empty = earliest pickup of the (new) flight


class DecisionIn(BaseModel):
    """A supplier accepts or rejects a change request for one of its bookings."""
    company_id: Optional[str] = None
    reason: Optional[str] = None


class BookingLookupIn(BaseModel):
    """Track a booking with the traveler's name and the booking number."""
    traveler_name: Optional[str] = None
    booking_no: Optional[str] = None
