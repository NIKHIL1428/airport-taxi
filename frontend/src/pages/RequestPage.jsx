import { useCallback, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api.js";
import { CancelBooking, ChangeSection } from "../components/ChangeRequest.jsx";
import { CarText, EmptyState, ErrorList, Guarantee, RequestFacts, StatusBadge, usePolling } from "../components/common.jsx";
import Icon, { Avatar, Stars } from "../components/Icon.jsx";
import { SharedNote } from "../components/SharedRide.jsx";
import { fmtDateTime, inr, titleCase } from "../format.js";
import { forgetRequests, rememberRequest } from "../myRides.js";

// One taxi offered by a supplier: Book or Reject (M4, R8), with its guaranteed window.
function OfferCard({ offer, canAct, onBook, onReject, onGuaranteeEnd, busy, errors, yourPickup }) {
  const open = offer.status === "OPEN";
  return (
    <article className={`card offer ${open ? "" : "offer-closed"}`}>
      <div className="offer-main">
        <div className="offer-company">
          <Avatar name={offer.company_name} size={48} />
          <div>
            <h3>{offer.company_name}</h3>
            <div className="offer-meta">
              <Stars value={offer.rating} />
              <span aria-hidden="true">·</span>
              <span>
                <Icon name="car" size={15} /> <CarText v={offer.vehicle} />
              </span>
            </div>
          </div>
        </div>
        <div className="offer-price">
          <span className="small">Total for this ride</span>
          <strong>{inr(offer.price_inr)}</strong>
          {!open && <StatusBadge status={offer.status} />}
        </div>
      </div>
      <SharedNote shared={offer.shared} yourPickup={yourPickup} />
      {open && canAct && <Guarantee seconds={offer.guarantee_seconds_left} onEnd={onGuaranteeEnd} />}
      {offer.warning && <p className="text-warn small">⚠ {offer.warning}</p>}
      {offer.status === "CAR_TAKEN" && (
        <p className="muted small">Another traveler booked this car for the same time. Please choose another taxi.</p>
      )}
      <ErrorList errors={errors} showRules={false} />
      {open && canAct && (
        <div className="actions">
          <button type="button" className="btn" disabled={busy} onClick={() => onReject(offer)}>
            Reject
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy || Boolean(offer.warning)}
            onClick={() => onBook(offer)}
          >
            {busy ? "Booking…" : "Book this taxi"}
          </button>
        </div>
      )}
    </article>
  );
}

