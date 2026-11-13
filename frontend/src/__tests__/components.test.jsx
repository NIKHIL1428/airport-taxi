// Components rendered to HTML (no browser needed): what the traveler and the supplier would see.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import BookingDetails from "../components/BookingDetails.jsx";
import { ErrorList, Guarantee, RequestFacts, StatusBadge } from "../components/common.jsx";

const html = (element) => renderToStaticMarkup(element);

const ride = {
  traveler_name: "Menon family",
  flight: { flight_id: "FL-401", flight_number: "AV 520", from: "BLR", to: "NRT", arrival_local: "2027-04-10T10:30:00" },
  hotel: { name: "Ueno Garden Inn", city: "Tokyo", area: "Ueno" },
  adults: 2,
  child_ages: [6],
  passengers: 3,
  large_bags: 3,
  small_bags: 2,
  pickup: "2027-04-10T11:30",
  car_type: null,
  price_inr: 12000,
  route: { airport: "NRT", area: "Ueno", distance_km: 73.3, drive_minutes: 90, price_min_inr: 10200, price_max_inr: 16800 },
  busy_window: { start: "2027-04-10T11:30", end: "2027-04-10T14:30" },
};

const booking = {
  ...ride,
  booking_no: "5050162226",
  status: "CONFIRMED",
  supplier: { name: "Sakura Cabs", rating: 4.4 },
  vehicle: { vehicle_id: "SC-3", type: "SUV", seats: 6, large_bags: 4, small_bags: 3 },
  price_inr: 12500,
  changes: [],
};

describe("StatusBadge", () => {
  it("shows a readable label for every status", () => {
    expect(html(<StatusBadge status="CAR_TAKEN" />)).toContain("Car taken");
    expect(html(<StatusBadge status="NOT_CHOSEN" />)).toContain("Not chosen");
    expect(html(<StatusBadge status="CANCELLED" />)).toContain("badge-cancelled");
  });
});

describe("ErrorList", () => {
  it("shows the rule tag for rule errors only", () => {
    const out = html(
      <ErrorList
        errors={[
          { rule: "R3", message: "Price is outside the range." },
          { rule: "INPUT", message: "Enter your price in INR." },
        ]}
      />
    );
    expect(out).toContain('<span class="rule-tag">R3</span>');
    expect(out).not.toContain(">INPUT<");
    expect(out).toContain("Enter your price in INR.");
  });
  it("hides rule tags for the traveler", () => {
    expect(html(<ErrorList errors={[{ rule: "R6", message: "Car is busy." }]} showRules={false} />)).not.toContain("rule-tag");
  });
  it("renders nothing without errors", () => {
    expect(html(<ErrorList errors={[]} />)).toBe("");
  });
});

describe("RequestFacts", () => {
  it("shows the supplier the traveler's name and when the car is needed", () => {
    const out = html(<RequestFacts r={ride} audience="supplier" />);
    expect(out).toContain("Menon family");
    expect(out).toContain("Car needed");
    expect(out).toContain("10 Apr 2027, 11:30 – 14:30");
  });
  it("hides the car's busy time from the traveler", () => {
    const out = html(<RequestFacts r={ride} />);
    expect(out).not.toContain("Car needed");
    expect(out).toContain("₹12,000");
    expect(out).toContain("(range ₹10,200 – ₹16,800)");
  });
});

describe("Guarantee", () => {
  it("promises confirmation while the window is open", () => {
    expect(html(<Guarantee seconds={300} />)).toContain("Guaranteed confirmation if you book within <strong>5:00</strong>");
  });
  it("explains what happens after the window", () => {
    expect(html(<Guarantee seconds={0} />)).toContain("The guaranteed time is over");
  });
  it("shows the supplier how long the car is held", () => {
    expect(html(<Guarantee seconds={65} audience="supplier" />)).toContain("Held 1:05");
  });
  it("shows nothing for an offer without a window", () => {
    expect(html(<Guarantee seconds={null} />)).toBe("");
  });
});

describe("BookingDetails", () => {
  it("shows the booking number, supplier, car and total", () => {
    const out = html(<BookingDetails b={booking} />);
    expect(out).toContain("5050162226");
    expect(out).toContain("Your taxi is booked");
    expect(out).toContain("Sakura Cabs");
    expect(out).toContain("SUV SC-3");
    expect(out).toContain("₹12,500");
  });
  it("shows a cancelled booking as cancelled", () => {
    const out = html(<BookingDetails b={{ ...booking, status: "CANCELLED" }} />);
    expect(out).toContain("This booking was cancelled");
    expect(out).not.toContain("Booking confirmed");
  });
});
