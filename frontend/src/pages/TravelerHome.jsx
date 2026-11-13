import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { EmptyState, ErrorList, StatusBadge, usePolling } from "../components/common.jsx";
import Icon from "../components/Icon.jsx";
import { fmtDateTime, inr } from "../format.js";
import { forgetRequests, getMyRequestIds } from "../myRides.js";

// One label per ride, used for the card, the filter chips and the counts.
function rideStage(r) {
  if (r.status === "BOOKED") return "BOOKED";
  if (r.status === "CANCELLED") return "CANCELLED";
  if (r.availability && !r.availability.available) return "NO_RIDE";
  if (r.open_offer_count > 0) return "OFFERED";
  return "WAITING";
}

const STAGE_LABELS = {
  WAITING: "Waiting for offers",
  OFFERED: "Offers received",
  BOOKED: "Booked",
  NO_RIDE: "No ride available",
  CANCELLED: "Cancelled",
};

const FILTERS = [{ value: "ALL", label: "All rides" }, ...Object.entries(STAGE_LABELS).map(([value, label]) => ({ value, label }))];

function RideStage({ r }) {
  const stage = rideStage(r);
  if (stage === "BOOKED") return <span className="stage stage-offers">Booked · {r.booking_no}</span>;
  if (stage === "NO_RIDE") return <span className="stage stage-none">No ride available</span>;
  if (stage === "CANCELLED") return <span className="stage stage-none">Cancelled · {r.booking_no}</span>;
  if (stage === "OFFERED")
    return (
      <span className="stage stage-offers">
        {r.open_offer_count} taxi{r.open_offer_count > 1 ? "s" : ""} offered
      </span>
    );
  return <span className="stage stage-wait">Waiting for offers</span>;
}

function RideCard({ r }) {
  return (
    <Link to={`/traveler/requests/${r.request_id}`} className="card card-link ride-card">
      <div className="ride-top">
        <span className="ride-id">{r.request_id}</span>
        <StatusBadge status={r.status} />
      </div>
      <div className="ride-route">
        <div className="ride-route-line">
          <Icon name="plane" size={18} />
          {r.flight.to}
          <Icon name="arrow" size={16} className="muted" />
          <Icon name="bed" size={18} />
          <span className="ellipsis">{r.hotel.name}</span>
        </div>
        <div className="ride-sub">
          <Icon name="calendar" size={15} />
          {fmtDateTime(r.pickup)}
          <span aria-hidden="true">·</span>
          <Icon name="user" size={15} />
          {r.passengers} passenger{r.passengers > 1 ? "s" : ""}
        </div>
      </div>
      <div className="ride-foot">
        <RideStage r={r} />
        <span className="price-tag">
          <small>Your price</small>
          {inr(r.price_inr)}
        </span>
      </div>
    </Link>
  );
}

export default function TravelerHome() {
  const [requests, setRequests] = useState(null);
  const [errors, setErrors] = useState(null);
  const [filter, setFilter] = useState("ALL");

  const load = useCallback(() => {
    const ids = getMyRequestIds();
    api
      .listRequests(ids)
      .then((d) => {
        // Rides the backend no longer has (database reset) are forgotten, so they stop being asked for.
        const found = new Set(d.map((r) => r.request_id));
        forgetRequests(ids.filter((id) => !found.has(id)));
        setRequests(d);
        setErrors(null);
      })
      .catch((e) => setErrors(e.errors));
  }, []);
  usePolling(load, 8000);

  const counts = useMemo(() => {
    const c = { ALL: requests?.length || 0 };
    for (const r of requests || []) c[rideStage(r)] = (c[rideStage(r)] || 0) + 1;
    return c;
  }, [requests]);

  const shown = useMemo(
    () => (requests || []).filter((r) => filter === "ALL" || rideStage(r) === filter),
    [requests, filter]
  );

  return (
    <>
      <div className="page-head">
        <div>
          <h1>My rides</h1>
          <p className="muted">Ride requests you posted from this browser.</p>
        </div>
        <Link to="/traveler/new" className="btn btn-primary">
          <Icon name="plane" size={16} /> Post a new ride
        </Link>
      </div>

      {requests?.length > 0 && (
        <div className="stat-row" role="group" aria-label="Filter rides">
          {FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              className="filter-chip"
              aria-pressed={filter === f.value}
              onClick={() => setFilter(f.value)}
            >
              {f.label}
              <span>{counts[f.value] ?? 0}</span>
            </button>
          ))}
        </div>
      )}

      <ErrorList errors={errors} />
      {!requests && !errors && <p className="muted">Loading your rides…</p>}

      {requests?.length === 0 && (
        <EmptyState
          title="No ride requests yet"
          icon="plane"
          action={
            <Link to="/traveler/new" className="btn btn-primary">
              Post a ride
            </Link>
          }
        >
          Post a ride with your price, and taxi companies that can serve it will offer you a car.
        </EmptyState>
      )}

      {requests?.length > 0 && shown.length === 0 && <p className="muted">No rides match this filter.</p>}

      {shown.length > 0 && (
        <div className="ride-grid">
          {shown.map((r) => (
            <RideCard key={r.request_id} r={r} />
          ))}
        </div>
      )}

      <div className="card track-hint">
        <div>
          <h3>Already booked?</h3>
          <p className="muted small">Lost your booking number? Find your ride with your name.</p>
        </div>
        <Link to="/track" className="btn">
          Track a booking <Icon name="arrow" size={16} />
        </Link>
      </div>
    </>
  );
}
