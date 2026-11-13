# Airport Taxi → Ride Offers

Travelers post an airport-to-hotel ride with their own price. Taxi suppliers see only the requests they can serve and assign cars. Built for Problem 2 of the Booking.com intern hackathon.

## Start the app

Needs Python 3.10+ and Node 18+. First copy the data pack's `problem-2/` and `catalog/` folders into `data/`, unchanged.

**Windows**
```
setup.bat      (once)
start.bat
```

**macOS / Linux**
```
./setup.sh     (once)
./start.sh
```

Open http://localhost:5173. The API runs on http://localhost:8000 (docs at `/docs`).

Run the rule tests (from `backend/`): `.venv\Scripts\python -m pytest -q` (Windows) or `.venv/bin/python -m pytest -q`.

## Architecture

```
frontend (React + Vite) ──/api──► backend (FastAPI)
                                    ├─ rules.py       R1–R7 as pure functions (no DB, no HTTP)
                                    ├─ services.py    loads data + DB rows, calls rules
                                    ├─ main.py        HTTP endpoints only
                                    ├─ data_store.py  read-only JSON data pack, indexed in memory
                                    └─ db.py          SQLite: requests, offers, bookings, change requests
```

- **The backend holds all the logic.** The frontend only shows what the API returns. Every rule is written once in `rules.py`, and all endpoints use it.
- **Errors** always have the form `{"errors": [{"rule": "R3", "message": "...", "field": "price_inr"}]}`, so the screen can name the broken rule and highlight the field.
- **State** is stored in `backend/taxi.db` (SQLite), so it survives a refresh and a restart. The 3 open requests are loaded once at startup (`INSERT OR IGNORE`).
- **Time** is always the local time of the arrival airport, as the data dictionary says. There is no time zone conversion.

### Key rules

| Rule | Where | Notes |
|---|---|---|
| R1 | `resolve_trip`, `validate_request` | Flight and hotel are in the catalog, the airport serves the hotel's city, at least 1 adult, children aged 0–17 |
| R2 | `validate_request` | Pickup at least 60 min after landing. No pickup given = landing + 60 min |
| R3 | `check_price_in_range` | Both ends of the range allowed. Also used for supplier prices (R7) |
| R4 | `evaluate_supplier` | Airport, city/area, open at pickup (windows past midnight handled), a car that fits and is free |
| R5 | `car_fit_problems` | Seats ≥ adults + children, large and small bags checked separately, car type (G2) |
| R6 | `busy_window`, `overlaps` | Busy = [pickup, pickup + 2 × drive). Back-to-back rides (end == start) do not overlap. Busy times come from `booked_rides.json` + confirmed bookings |
| R7 | `check_assignment` | Lists every broken rule for an assigned car and price |

## Screens

Light and dark themes (or follow the system), switchable from the top bar; works on phones.

| Path | Who | What |
|---|---|---|
| `/` | Everyone | Home: "I'm travelling" or "I run a taxi company", and how it works |
| `/traveler` | Traveler | My rides as cards, filtered by stage (waiting, offers, booked, no ride, cancelled) |
| `/traveler/new` | Traveler | Ride request form with live price range and a live check that the name is free; "Fill Menon example" button |
| `/traveler/requests/:id` | Traveler | Taxis offered (sort, filter) with the guaranteed-confirmation countdown, Book / Reject; once booked: change request and cancel. If no supplier can serve: "No ride is available for your request." with a short "Why?" |
| `/booking/:number` | Traveler | Booking ticket, change request, cancel; a wrong number shows "Booking not found" |
| `/track` | Traveler | Track a booking with name + booking number, or find the ride by name alone |
| `/supplier` | Supplier | Choose your company |
| `/supplier/:id` | Supplier | KPIs; filters + "Choose a traveler" dropdown, then the request, car availability and the assign form; "My taxis"; "Change requests" |

