// The API client: every call goes to /api, and every error becomes an ApiError with a list of messages.
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api.js";

const reply = (status, body) => Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) });

afterEach(() => {
  vi.restoreAllMocks();
});

describe("api client", () => {
  it("builds the price-range URL from the flight and hotel", async () => {
    const fetchMock = vi.fn(() => reply(200, { price_min_inr: 10200 }));
    globalThis.fetch = fetchMock;
    const range = await api.priceRange("FL-401", "HTL-TYO-004");
    expect(range.price_min_inr).toBe(10200);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/price-range?flight_id=FL-401&hotel_id=HTL-TYO-004");
  });

  it("sends a POST with a JSON body when assigning a car", async () => {
    const fetchMock = vi.fn(() => reply(201, { offer_id: 1 }));
    globalThis.fetch = fetchMock;
    await api.createOffer({ request_id: "REQ-0004", vehicle_id: "SC-3" });
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/offers");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({ request_id: "REQ-0004", vehicle_id: "SC-3" });
  });

  it("turns a refused request into an ApiError with the rule and message", async () => {
    globalThis.fetch = vi.fn(() =>
      reply(422, { errors: [{ rule: "R3", field: "price_inr", message: "Price ₹5 is outside the range." }] })
    );
    let error;
    try {
      await api.createRequest({});
    } catch (e) {
      error = e;
    }
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(422);
    expect(error.errors[0].rule).toBe("R3");
  });

  it("gives a clear message when the backend cannot be reached", async () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new TypeError("Failed to fetch")));
    let error;
    try {
      await api.catalog();
    } catch (e) {
      error = e;
    }
    expect(error.status).toBe(0);
    expect(error.errors[0].message).toContain("Cannot reach the backend");
  });

  it("explains a server error without a body", async () => {
    globalThis.fetch = vi.fn(() => reply(500, {}));
    let error;
    try {
      await api.catalog();
    } catch (e) {
      error = e;
    }
    expect(error.errors[0].message).toContain("backend is not responding");
  });

  it("encodes values that go into the URL", async () => {
    const fetchMock = vi.fn(() => reply(200, {}));
    globalThis.fetch = fetchMock;
    await api.findByName("Menon & family");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/requests/by-name?name=Menon+%26+family");
  });
});
