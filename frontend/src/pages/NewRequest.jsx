import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { ErrorList, Stepper, useCatalog } from "../components/common.jsx";
import Icon from "../components/Icon.jsx";
import { fmtDateTime, inr, titleCase } from "../format.js";
import { rememberRequest } from "../myRides.js";

const EMPTY = {
  traveler_name: "",
  airport: "",
  flight_id: "",
  hotel_id: "",
  adults: "1",
  child_ages: [],
  large_bags: "0",
  small_bags: "0",
  pickup: "",
  car_type: "",
  price_inr: "",
};

// Scenario 1 from the problem statement, for the demo.
const MENON = {
  traveler_name: "Menon family",
  airport: "NRT",
  flight_id: "FL-401",
  hotel_id: "HTL-TYO-004",
  adults: "2",
  child_ages: ["6"],
  large_bags: "3",
  small_bags: "2",
  pickup: "2027-04-10T11:30",
  car_type: "",
  price_inr: "12000",
};

// "" -> null, "12" -> 12, "abc" -> "abc" (the backend then gives a clear message).
const toNumber = (v) => (v === "" || v == null ? null : Number.isNaN(Number(v)) ? v : Number(v));

export default function NewRequest() {
  const { catalog, error: catalogError } = useCatalog();
  const navigate = useNavigate();
  const [form, setForm] = useState(EMPTY);
  const [range, setRange] = useState(null);
  const [rangeErrors, setRangeErrors] = useState(null);
  const [errors, setErrors] = useState(null);
  const [saving, setSaving] = useState(false);
  const [nameCheck, setNameCheck] = useState(null); // {available, message} from the backend

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  // Ask the backend for the price range whenever flight + hotel change (R1, R3).
  useEffect(() => {
    setRange(null);
    setRangeErrors(null);
    if (!form.flight_id || !form.hotel_id) return;
    let stale = false;
    api
      .priceRange(form.flight_id, form.hotel_id)
      .then((r) => !stale && setRange(r))
      .catch((e) => !stale && setRangeErrors(e.errors));
    return () => {
      stale = true;
    };
  }, [form.flight_id, form.hotel_id]);

  // Live check that the name is still free (names are unique, so a traveler can find their ride by name).
  useEffect(() => {
    setNameCheck(null);
    if (!form.traveler_name.trim()) return;
    let stale = false;
    const timer = setTimeout(() => {
      api
        .checkName(form.traveler_name)
        .then((r) => !stale && setNameCheck(r))
        .catch(() => {});
    }, 350);
    return () => {
      stale = true;
      clearTimeout(timer);
    };
  }, [form.traveler_name]);

  const flights = useMemo(
    () => (catalog?.flights || []).filter((f) => !form.airport || f.to === form.airport),
    [catalog, form.airport]
  );

  const hotelsByCity = useMemo(() => {
    const groups = {};
    for (const h of catalog?.hotels || []) (groups[h.city] ??= []).push(h);
    return groups;
  }, [catalog]);

  const servedCities = catalog?.arrival_airports.find((a) => a.code === form.airport)?.serves_cities;

  const price = Number(form.price_inr);
  const priceOutside = range && form.price_inr !== "" && (price < range.price_min_inr || price > range.price_max_inr);

  function setChildAge(i, value) {
    setForm((f) => ({ ...f, child_ages: f.child_ages.map((a, j) => (j === i ? value : a)) }));
  }

  async function submit(e) {
    e.preventDefault();
    setErrors(null);
    setSaving(true);
    try {
      const created = await api.createRequest({
        traveler_name: form.traveler_name,
        flight_id: form.flight_id || null,
        hotel_id: form.hotel_id || null,
        adults: toNumber(form.adults),
        child_ages: form.child_ages.map(toNumber),
        large_bags: toNumber(form.large_bags) ?? 0,
        small_bags: toNumber(form.small_bags) ?? 0,
        pickup: form.pickup || null,
        car_type: form.car_type || null,
        price_inr: toNumber(form.price_inr),
      });
      rememberRequest(created.request_id);
      navigate(`/traveler/requests/${created.request_id}`);
    } catch (err) {
      setErrors(err.errors);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } finally {
      setSaving(false);
    }
  }

  const fieldError = (name) => errors?.some((e) => e.field === name);

  if (catalogError) return <ErrorList errors={catalogError.errors} />;
  if (!catalog) return <p className="muted">Loading flights and hotels…</p>;


  return (
    <>
      <div className="page-head">
        <div>
          <h1>Post a ride request</h1>
          <p className="muted">From the airport to your hotel. You set the price.</p>
        </div>
        <button type="button" className="btn" onClick={() => setForm(MENON)}>
          Fill Menon example
        </button>
      </div>

      <ErrorList errors={errors} />

      <form onSubmit={submit} noValidate className="form-layout">
        <div className="card form form-main">
          <fieldset>
            <legend>
              <span className="section-num">1</span> Your details
            </legend>
            <label className={fieldError("traveler_name") || nameCheck?.available === false ? "invalid" : ""}>
              Your name (must be unique)
              <input
                value={form.traveler_name}
                onChange={set("traveler_name")}
                placeholder="e.g. Menon family"
                autoComplete="name"
              />
              {nameCheck ? (
                <small className={nameCheck.available ? "text-ok" : "text-danger"}>
                  {nameCheck.available ? "✓ This name is free." : nameCheck.message}
                </small>
              ) : (
                <small className="muted">
                  You can find your ride later with this name, even without the booking number.
                </small>
              )}
            </label>
          </fieldset>

          <fieldset>
            <legend>
              <span className="section-num">2</span> Flight and hotel
            </legend>
            <div className="row">
              <label>
                Arrival airport
                <select value={form.airport} onChange={(e) => setForm((f) => ({ ...f, airport: e.target.value, flight_id: "" }))}>
                  <option value="">All airports</option>
                  {catalog.arrival_airports.map((a) => (
                    <option key={a.code} value={a.code}>
                      {a.code} · {a.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className={fieldError("flight_id") ? "invalid" : ""}>
                Arrival flight
                <select value={form.flight_id} onChange={set("flight_id")}>
                  <option value="">Choose a flight…</option>
                  {flights.map((f) => (
                    <option key={f.flight_id} value={f.flight_id}>
                      {f.flight_number} · {f.from} → {f.to} · lands {fmtDateTime(f.arrival_local)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label className={fieldError("hotel_id") ? "invalid" : ""}>
              Hotel
              <select value={form.hotel_id} onChange={set("hotel_id")}>
                <option value="">Choose a hotel…</option>
                {Object.entries(hotelsByCity).map(([city, hotels]) => (
                  <optgroup
                    key={city}
                    label={servedCities && !servedCities.includes(city) ? `${city} (not served from ${form.airport})` : city}
                  >
                    {hotels.map((h) => (
                      <option key={h.hotel_id} value={h.hotel_id}>
                        {h.name} — {h.area}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </label>
            <ErrorList errors={rangeErrors} />
          </fieldset>

          <fieldset>
            <legend>
              <span className="section-num">3</span> Passengers and bags
            </legend>
            <div className="steppers">
              <div className={fieldError("adults") ? "invalid" : ""}>
                <Stepper id="adults" label="Adults" min={1} max={20} value={form.adults} onChange={(v) => setForm((f) => ({ ...f, adults: v }))} hint="At least 1" />
              </div>
              <div className={fieldError("large_bags") ? "invalid" : ""}>
                <Stepper id="large-bags" label="Large bags" max={20} value={form.large_bags} onChange={(v) => setForm((f) => ({ ...f, large_bags: v }))} hint="Suitcases" />
              </div>
              <div className={fieldError("small_bags") ? "invalid" : ""}>
                <Stepper id="small-bags" label="Small bags" max={20} value={form.small_bags} onChange={(v) => setForm((f) => ({ ...f, small_bags: v }))} hint="Hand luggage" />
              </div>
            </div>
            <div className={`children ${fieldError("child_ages") ? "invalid" : ""}`}>
              <span>Children (age 0–17)</span>
              {form.child_ages.map((age, i) => (
                <span key={i} className="child">
                  <input
                    type="number"
                    min="0"
                    max="17"
                    value={age}
                    onChange={(e) => setChildAge(i, e.target.value)}
                    aria-label={`Child ${i + 1} age`}
                  />
                  <button
                    type="button"
                    className="btn btn-small"
                    onClick={() => setForm((f) => ({ ...f, child_ages: f.child_ages.filter((_, j) => j !== i) }))}
                  >
                    Remove
                  </button>
                </span>
              ))}
              <button
                type="button"
                className="btn btn-small"
                onClick={() => setForm((f) => ({ ...f, child_ages: [...f.child_ages, ""] }))}
              >
                + Add child
              </button>
            </div>
          </fieldset>

          <fieldset>
            <legend>
              <span className="section-num">4</span> Pickup and price
            </legend>
            <div className="row">
              <label className={fieldError("pickup") ? "invalid" : ""}>
                Pickup time (local, optional)
                <input type="datetime-local" value={form.pickup} onChange={set("pickup")} />
                <small className="muted">
                  {range ? `Empty = earliest pickup, ${fmtDateTime(range.earliest_pickup)}` : "Empty = 60 min after landing"}
                </small>
              </label>
              <label className={fieldError("car_type") ? "invalid" : ""}>
                Car type
                <select value={form.car_type} onChange={set("car_type")}>
                  <option value="">Any</option>
                  {catalog.car_types.map((t) => (
                    <option key={t} value={t}>
                      {titleCase(t)}
                    </option>
                  ))}
                </select>
              </label>
              <label className={fieldError("price_inr") || priceOutside ? "invalid" : ""}>
                Your price (₹, whole ride)
                <input type="number" min="0" step="100" value={form.price_inr} onChange={set("price_inr")} />
                {priceOutside ? (
                  <small className="text-danger">
                    Outside {inr(range.price_min_inr)} – {inr(range.price_max_inr)}
                  </small>
                ) : (
                  range && (
                    <small className="muted">
                      Suggested {inr(range.price_min_inr)} – {inr(range.price_max_inr)}
                    </small>
                  )
                )}
              </label>
            </div>
          </fieldset>
        </div>

        <aside className="summary-panel">
          <div className="card sticky-card">
            <h2>Your ride</h2>
            {range ? (
              <>
                <div className="summary-route">
                  <Icon name="plane" size={18} />
                  <div>
                    <strong>{range.airport}</strong> → <strong>{range.city}</strong>
                    <div className="muted small">
                      {range.area} · {range.distance_km} km · about {range.drive_minutes} min
                    </div>
                  </div>
                </div>
                <dl className="facts summary-facts">
                  <dt>Lands</dt>
                  <dd>{fmtDateTime(range.arrival_local)}</dd>
                  <dt>Earliest pickup</dt>
                  <dd>{fmtDateTime(range.earliest_pickup)}</dd>
                  <dt>Suggested price</dt>
                  <dd>
                    {inr(range.price_min_inr)} – {inr(range.price_max_inr)}
                  </dd>
                </dl>
              </>
            ) : (
              <p className="muted small">Choose a flight and hotel to see the route, times and suggested price.</p>
            )}

            <div className="summary-total">
              <span>Your price</span>
              <strong>{form.price_inr !== "" ? inr(Number(form.price_inr)) : "—"}</strong>
            </div>
            {priceOutside && (
              <p className="text-danger small">
                Outside the allowed range {inr(range.price_min_inr)} – {inr(range.price_max_inr)}
              </p>
            )}

            <button type="submit" className="btn btn-primary btn-block btn-lg" disabled={saving}>
              {saving ? "Posting your request…" : "Post ride request"}
            </button>
            <p className="muted small submit-note">
              Taxi companies with a free car that fits your party can then offer you a ride. You choose one.
            </p>
          </div>
        </aside>
      </form>
    </>
  );
}
