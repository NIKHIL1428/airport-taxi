import { CarText, StatusBadge } from "./common.jsx";
import { SharedNote } from "./SharedRide.jsx";
import Icon, { Stars } from "./Icon.jsx";
import { bagsText, fmtDateTime, inr, passengersText } from "../format.js";

const STEPS = ["Request posted", "Taxi offered", "Booking confirmed"];

// The full details of one booking (M5). Used by the booking page, the ride page's link and Track booking.
export default function BookingDetails({ b }) {
  const cancelled = b.status === "CANCELLED";
  const changed = b.changes?.some((c) => c.status === "ACCEPTED");
  return (
    <article className={`card booking ${cancelled ? "booking-cancelled" : ""}`}>
      <header className="booking-hero">
        <span className="check-bubble">
          <Icon name={cancelled ? "back" : "check"} size={24} />
        </span>
        <div>
          <h2>{cancelled ? "This booking was cancelled" : "Your taxi is booked"}</h2>
          <p>
            {cancelled
              ? "The taxi is free for other travelers. Post a new ride request if you still need one."
              : `From ${b.flight.to} to ${b.hotel.name}, picking up ${fmtDateTime(b.pickup)}.`}
          </p>
        </div>
      </header>

      {!cancelled && (
        <ol className="steps" aria-label="Booking progress">
          {STEPS.map((step) => (
            <li key={step} className="done">
              {step}
            </li>
          ))}
        </ol>
      )}

      <div className="booking-ticket">
        <div>
          <p className="booking-label">Booking number</p>
          <p className="booking-no">{b.booking_no}</p>
        </div>
        <StatusBadge status={b.status} />
      </div>

      <div className="booking-body">
        <section>
          <h4>Trip</h4>
          <dl className="facts">
            <dt>Traveler</dt>
            <dd>{b.traveler_name}</dd>
            <dt>Flight</dt>
            <dd>
              {b.flight.flight_number} ({b.flight.flight_id}) · {b.flight.from} → {b.flight.to}
              <br />
              <span className="muted">lands {fmtDateTime(b.flight.arrival_local)}</span>
            </dd>
            <dt>Hotel</dt>
            <dd>
              {b.hotel.name}
              <br />
              <span className="muted">
                {b.hotel.city} / {b.hotel.area}
              </span>
            </dd>
            <dt>Pickup</dt>
            <dd>
              <strong>{fmtDateTime(b.pickup)}</strong> at {b.flight.to}
              {changed && <span className="muted small"> (changed)</span>}
            </dd>
          </dl>
        </section>

        <section>
          <h4>Taxi</h4>
          <dl className="facts">
            <dt>Company</dt>
            <dd>
              {b.supplier.name}
              <br />
              <Stars value={b.supplier.rating} />
            </dd>
            <dt>Car</dt>
            <dd>
              <CarText v={b.vehicle} />
            </dd>
            <dt>Passengers</dt>
            <dd>{passengersText(b)}</dd>
            <dt>Bags</dt>
            <dd>{bagsText(b)}</dd>
          </dl>
        </section>
      </div>

      {!cancelled && <SharedNote shared={b.shared} />}

      <div className="booking-total">
        <span>Total fare</span>
        <strong>{inr(b.price_inr)}</strong>
      </div>
    </article>
  );
}
