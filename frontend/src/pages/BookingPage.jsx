import { useCallback, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api.js";
import BookingDetails from "../components/BookingDetails.jsx";
import { CancelBooking, ChangeSection } from "../components/ChangeRequest.jsx";
import { EmptyState, ErrorList, usePolling } from "../components/common.jsx";
import Icon from "../components/Icon.jsx";

// M5: the booking number opens a summary. A wrong number shows "not found".
// Refreshes every 5 s, so the traveler sees the supplier's answer to a change request.
export default function BookingPage() {
  const { bookingNo } = useParams();
  const [b, setB] = useState(null);
  const [notFound, setNotFound] = useState(false);
  const [errors, setErrors] = useState(null);

  const load = useCallback(() => {
    api
      .booking(bookingNo)
      .then((d) => {
        setB(d);
        setErrors(null);
      })
      .catch((e) => (e.status === 404 ? setNotFound(true) : setErrors(e.errors)));
  }, [bookingNo]);
  usePolling(load, notFound ? null : 5000);

  if (notFound)
    return (
      <EmptyState
        title="Booking not found"
        icon="ticket"
        action={
          <Link to="/track" className="btn btn-primary">
            Track a booking
          </Link>
        }
      >
        There is no booking with number {bookingNo}. Check the 10 digits and try again.
      </EmptyState>
    );
  if (errors) return <ErrorList errors={errors} showRules={false} />;
  if (!b) return <p className="muted">Loading…</p>;

  return (
    <>
      <Link to={`/traveler/requests/${b.request_id}`} className="back-link">
        <Icon name="back" size={16} /> Ride {b.request_id}
      </Link>
      <div className="booking-layout">
        <BookingDetails b={b} />
        <div className="booking-actions">
          <ChangeSection booking={b} onSent={load} />
          <CancelBooking booking={b} onCancelled={load} />
        </div>
      </div>
    </>
  );
}