Travelers never see other suppliers' reasons, rule codes or car busy times; suppliers see what they need to assign a car. Every car stays selectable in the assign form, so the backend can refuse a bad one with its rule.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/catalog` | Arrival airports, arriving flights, hotels, suppliers, car types |
| GET | `/api/price-range?flight_id=&hotel_id=` | Suggested range + earliest pickup (R1, R3) |
| POST | `/api/requests` | Create a ride request (M1). `traveler_name` is required and unique |
| GET | `/api/names/check?name=` | Is this traveler name still free? (live check in the form) |
| GET | `/api/requests/by-name?name=` | Find a ride by the traveler's unique name (shows the booking number) |
| GET | `/api/requests?ids=A,B` | The traveler's own requests |
| GET | `/api/requests/{id}` | Traveler view: details + availability ("No ride is available…" + one reason) |
| GET | `/api/requests/{id}/offers` | All taxis assigned to the request (M4) |
| POST | `/api/offers` | Supplier assigns a car + price (M3, R7, G1). `hold_minutes` (1–60, default 5): guaranteed window (see below) |
| POST | `/api/offers/shared` | S1: one car for two requests (`request_ids`, `vehicle_id`, `prices` one per family, `hold_minutes`) |
| POST | `/api/offers/{id}/reject` | Traveler rejects a taxi (R8) |
| POST | `/api/offers/{id}/book` | Traveler books a taxi; re-checks the car is free (M6) and returns the booking (R8) |
| GET | `/api/bookings/{number}` | Booking summary (M5); 404 if not found |
| POST | `/api/bookings/lookup` | Track: traveler name + booking number must both match |
| GET | `/api/suppliers/{id}/dashboard` | Open requests this supplier can serve, its cars, its offers (M2) |
| GET | `/api/suppliers/{id}/offers` | All taxis this supplier assigned, with booking numbers |
| POST | `/api/bookings/{number}/changes` | Traveler asks for a new flight and/or pickup (M7) |
| GET | `/api/suppliers/{id}/changes` | Change requests for this supplier's bookings, each with the R9 check |
| POST | `/api/bookings/{number}/cancel` | Traveler cancels the booking; the car is free again |
| POST | `/api/changes/{id}/accept` | Supplier accepts (body `company_id`); refused unless R9 holds |
| POST | `/api/changes/{id}/reject` | Supplier rejects (body `company_id`, optional `reason`); booking unchanged |

## Traveler names

Every ride request needs a traveler name, and **names are unique** (spaces and capitals are ignored, so "menon  FAMILY" = "Menon family"; the 3 preloaded names count too). The form checks the name live as you type. A traveler who lost the booking number types their name in "Forgot your booking number?" on My rides to open the ride, which shows the booking number. One name = one ride request, so a second ride needs another name (e.g. "Menon family 2").

## Change requests (M7, R9)

On the booking page the traveler picks a new flight and/or a new pickup time. With a new flight and no time, the pickup is 60 minutes after it lands.

- **Refused at once** (the traveler sees why): pickup less than 60 minutes after landing (R2), a flight to a different airport, an unknown flight, nothing changed, or another change still waiting.
- **The supplier** sees it under "Change requests", with the backend's R9 check: ✓ "pickup is valid and the car is free at the new time", or the reason it is not. **Accept** is only possible when R9 holds (checked again on accept, under the same lock as a booking). **Reject** takes an optional reason.
- **Accepted:** the booking, the ride request and the car's busy time move to the new flight/pickup; other travelers' open offers of that car for the new time become "Car taken".
- **Rejected:** the booking keeps its old flight and pickup. The traveler sees the result on the booking page (it refreshes every 5 s) and can then send another.

Assumption: the new flight must land at the **same airport**. The supplier, its car and the price were agreed for that airport; a different airport is a new ride request.

## Cancelling a booking

On the ride page and the booking page the traveler can **Cancel booking** (with a second click to confirm). The booking, the ride and its taxi become **Cancelled**; the car is free again at once (only confirmed bookings make a car busy); a waiting change request is closed; and other travelers' "Car taken" offers of that car become bookable again if the car is now free for their time. The supplier sees "Cancelled" in My taxis. A cancelled ride cannot be booked, changed or offered again: the traveler posts a new ride request.

## Guaranteed confirmation

When a supplier assigns a car, the traveler gets a **guaranteed window** (5 minutes by default; the supplier can set 1–60):

- **During the window** the car is *held* for that traveler: it counts as busy (R6) for every other request, so no other supplier offer or booking can take it. The traveler sees "✓ Guaranteed confirmation if you book within 4:59", and booking always succeeds.
- **After the window** the offer does **not** expire: it stays open, but the hold is released and the car is free for everyone again (the same traveler included). Booking then checks, at that moment, that the car is still free (M6); if another traveler holds or booked it, the traveler sees a warning and the booking is refused.
- Rejecting an offer, or booking another one, ends its hold at once.
- When a car is booked, other travelers' open offers of that car **for an overlapping time** become **"Car taken"** (they can never be booked). Offers of the same car for another time stay open: one car can do both rides.
- **Two Book clicks at the same moment:** `book_offer()` takes SQLite's write lock (`BEGIN IMMEDIATE`) before its availability check, so the second booking waits, then sees the first and is refused. A car can never be booked twice (test: `test_two_book_clicks_at_the_same_moment`).

