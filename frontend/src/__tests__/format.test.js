// Formatting helpers: times are local airport times and must never shift by time zone.
import { describe, expect, it } from "vitest";
import { bagsText, fmtDateTime, fmtTime, inr, passengersText, titleCase } from "../format.js";

describe("fmtDateTime", () => {
  it("formats a local time without converting time zones", () => {
    expect(fmtDateTime("2027-04-10T11:30")).toBe("10 Apr 2027, 11:30");
    expect(fmtDateTime("2027-04-01T00:05:00")).toBe("1 Apr 2027, 00:05");
  });
  it("shows a dash for an empty value", () => {
    expect(fmtDateTime(null)).toBe("—");
    expect(fmtDateTime("")).toBe("—");
  });
});

describe("fmtTime", () => {
  it("keeps only hours and minutes", () => {
    expect(fmtTime("2027-04-10T14:30:00")).toBe("14:30");
    expect(fmtTime(undefined)).toBe("—");
  });
});

describe("inr", () => {
  it("uses the rupee sign and Indian digit grouping", () => {
    expect(inr(12000)).toBe("₹12,000");
    expect(inr(1234567)).toBe("₹12,34,567");
    expect(inr(0)).toBe("₹0");
  });
  it("shows a dash when there is no price", () => {
    expect(inr(null)).toBe("—");
  });
});

describe("passengersText and bagsText", () => {
  it("describes the Menon family", () => {
    expect(passengersText({ adults: 2, child_ages: [6] })).toBe("2 adults + 1 child (age 6)");
    expect(bagsText({ large_bags: 3, small_bags: 2 })).toBe("3 large + 2 small");
  });
  it("handles one adult and several children", () => {
    expect(passengersText({ adults: 1, child_ages: [] })).toBe("1 adult");
    expect(passengersText({ adults: 2, child_ages: [3, 10] })).toBe("2 adults + 2 children (age 3, 10)");
  });
});

describe("titleCase", () => {
  it("formats car types and keeps SUV in capitals", () => {
    expect(titleCase("HATCHBACK")).toBe("Hatchback");
    expect(titleCase("SUV")).toBe("SUV");
    expect(titleCase(null)).toBe("Any");
  });
});
