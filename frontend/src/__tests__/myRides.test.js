// "My rides" is remembered in the browser (no login). These tests use an in-memory localStorage.
import { beforeEach, describe, expect, it } from "vitest";
import { forgetRequests, getMyRequestIds, rememberRequest } from "../myRides.js";

beforeEach(() => {
  const store = new Map();
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  };
});

describe("my rides", () => {
  it("starts empty", () => {
    expect(getMyRequestIds()).toEqual([]);
  });
  it("remembers rides newest first, without duplicates", () => {
    rememberRequest("REQ-0004");
    rememberRequest("REQ-0005");
    rememberRequest("REQ-0004");
    expect(getMyRequestIds()).toEqual(["REQ-0004", "REQ-0005"]);
  });
  it("forgets rides that no longer exist", () => {
    rememberRequest("REQ-0004");
    rememberRequest("REQ-0005");
    forgetRequests(["REQ-0004", "REQ-9999"]);
    expect(getMyRequestIds()).toEqual(["REQ-0005"]);
  });
  it("survives broken saved data", () => {
    localStorage.setItem("airport-taxi.my-requests", "not json");
    expect(getMyRequestIds()).toEqual([]);
  });
});
