import { useMemo, useState } from "react";
import { api } from "../api.js";
import { ErrorList, StatusBadge, useCatalog } from "./common.jsx";
import Icon from "./Icon.jsx";
import { fmtDateTime } from "../format.js";

// M7 change requests and cancelling a booking. Shared by the booking page, the ride page and Track booking.

function ChangeHistory({ changes }) {
  if (!changes.length) return null;
  return (
    <ul className="changes">
      {changes.map((c) => (
        <li key={c.change_id}>
          <div className="change-line">
            <StatusBadge status={c.status} />
            <span>
              {c.new_flight ? `Flight ${c.new_flight.flight_number} (${c.new_flight.flight_id}), ` : "Same flight, "}
              pickup <strong>{fmtDateTime(c.resulting_pickup)}</strong>
            </span>
          </div>
          <div className="muted small">
            Was {c.old_flight_id}, {fmtDateTime(c.old_pickup)}
          </div>
          {c.status === "WAITING" && <div className="muted small">Waiting for the taxi company to answer.</div>}
          {c.status === "ACCEPTED" && <div className="text-ok small">Your booking now uses this flight and pickup.</div>}
          {c.status === "REJECTED" && (
            <div className="text-danger small">Rejected: {c.reason}. Your booking is unchanged.</div>
          )}
        </li>
      ))}
    </ul>
  );
}

// M7: flight changed? Ask the taxi company for a new flight or pickup time.
export function ChangeSection({ booking, onSent }) {
  if (booking.status !== "CONFIRMED") {
    return booking.changes?.length ? (
      <section className="card action-card">
        <h2>Change requests</h2>
        <ChangeHistory changes={booking.changes} />
      </section>
    ) : null;
  }
  return <ChangeForm booking={booking} onSent={onSent} />;
}

function ChangeForm({ booking, onSent }) {
  const { catalog } = useCatalog();
  const [flightId, setFlightId] = useState("");
  const [pickup, setPickup] = useState("");
  const [errors, setErrors] = useState(null);
  const [sending, setSending] = useState(false);
  const waiting = booking.changes.some((c) => c.status === "WAITING");

  // Only flights to the same airport: the taxi and price were agreed for that airport.
  const flights = useMemo(
    () => (catalog?.flights || []).filter((f) => f.to === booking.flight.to && f.flight_id !== booking.flight.flight_id),
    [catalog, booking.flight.to, booking.flight.flight_id]
  );

  async function send(e) {
    e.preventDefault();
    setErrors(null);
    setSending(true);
    try {
      await api.createChange(booking.booking_no, { new_flight_id: flightId || null, new_pickup: pickup || null });
      setFlightId("");
      setPickup("");
      onSent();
    } catch (err) {
      setErrors(err.errors);
    } finally {
      setSending(false);
    }
  }

  return (
    <section className="card action-card">
      <div className="action-head">
        <span className="action-icon">
          <Icon name="plane" size={18} />
        </span>
        <div>
          <h2>Flight changed?</h2>
          <p className="muted small">
            Ask {booking.supplier.name} for a new flight or pickup time. They can accept only if the new pickup is at
            least 60 minutes after landing and the same car is free then.
          </p>
        </div>
      </div>
      <ChangeHistory changes={booking.changes} />
      {waiting ? (
        <p className="muted small">You can send another change once the taxi company has answered.</p>
      ) : (
        <form className="change-form" onSubmit={send} noValidate>
          <div className="row">
            <label>
              New flight (to {booking.flight.to})
              <select value={flightId} onChange={(e) => setFlightId(e.target.value)}>
                <option value="">Same flight ({booking.flight.flight_id})</option>
                {flights.map((f) => (
                  <option key={f.flight_id} value={f.flight_id}>
                    {f.flight_id} · {f.flight_number} {f.from}→{f.to} · lands {fmtDateTime(f.arrival_local)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              New pickup time (optional)
              <input type="datetime-local" value={pickup} onChange={(e) => setPickup(e.target.value)} />
              <small className="muted">Empty with a new flight = 60 min after it lands</small>
            </label>
          </div>
          <ErrorList errors={errors} showRules={false} />
          <button className="btn btn-primary" disabled={sending}>
            {sending ? "Sending…" : "Send change request"}
          </button>
        </form>
      )}
    </section>
  );
}

// Cancel the booking, with a second click to confirm. The car is free again at once.
export function CancelBooking({ booking, onCancelled }) {
  const [asking, setAsking] = useState(false);
  const [errors, setErrors] = useState(null);
  const [busy, setBusy] = useState(false);
  if (booking.status !== "CONFIRMED") return null;

  async function cancel() {
    setBusy(true);
    setErrors(null);
    try {
      await api.cancelBooking(booking.booking_no);
      setAsking(false);
      onCancelled();
    } catch (err) {
      setErrors(err.errors);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card action-card cancel-box">
      {!asking ? (
        <div className="cancel-row">
          <div>
            <h3>Don't need the taxi any more?</h3>
            <p className="muted small">Cancelling frees the car for other travelers straight away.</p>
          </div>
          <button type="button" className="btn btn-danger-outline" onClick={() => setAsking(true)}>
            Cancel booking
          </button>
        </div>
      ) : (
        <>
          <p>
            <strong>Cancel booking {booking.booking_no}?</strong> {booking.supplier.name} will be told and the taxi
            will be given to other travelers. This cannot be undone.
          </p>
          <div className="actions">
            <button type="button" className="btn" disabled={busy} onClick={() => setAsking(false)}>
              Keep my booking
            </button>
            <button type="button" className="btn btn-danger" disabled={busy} onClick={cancel}>
              {busy ? "Cancelling…" : "Yes, cancel booking"}
            </button>
          </div>
        </>
      )}
      <ErrorList errors={errors} showRules={false} />
    </section>
  );
}
