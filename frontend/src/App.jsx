import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { useCatalog } from "./components/common.jsx";
import Icon from "./components/Icon.jsx";
import { THEME_CHOICES, useTheme } from "./theme.js";
import Home from "./pages/Home.jsx";
import SupplierPicker from "./pages/SupplierPicker.jsx";
import TravelerHome from "./pages/TravelerHome.jsx";
import NewRequest from "./pages/NewRequest.jsx";
import RequestPage from "./pages/RequestPage.jsx";
import BookingPage from "./pages/BookingPage.jsx";
import TrackBooking from "./pages/TrackBooking.jsx";
import SupplierDashboard from "./pages/SupplierDashboard.jsx";

// Three choices, one saved per browser. Kept in the top bar so it is always one click away.
function ThemeSwitch() {
  const { choice, change } = useTheme();
  return (
    <div className="theme-switch" role="group" aria-label="Colour theme">
      {THEME_CHOICES.map((t) => (
        <button
          key={t.value}
          type="button"
          aria-pressed={choice === t.value}
          className={choice === t.value ? "active" : ""}
          onClick={() => change(t.value)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

// The top bar changes with the role: travelers and suppliers only see their own links.
function TopBar() {
  const { pathname } = useLocation();
  const { catalog } = useCatalog();
  const supplierId = pathname.match(/^\/supplier\/([^/]+)/)?.[1];
  const supplier = catalog?.suppliers.find((s) => s.company_id === supplierId);
  const isTraveler = pathname.startsWith("/traveler") || pathname.startsWith("/booking") || pathname.startsWith("/track");

  return (
    <header className="topbar">
      <Link to="/" className="brand">
        <span className="brand-mark">
          <Icon name="car" size={18} />
        </span>
        Airport Taxi
      </Link>
      <nav className="nav">
        {isTraveler && (
          <>
            <NavLink to="/traveler" end>
              My rides
            </NavLink>
            <NavLink to="/traveler/new">New ride</NavLink>
            <NavLink to="/track">Track booking</NavLink>
          </>
        )}
        {supplierId && <span className="role-pill">{supplier?.name || supplierId}</span>}
        {pathname !== "/" && (
          <Link to="/" className="switch-role">
            Switch role
          </Link>
        )}
        <ThemeSwitch />
      </nav>
    </header>
  );
}

export default function App() {
  return (
    <>
      <TopBar />
      <main className="container" id="main">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/traveler" element={<TravelerHome />} />
          <Route path="/traveler/new" element={<NewRequest />} />
          <Route path="/traveler/requests/:requestId" element={<RequestPage />} />
          <Route path="/track" element={<TrackBooking />} />
          <Route path="/booking/:bookingNo" element={<BookingPage />} />
          <Route path="/supplier" element={<SupplierPicker />} />
          <Route path="/supplier/:companyId" element={<SupplierDashboard />} />
          <Route
            path="*"
            element={
              <div className="card empty">
                <h1>Page not found</h1>
                <Link to="/" className="btn btn-primary">
                  Go home
                </Link>
              </div>
            }
          />
        </Routes>
      </main>
      <footer className="footer">
        <div className="footer-inner">
          Airport Taxi · ride offers from airports to hotels. All times are local airport times.
        </div>
      </footer>
    </>
  );
}
