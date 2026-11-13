// All data comes from the backend API. Errors always look like {errors: [{rule, message, field}]}.

export class ApiError extends Error {
  constructor(status, errors) {
    super(errors.map((e) => e.message).join(" "));
    this.status = status;
    this.errors = errors;
  }
}

async function call(path, options = {}) {
  let res;
  try {
    res = await fetch(`/api${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch {
    throw new ApiError(0, [{ rule: "NETWORK", message: "Cannot reach the backend. Is it running on port 8000?" }]);
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const fallback =
      res.status >= 500
        ? "The backend is not responding. Check that the backend window is running and has no error."
        : body.detail || `Request failed (${res.status})`;
    throw new ApiError(res.status, body.errors || [{ rule: "ERROR", message: fallback }]);
  }
  return body;
}

const q = (params) => new URLSearchParams(params).toString();
const enc = encodeURIComponent;
const post = (path, body) => call(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });

export const api = {
  catalog: () => call("/catalog"),
  priceRange: (flightId, hotelId) => call(`/price-range?${q({ flight_id: flightId, hotel_id: hotelId })}`),

  // Traveler
  createRequest: (payload) => post("/requests", payload),
  listRequests: (ids) => call(`/requests?${q({ ids: ids.join(",") })}`),
  getRequest: (id) => call(`/requests/${enc(id)}`),
  checkName: (name) => call(`/names/check?${q({ name })}`),
  findByName: (name) => call(`/requests/by-name?${q({ name })}`),
  requestOffers: (id) => call(`/requests/${enc(id)}/offers`),
  bookOffer: (offerId) => post(`/offers/${offerId}/book`),
  rejectOffer: (offerId) => post(`/offers/${offerId}/reject`),
  booking: (no) => call(`/bookings/${enc(no)}`),
  lookupBooking: (travelerName, bookingNo) =>
    post("/bookings/lookup", { traveler_name: travelerName, booking_no: bookingNo }),
  createChange: (no, payload) => post(`/bookings/${enc(no)}/changes`, payload),
  cancelBooking: (no) => post(`/bookings/${enc(no)}/cancel`),

  // Supplier
  supplierDashboard: (companyId) => call(`/suppliers/${enc(companyId)}/dashboard`),
  supplierOffers: (companyId) => call(`/suppliers/${enc(companyId)}/offers`),
  createOffer: (payload) => post("/offers", payload),
  createSharedOffer: (payload) => post("/offers/shared", payload), // S1: one car, two requests
  supplierChanges: (companyId) => call(`/suppliers/${enc(companyId)}/changes`),
  acceptChange: (id, companyId) => post(`/changes/${id}/accept`, { company_id: companyId }),
  rejectChange: (id, companyId, reason) => post(`/changes/${id}/reject`, { company_id: companyId, reason }),
};
