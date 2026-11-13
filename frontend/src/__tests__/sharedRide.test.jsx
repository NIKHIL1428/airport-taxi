// S1 shared ride: what the traveler sees on a shared offer, and the supplier's shared-ride form.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { SharedNote, SharedRideForm } from "../components/SharedRide.jsx";

const html = (element) => renderToStaticMarkup(element);

const shared = {
  share_group: "SH-0001",
  pickup: "2027-04-10T12:00",
  other_passengers: 2,
  other_large_bags: 1,
  other_small_bags: 1,
  other_hotel: "Ueno Garden Inn",
  total_passengers: 5,
  other_booked: false,
};

describe("SharedNote (traveler)", () => {
  it("shows nothing for a private ride", () => {
    expect(html(<SharedNote shared={null} />)).toBe("");
  });

  it("says who else rides along, without a name", () => {
    const out = html(<SharedNote shared={shared} yourPickup="2027-04-10T12:00" />);
    expect(out).toContain("Shared ride");
    expect(out).toContain("2 people, 1 large + 1 small bags");
    expect(out).not.toContain("not 12:00");
  });

  it("warns when the shared car comes later than the traveler asked", () => {
    const out = html(<SharedNote shared={shared} yourPickup="2027-04-10T11:30" />);
    expect(out).toContain("12:00");
    expect(out).toContain("not 11:30");
  });
});

describe("SharedRideForm (supplier)", () => {
  const request = {
    request_id: "REQ-0004",
    traveler_name: "Menon family",
    price_inr: 12000,
    hotel: { name: "Ueno Garden Inn" },
    route: { price_min_inr: 10200, price_max_inr: 16800 },
  };
  const partner = {
    request_id: "REQ-0005",
    traveler_name: "Rao couple",
    passengers: 2,
    pickup: "2027-04-10T12:00",
    price_inr: 11000,
    hotel_name: "Ueno Garden Inn",
    shared_pickup: "2027-04-10T12:00",
    total_passengers: 5,
    total_large_bags: 4,
    total_small_bags: 3,
    busy_window: { start: "2027-04-10T12:00", end: "2027-04-10T15:00" },
    vehicles: [
      { vehicle_id: "SC-1", type: "SEDAN", seats: 4, usable: false, availability: { label: "Does not fit" } },
      { vehicle_id: "SC-3", type: "SUV", seats: 6, usable: true, availability: { label: "Available" } },
    ],
  };

  it("is hidden when nobody can share", () => {
    expect(html(<SharedRideForm request={{ ...request, share_with: [] }} companyId="TX-JP-01" />)).toBe("");
  });

  it("shows the partner, everyone together, and a price for each family", () => {
    const out = html(<SharedRideForm request={{ ...request, share_with: [partner] }} companyId="TX-JP-01" />);
    expect(out).toContain("Rao couple");
    expect(out).toContain("5 people, 4 large + 3 small bags");
    expect(out).toContain("12:00 – 15:00");
    expect(out).toContain("Price for Menon family");
    expect(out).toContain("Price for Rao couple");
    expect(out).toContain("(does not fit)");
  });
});
