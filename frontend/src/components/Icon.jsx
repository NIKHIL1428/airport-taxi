// Small line icons (24×24, stroke-based). Decorative: the text next to them says what they mean.
const SHAPES = {
  car: (
    <>
      <path d="M5 16.5V12l2-5h10l2 5v4.5" />
      <path d="M3 16.5h18v2.5H3z" />
      <circle cx="7.5" cy="18.5" r="0.5" />
      <circle cx="16.5" cy="18.5" r="0.5" />
    </>
  ),
  plane: <path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z" />,
  bed: (
    <>
      <path d="M2.5 19V6M2.5 14h19v5M21.5 14v-2.5A2.5 2.5 0 0 0 19 9h-7v5" />
      <circle cx="6.5" cy="11" r="2" />
    </>
  ),
  pin: (
    <>
      <path d="M12 21s7-6.2 7-11.5a7 7 0 0 0-14 0C5 14.8 12 21 12 21z" />
      <circle cx="12" cy="9.5" r="2.5" />
    </>
  ),
  calendar: (
    <>
      <rect x="3" y="4.5" width="18" height="16.5" rx="2" />
      <path d="M3 9.5h18M8 2.5v4M16 2.5v4" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7.5V12l3 2" />
    </>
  ),
  user: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4 3.6-6 8-6s8 2 8 6" />
    </>
  ),
  users: (
    <>
      <circle cx="9" cy="8" r="3.2" />
      <path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6" />
      <path d="M16 4.6a3.2 3.2 0 0 1 0 6.3M21 20c0-2.7-1.6-5-4-5.8" />
    </>
  ),
  bag: (
    <>
      <rect x="4" y="7" width="16" height="13" rx="2" />
      <path d="M9 7V5a3 3 0 0 1 6 0v2" />
    </>
  ),
  money: (
    <>
      <rect x="2.5" y="6.5" width="19" height="11" rx="2" />
      <circle cx="12" cy="12" r="2.5" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-4.2-4.2" />
    </>
  ),
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
  back: <path d="M19 12H5M11 6l-6 6 6 6" />,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  shield: <path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z" />,
  list: <path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01" />,
  star: <path d="M12 3.5l2.6 5.3 5.8.8-4.2 4.1 1 5.8L12 16.9l-5.2 2.6 1-5.8-4.2-4.1 5.8-.8z" fill="currentColor" />,
  ticket: (
    <>
      <path d="M3 8a2 2 0 0 0 0 4v4h18v-4a2 2 0 0 0 0-4V4H3z" />
      <path d="M14 4v16" strokeDasharray="2 2" />
    </>
  ),
};

export default function Icon({ name, size = 18, className = "" }) {
  return (
    <svg
      className={`icon ${className}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {SHAPES[name]}
    </svg>
  );
}

// A round badge with the company's first letter. Used instead of a logo we do not have.
export function Avatar({ name, size = 44 }) {
  return (
    <span className="avatar" style={{ width: size, height: size, fontSize: Math.round(size * 0.42) }} aria-hidden="true">
      {(name || "?").trim().charAt(0).toUpperCase()}
    </span>
  );
}

// Star rating: one filled star and the score to one decimal place.
export function Stars({ value }) {
  if (value == null) return null;
  return (
    <span className="stars" aria-label={`Rated ${value} out of 5`}>
      <Icon name="star" size={14} className="star-icon" />
      <span>{Number(value).toFixed(1)}</span>
    </span>
  );
}