export default function RequestPage() {
  const { requestId } = useParams();
  const navigate = useNavigate();
  const [ride, setRide] = useState(null);
  const [offers, setOffers] = useState([]);
  const [booking, setBooking] = useState(null); // once booked: for the change and cancel panels
  const [errors, setErrors] = useState(null);
  const [notFound, setNotFound] = useState(false);
  const [offerErrors, setOfferErrors] = useState({});
  const [busyOffer, setBusyOffer] = useState(null);
  const [sort, setSort] = useState("price-asc");
  const [typeFilter, setTypeFilter] = useState("");

  const load = useCallback(() => {
    Promise.all([api.getRequest(requestId), api.requestOffers(requestId)])
      .then(async ([r, o]) => {
        setRide(r);
        setOffers(o);
        setBooking(r.booking_no ? await api.booking(r.booking_no) : null);
        setErrors(null);
        rememberRequest(requestId); // opened by link: keep it in "My rides"
      })
      .catch((e) => {
        if (e.status === 404) {
          setNotFound(true); // stops the polling below
          forgetRequests([requestId]);
        } else {
          setErrors(e.errors);
        }
      });
  }, [requestId]);
  usePolling(load, notFound ? null : 5000);

  // G5: sort by price, filter by car type (display only; data comes from the backend).
  const shown = useMemo(() => {
    const list = offers.filter((o) => !typeFilter || o.vehicle.type === typeFilter);
    const by = {
      "price-asc": (a, b) => a.price_inr - b.price_inr,
      "price-desc": (a, b) => b.price_inr - a.price_inr,
      rating: (a, b) => (b.rating || 0) - (a.rating || 0),
    }[sort];
    return [...list].sort(by);
  }, [offers, sort, typeFilter]);
  const types = [...new Set(offers.map((o) => o.vehicle.type))];

  async function act(offer, action) {
    setBusyOffer(offer.offer_id);
    setOfferErrors((e) => ({ ...e, [offer.offer_id]: null }));
    try {
      if (action === "book") {
        const b = await api.bookOffer(offer.offer_id);
        navigate(`/booking/${b.booking_no}`);
        return;
      }
      await api.rejectOffer(offer.offer_id);
      load();
    } catch (err) {
      setOfferErrors((e) => ({ ...e, [offer.offer_id]: err.errors }));
      load();
    } finally {
      setBusyOffer(null);
    }
  }

  if (notFound)
    return (
      <EmptyState
        title="Ride not found"
        icon="search"
        action={
          <Link to="/traveler" className="btn btn-primary">
            Back to my rides
          </Link>
        }
      >
        There is no ride {requestId}. It may have been removed when the app's data was reset.
      </EmptyState>
    );
  if (errors) return <ErrorList errors={errors} showRules={false} />;
  if (!ride) return <p className="muted">Loading your ride…</p>;

  const av = ride.availability;
  const open = ride.status === "OPEN";
  const noRide = open && av && !av.available && offers.length === 0;

  return (
    <>
      <Link to="/traveler" className="back-link">
        <Icon name="back" size={16} /> My rides
      </Link>
      <div className="page-head">
        <h1>
          Ride {ride.request_id} <StatusBadge status={ride.status} />
        </h1>
      </div>

      {ride.status === "BOOKED" && (
        <div className="alert alert-success">
          <strong>Your taxi is booked.</strong>
          <span>
            Booking number{" "}
            <Link to={`/booking/${ride.booking_no}`}>
              <strong>{ride.booking_no}</strong>
            </Link>
          </span>
        </div>
      )}

      {ride.status === "CANCELLED" && (
        <div className="alert alert-error">
          <strong>You cancelled this ride.</strong>
          <span>
            Booking {ride.booking_no} is cancelled and the taxi is free for other travelers.{" "}
            <Link to="/traveler/new">Request a new ride</Link>
          </span>
        </div>
      )}

      {open && av && !av.available && (
        <div className="alert alert-error">
          <strong>{av.message}</strong>
          {av.reason && (
            <details className="why">
              <summary>Why?</summary>
              {av.reason}
            </details>
          )}
        </div>
      )}

      <div className="card ride-hero">
        <div>
          <h2>
            {ride.flight.to} → {ride.hotel.name}
          </h2>
          <p>
            <Icon name="calendar" size={15} /> Pickup {fmtDateTime(ride.pickup)} · {ride.passengers} passenger
            {ride.passengers > 1 ? "s" : ""}
          </p>
        </div>
        <div className="price-tag">
          <small>Your price</small>
          {inr(ride.price_inr)}
        </div>
      </div>

      {booking && (
        <div className="booking-actions">
          <ChangeSection booking={booking} onSent={load} />
          <CancelBooking booking={booking} onCancelled={load} />
        </div>
      )}

      <div className={noRide ? "" : "two-col"}>
        {!noRide && (
          <section>
            <div className="offer-toolbar">
              <h2>
                Taxis offered{offers.length > 0 && <span className="muted"> ({offers.length})</span>}
              </h2>
              {offers.length > 1 && (
                <div className="controls">
                  <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort taxis">
                    <option value="price-asc">Price: low to high</option>
                    <option value="price-desc">Price: high to low</option>
                    <option value="rating">Rating</option>
                  </select>
                  <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} aria-label="Filter by car type">
                    <option value="">All car types</option>
                    {types.map((t) => (
                      <option key={t} value={t}>
                        {titleCase(t)}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>
            {offers.length === 0 && open && av?.available && (
              <div className="card empty-state">
                <div className="empty-icon">
                  <Icon name="clock" size={26} />
                </div>
                <h3>Waiting for taxi companies</h3>
                <p className="muted">
                  Companies are looking at your request. Each offer comes with a few minutes of guaranteed
                  confirmation: book within that time and the taxi is yours.
                </p>
              </div>
            )}
            {shown.map((o) => (
              <OfferCard
                key={o.offer_id}
                offer={o}
                canAct={open}
                busy={busyOffer === o.offer_id}
                errors={offerErrors[o.offer_id]}
                onBook={(x) => act(x, "book")}
                onReject={(x) => act(x, "reject")}
                onGuaranteeEnd={load}
                yourPickup={ride.pickup}
              />
            ))}
            {offers.length > 0 && shown.length === 0 && <p className="muted">No taxis of this type.</p>}
          </section>
        )}

        <section>
          <div className="card summary-card">
            <h2>Ride details</h2>
            <RequestFacts r={ride} />
          </div>
        </section>
      </div>
    </>
  );
}
