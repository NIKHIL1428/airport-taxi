// Times are local airport times without offsets: format the string directly, never via Date (no TZ shifts).
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function fmtDateTime(value) {
  if (!value) return "—";
  const [date, time = ""] = value.split("T");
  const [y, m, d] = date.split("-");
  return `${Number(d)} ${MONTHS[Number(m) - 1]} ${y}, ${time.slice(0, 5)}`;
}

export const fmtTime = (value) => (value ? value.split("T")[1].slice(0, 5) : "—");

export const inr = (n) => (n == null ? "—" : `₹${Number(n).toLocaleString("en-IN")}`);

export function passengersText(r) {
  const kids = r.child_ages?.length
    ? ` + ${r.child_ages.length} child${r.child_ages.length > 1 ? "ren" : ""} (age ${r.child_ages.join(", ")})`
    : "";
  return `${r.adults} adult${r.adults > 1 ? "s" : ""}${kids}`;
}

export const bagsText = (r) => `${r.large_bags} large + ${r.small_bags} small`;

// HATCHBACK -> Hatchback, SUV stays SUV.
export const titleCase = (s) => (!s ? "Any" : s === "SUV" ? "SUV" : s.charAt(0) + s.slice(1).toLowerCase());