In code: `busy_times_by_vehicle()` adds each active hold as a busy time tagged with its request, and `for_request()` removes a request's own holds before that request is checked.

## Shared ride (S1)

Two families on the **same flight** going to hotels in the **same area** can share one car.

- **Who can share:** same flight, same city and area (same route and drive time), pickups at most **60 minutes** apart, and the same car type if both chose one (`rules.plan_shared_ride`).
- **The car** must fit everyone together (R5: all passengers and all bags) and be free (R6). It picks up at the **later** of the two pickups, which still follows R2 for both. Its busy time is that pickup + 2 x drive time.
- **Supplier:** when a request can share, its panel shows a "Shared ride" form: choose the other traveler and a car (each car shows if it fits both), and set a price for each family (each inside the route's range, R3). A car that breaks a rule is refused with the rule, as for a normal assignment.
- **Traveler:** the offer shows a "Shared ride" label, the other family's people and bags (no name), and the pickup time if it is later than they asked. Each family books or rejects its own offer, so one family can say no and the other still rides.
- **No double booking:** both bookings of one shared ride use the same car at the same time. They do not block each other (they are one trip), but they block every other request (M6). The guarantee hold works the same way.
- **After booking:** cancelling one family keeps the other's booking. A change request is accepted only if the car is free at the new time. The other family's ride still counts as busy, so moving inside the shared trip is refused (R6). Once a change is accepted the ride is no longer shared.

In code: offers and bookings of a shared ride have the same `share_group`. In `for_request()`, a shared ride's busy time doesn't block the families that still have an open offer in that car.

## Status

- [x] M1 Ride request
- [x] M2 Supplier dashboard; traveler sees "No ride is available for your request." with a short reason
- [x] M3 Assign a car (refused car or price shows the rule it breaks)
- [x] M4 Book or reject (others become "not chosen")
- [x] M5 Booking summary (10-digit number, survives restart, "not found")
- [x] M6 No double booking (checked again at booking time)
- [x] M7 Flight change (see "Change requests" below)
- [x] G1 Several cars per supplier
- [x] G2 Car type (traveler chooses; other types refused with R5)
- [x] G4 Offer time: a guaranteed window (default 5 minutes) instead of a hard expiry, see "Guaranteed confirmation"
- [x] G5 Sort by price, filter by car type
- [x] S1 Shared ride (see "Shared ride" above)

## Tests

Run every test with one command from the project folder:

- Windows: `run_tests.bat`
- Mac/Linux: `./run_tests.sh`

(Run `setup.bat` / `setup.sh` once first; it installs pytest, httpx and vitest.)

### Backend: pytest (99 tests)

Run from `backend/`: `python -m pytest -v`

| File | What it tests |
|---|---|
| `tests/test_rules.py` (58) | The rules engine and services on small sample data in `tests/fixtures/data`: R1–R9, busy windows, guaranteed confirmation, "car taken", no double booking (including two bookings at the same moment), change requests, cancelling, unique names. |
| `tests/test_shared_rides.py` (19) | S1 shared ride: who can share, the car fits everyone, a price per family, both families book one car, holds, cancel and change. |
| `tests/test_api.py` (20) | The real FastAPI app over HTTP with TestClient, like the browser calls it: status codes (201/404/409/422/403), the JSON the frontend reads and the error format `{"errors": [{rule, field, message}]}`. One test per must-have M1–M7, plus the shared ride. Each test gets its own temporary database. |
| `tests/test_real_data.py` (2) | The full Menon demo on the real data pack. |

### Frontend: Vitest (35 tests)

Run from `frontend/`: `npm test`

| File | What it tests |
|---|---|
| `src/__tests__/format.test.js` (8) | Money, dates, durations and labels shown on screen. |
| `src/__tests__/myRides.test.js` (4) | "My rides" saved in the browser: remember, forget, bad data. |
| `src/__tests__/api.test.js` (6) | Each call hits the right URL and method; backend errors reach the page. |
| `src/__tests__/components.test.jsx` (12) | Status badges, the guarantee countdown, error lists, booking details. |
| `src/__tests__/sharedRide.test.jsx` (5) | The traveler's "Shared ride" note and the supplier's shared-ride form. |

## Known limitations

- Shared ride: the busy time uses the route's drive time; the extra stop when the two hotels differ is not added. At most two families share one car.

- No login, by design: the user picks a role. A traveler's "My rides" list is kept in their browser.
- No user accounts: anyone who knows a traveler's name can find that ride.
