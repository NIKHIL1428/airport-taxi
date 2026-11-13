import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import BookingDetails from "../components/BookingDetails.jsx";
import { CancelBooking, ChangeSection } from "../components/ChangeRequest.jsx";
import { ErrorList, RequestFacts, StatusBadge } from "../components/common.jsx";
import Icon from "../components/Icon.jsx";
import { rememberRequest } from "../myRides.js";

// Track a ride without an account, two ways:
//  - Booking number: the traveler's name AND the 10-digit number must both match.
//  - Name only: names are unique, so the name finds the one ride posted under it, with its booking number.
const TABS = [
  { id: "number", label: "Booking number" },
  { id: "name", label: "Forgot the number" },
];

export default function TrackBooking() {
  const [tab, setTab] = useState("number");
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Track my booking</h1>
          <p className="muted">Find your booking with its number, or find your ride with the name you used.</p>
        </div>
      </div>

      <div className="tabs" role="tablist" aria-label="How to find your booking">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={tab === t.id ? "active" : ""}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "number" ? <ByNumber /> : <ByName />}
    </>
  );
}

// The booking ticket plus the change and cancel panels, refreshed after each action.
function BookingWithActions({ booking, reload }) {
  return (
    <div className="booking-layout">
      <BookingDetails b={booking} />
      <div className="booking-actions">
        <ChangeSection booking={booking} onSent={reload} />
        <CancelBooking booking={booking} onCancelled={reload} />
      </div>
    </div>
  );
}

function ByNumber() {
  const [name, setName] = useState("");
  const [number, setNumber] = useState("");
  const [booking, setBooking] = useState(null);
  const [errors, setErrors] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setErrors(null);
    setBooking(null);
    setBusy(true);
    try {
      setBooking(await api.lookupBooking(name, number));
    } catch (err) {
      setErrors(err.errors);
    } finally {
      setBusy(false);
    }
  }

  const reload = useCallback(() => {
    if (booking) api.booking(booking.booking_no).then(setBooking).catch(() => {});
  }, [booking]);

  return (
    <>
      <form className="card form-compact" onSubmit={submit} noValidate>
        <p className="muted small">Enter the name you used for the ride and your 10-digit booking number.</p>
        <label>
          Your name
          <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
        </label>
        <label>
          Booking number
          <input value={number} onChange={(e) => setNumber(e.target.value)} inputMode="numeric" placeholder="10 digits" />
        </label>
        <button className="btn btn-primary" disabled={busy}>
          {busy ? "Checking…" : "Find my booking"}
        </button>
      </form>

      <ErrorList errors={errors} showRules={false} />
      {booking && <BookingWithActions booking={booking} reload={reload} />}
    </>
  );
}

function ByName() {
  const [name, setName] = useState("");
  const [ride, setRide] = useState(null);
  const [booking, setBooking] = useState(null);
  const [errors, setErrors] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setErrors(null);
    setRide(null);
    setBooking(null);
    setBusy(true);
    try {
      const found = await api.findByName(name);
      rememberRequest(found.request_id);
      setRide(found);
      setBooking(found.booking_no ? await api.booking(found.booking_no) : null);
    } catch (err) {
      setErrors(err.errors);
    } finally {
      setBusy(false);
    }
  }

  const reload = useCallback(() => {
    if (booking) api.booking(booking.booking_no).then(setBooking).catch(() => {});
  }, [booking]);

  return (
    <>
      <form className="card form-compact" onSubmit={submit} noValidate>
        <p className="muted small">
          Names are unique on this platform, so the name you used finds your ride and its booking number.
        </p>
        <label>
          The name you used for the ride
          <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
        </label>
        <button className="btn btn-primary" disabled={busy}>
          {busy ? "Searching…" : "Find my ride"}
        </button>
      </form>

      <ErrorList errors={errors} showRules={false} />

      {ride && !booking && (
        <section className="card summary-card">
          <div className="offer-toolbar">
            <h2>
              Ride {ride.request_id} <StatusBadge status={ride.status} />
            </h2>
            <Link to={`/traveler/requests/${ride.request_id}`} className="btn btn-primary">
              See taxis offered <Icon name="arrow" size={16} />
            </Link>
          </div>
          <p className="muted small">This ride is not booked yet, so it has no booking number.</p>
          <RequestFacts r={ride} />
        </section>
      )}
      {booking && <BookingWithActions booking={booking} reload={reload} />}
    </>
  );
}
