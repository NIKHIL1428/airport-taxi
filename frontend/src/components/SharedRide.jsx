import { useState } from "react";
import { api } from "../api.js";
import { ErrorList } from "./common.jsx";
import Icon from "./Icon.jsx";
import { fmtDateTime, fmtTime, inr, titleCase } from "../format.js";

// S1 shared ride. The backend decides who can share (same flight, same area, pickups at most
// 60 minutes apart, a car that fits everyone and is free). The screen only shows its answer.

const people = (n) => `${n} ${n === 1 ? "person" : "people"}`;
const bags = (large, small) => `${large} large + ${small} small bags`;

// Supplier: put this request and one partner request into one car, with a price for each family.
export function SharedRideForm({ request, companyId, onAssigned }) {
  const partners = request.share_with || [];
  const [partnerId, setPartnerId] = useState(partners[0]?.request_id || "");
  const partner = partners.find((p) => p.request_id === partnerId);
  const [vehicleId, setVehicleId] = useState(partner?.vehicles.find((v) => v.usable)?.vehicle_id || "");
  const [price, setPrice] = useState(String(request.price_inr));
  const [partnerPrice, setPartnerPrice] = useState(String(partner?.price_inr ?? ""));
  const [holdMinutes, setHoldMinutes] = useState("5");
  const [errors, setErrors] = useState(null);
  const [done, setDone] = useState(null);
  const [saving, setSaving] = useState(false);

  if (!partners.length) return null;

  function choosePartner(id) {
    const p = partners.find((x) => x.request_id === id);
    setPartnerId(id);
    setVehicleId(p?.vehicles.find((v) => v.usable)?.vehicle_id || "");
    setPartnerPrice(String(p?.price_inr ?? ""));
    setErrors(null);
    setDone(null);
  }

  async function submit(e) {
    e.preventDefault();
    setErrors(null);
    setDone(null);
    setSaving(true);
    const num = (v) => (v === "" ? null : Number(v));
    try {
      const result = await api.createSharedOffer({
        request_ids: [request.request_id, partnerId],
        company_id: companyId,
        vehicle_id: vehicleId || null,
        prices: [num(price), num(partnerPrice)],
        hold_minutes: num(holdMinutes),
      });
      setDone(
        `Shared ride assigned: ${result.offers[0].vehicle.vehicle_id} picks up both families at ` +
          `${fmtTime(result.pickup)}. Each family books or rejects its own offer.`
      );
      onAssigned();
    } catch (err) {
      setErrors(err.errors);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="assign shared-form" onSubmit={submit} noValidate>
      <h4>
        <Icon name="users" size={16} /> Shared ride
        <span className="badge badge-shared">S1</span>
      </h4>
      <p className="muted small">
        {partners.length === 1 ? "Another traveler" : `${partners.length} travelers`} on the same flight to the same
        area can share one of your cars with {request.traveler_name}.
      </p>
      <div className="assign-grid">
        <label>
          Share with
          <select value={partnerId} onChange={(e) => choosePartner(e.target.value)}>
            {partners.map((p) => (
              <option key={p.request_id} value={p.request_id}>
                {p.request_id} · {p.traveler_name} · {people(p.passengers)} · pickup {fmtTime(p.pickup)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Car
          <select value={vehicleId} onChange={(e) => setVehicleId(e.target.value)}>
            <option value="">Choose a car…</option>
            {partner?.vehicles.map((v) => (
              <option key={v.vehicle_id} value={v.vehicle_id}>
                {v.usable ? "✓" : "✗"} {v.vehicle_id} · {titleCase(v.type)} · {v.seats} seats
                {v.usable ? "" : ` (${v.availability.label.toLowerCase()})`}
              </option>
            ))}
          </select>
        </label>
      </div>
      {partner && (
        <div className="shared-summary">
          <span>
            <strong>Together:</strong> {people(partner.total_passengers)},{" "}
            {bags(partner.total_large_bags, partner.total_small_bags)}
          </span>
          <span>
            <strong>Pickup:</strong> {fmtDateTime(partner.shared_pickup)} (the later of the two)
          </span>
          <span>
            <strong>Car busy:</strong> {fmtTime(partner.busy_window.start)} – {fmtTime(partner.busy_window.end)}
          </span>
          <span>
            <strong>Hotels:</strong> {request.hotel.name}
            {partner.hotel_name !== request.hotel.name ? ` and ${partner.hotel_name}` : ""}
          </span>
        </div>
      )}
      <div className="assign-grid">
        <label>
          Price for {request.traveler_name} (₹)
          <input type="number" step="100" value={price} onChange={(e) => setPrice(e.target.value)} />
          <small className="muted">They asked {inr(request.price_inr)}</small>
        </label>
        <label>
          Price for {partner?.traveler_name || "the other traveler"} (₹)
          <input type="number" step="100" value={partnerPrice} onChange={(e) => setPartnerPrice(e.target.value)} />
          <small className="muted">
            They asked {inr(partner?.price_inr)}
            {request.route && ` · allowed ${inr(request.route.price_min_inr)} – ${inr(request.route.price_max_inr)}`}
          </small>
        </label>
        <label>
          Guaranteed for (minutes)
          <input type="number" min="1" max="60" value={holdMinutes} onChange={(e) => setHoldMinutes(e.target.value)} />
          <small className="muted">Car held for both families</small>
        </label>
      </div>
      <ErrorList errors={errors} />
      {done && <div className="alert alert-success">{done}</div>}
      <button className="btn btn-primary" disabled={saving}>
        {saving ? "Assigning…" : "Assign shared ride"}
      </button>
    </form>
  );
}

// Traveler (offer card and booking): this car also carries another family. No names are shown.
export function SharedNote({ shared, yourPickup }) {
  if (!shared) return null;
  const later = shared.pickup && yourPickup && shared.pickup !== yourPickup;
  return (
    <div className="shared-note">
      <span className="badge badge-shared">
        <Icon name="users" size={13} /> Shared ride
      </span>
      <span className="small">
        You share this car with another traveler ({people(shared.other_passengers)},{" "}
        {bags(shared.other_large_bags, shared.other_small_bags)}
        {shared.other_hotel ? `, to ${shared.other_hotel}` : ""}).
        {later && (
          <>
            {" "}
            Pickup is at <strong>{fmtTime(shared.pickup)}</strong>, not {fmtTime(yourPickup)}.
          </>
        )}
      </span>
    </div>
  );
}
