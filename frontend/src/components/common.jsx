import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import Icon from "./Icon.jsx";
import { bagsText, fmtDateTime, fmtTime, inr, passengersText, titleCase } from "../format.js";

// Loads /api/catalog once and shares it between pages.
let catalogPromise = null;
export function useCatalog() {
  const [catalog, setCatalog] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    catalogPromise ??= api.catalog();
    catalogPromise.then(setCatalog).catch((e) => {
      catalogPromise = null;
      setError(e);
    });
  }, []);
  return { catalog, error };
}

// Calls `load` now and every `ms` while the page is open (so the traveler and supplier
// screens update each other during the demo without a manual refresh). `ms = null` stops it.
export function usePolling(load, ms = 5000) {
  const saved = useRef(load);
  saved.current = load;
  useEffect(() => {
    if (ms == null) return;
    saved.current();
    const timer = setInterval(() => saved.current(), ms);
    return () => clearInterval(timer);
  }, [ms]);
}

export function ErrorList({ errors, showRules = true }) {
  if (!errors?.length) return null;
  return (
    <div className="alert alert-error" role="alert">
      <ul>
        {errors.map((e, i) => (
          <li key={i}>
            {showRules && e.rule && /^(R\d|G\d)/.test(e.rule) && <span className="rule-tag">{e.rule}</span>}
            {e.message}
          </li>
        ))}
      </ul>
    </div>
  );
}

const STATUS_LABELS = {
  OPEN: "Open",
  BOOKED: "Booked",
  REJECTED: "Rejected",
  NOT_CHOSEN: "Not chosen",
  CAR_TAKEN: "Car taken",
  CONFIRMED: "Confirmed",
  CANCELLED: "Cancelled",
  WAITING: "Waiting",
  ACCEPTED: "Accepted",
};

export function StatusBadge({ status }) {
  return <span className={`badge badge-${status.toLowerCase()}`}>{STATUS_LABELS[status] || status}</span>;
}

// Seconds left, counting down every second from the backend's number (so the browser's clock
// doesn't matter). When it reaches 0, `onEnd` reloads the data.
function useCountdown(seconds, onEnd) {
  const [left, setLeft] = useState(seconds);
  const endRef = useRef(onEnd);
  endRef.current = onEnd;
  useEffect(() => {
    setLeft(seconds);
    if (!seconds) return;
    const deadline = Date.now() + seconds * 1000;
    const timer = setInterval(() => {
      const s = Math.max(0, Math.round((deadline - Date.now()) / 1000));
      setLeft(s);
      if (s === 0) {
        clearInterval(timer);
        endRef.current?.();
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [seconds]);
  return left;
}

const clock = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

// The guaranteed window of an offer. While it runs, the car is held for this traveler only.
// Afterwards the offer stays open, but the car is open to everyone and is checked when booking.
export function Guarantee({ seconds, onEnd, audience = "traveler" }) {
  const left = useCountdown(seconds, onEnd);
  if (seconds == null) return null;
  if (audience === "supplier") {
    return left > 0 ? (
      <span className={`countdown ${left <= 60 ? "countdown-soon" : ""}`}>
        <Icon name="clock" size={13} /> Held {clock(left)}
      </span>
    ) : (
      <span className="countdown">Not held</span>
    );
  }
  return left > 0 ? (
    <p className={`guarantee ${left <= 60 ? "guarantee-soon" : ""}`}>
      <Icon name="shield" size={16} /> Guaranteed confirmation if you book within <strong>{clock(left)}</strong>
    </p>
  ) : (
    <p className="guarantee-over">
      <Icon name="clock" size={14} /> The guaranteed time is over. This taxi is now open to other travelers too. You
      can still book it: we check it is free when you book.
    </p>
  );
}

// A number with − and + buttons. The value stays as typed, so the backend can give the clear message
// for a bad entry (for example a negative count), and the buttons never go past min or max.
export function Stepper({ id, label, value, onChange, min = 0, max = 99, hint }) {
  const n = Number(value);
  const current = value === "" || Number.isNaN(n) ? min : n;
  const step = (delta) => onChange(String(Math.min(max, Math.max(min, current + delta))));
  return (
    <div className="stepper">
      <span className="stepper-label" id={`${id}-label`}>
        {label}
      </span>
      <div className="stepper-control">
        <button type="button" onClick={() => step(-1)} disabled={current <= min} aria-label={`Decrease ${label}`}>
          −
        </button>
        <input
          id={id}
          inputMode="numeric"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-labelledby={`${id}-label`}
        />
        <button type="button" onClick={() => step(1)} disabled={current >= max} aria-label={`Increase ${label}`}>
          +
        </button>
      </div>
      {hint && <small className="muted">{hint}</small>}
    </div>
  );
}

export function EmptyState({ title, children, action, icon = "list" }) {
  return (
    <div className="card empty-state">
      <div className="empty-icon">
        <Icon name={icon} size={26} />
      </div>
      <h3>{title}</h3>
      {children && <p className="muted">{children}</p>}
      {action}
    </div>
  );
}

export function CarText({ v }) {
  return (
    <>
      {titleCase(v.type)} {v.vehicle_id} · {v.seats} seats · {v.large_bags} large + {v.small_bags} small bags
    </>
  );
}

// The details of a ride request. Suppliers also get the car's busy time.
export function RequestFacts({ r, audience = "traveler" }) {
  return (
    <dl className="facts">
      {audience === "supplier" && (
        <>
          <dt>Traveler</dt>
          <dd>{r.traveler_name}</dd>
        </>
      )}
      <dt>Flight</dt>
      <dd>
        {r.flight.flight_number} ({r.flight.flight_id}) {r.flight.from}→{r.flight.to} · lands{" "}
        {fmtDateTime(r.flight.arrival_local)}
      </dd>
      <dt>Hotel</dt>
      <dd>
        {r.hotel.name} · {r.hotel.city} / {r.hotel.area}
      </dd>
      <dt>Passengers</dt>
      <dd>
        {passengersText(r)} = {r.passengers}
      </dd>
      <dt>Bags</dt>
      <dd>{bagsText(r)}</dd>
      <dt>Pickup</dt>
      <dd>{fmtDateTime(r.pickup)}</dd>
      <dt>Car type</dt>
      <dd>{titleCase(r.car_type)}</dd>
      <dt>{audience === "supplier" ? "Traveler's price" : "Your price"}</dt>
      <dd>
        <strong>{inr(r.price_inr)}</strong>
        {r.route && (
          <span className="muted">
            {" "}
            (range {inr(r.route.price_min_inr)} – {inr(r.route.price_max_inr)})
          </span>
        )}
      </dd>
      {r.route && (
        <>
          <dt>Route</dt>
          <dd>
            {r.route.airport} → {r.route.area} · {r.route.distance_km} km · about {r.route.drive_minutes} min
          </dd>
        </>
      )}
      {audience === "supplier" && r.busy_window && (
        <>
          <dt>Car needed</dt>
          <dd>
            {fmtDateTime(r.busy_window.start)} – {fmtTime(r.busy_window.end)} (there and back)
          </dd>
        </>
      )}
    </dl>
  );
}
