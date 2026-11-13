import { Link } from "react-router-dom";
import Icon from "../components/Icon.jsx";

// Home page: the user says who they are. No login, no account.
export default function Home() {
  return (
    <>
      <section className="hero">
        <div className="hero-inner">
          <p className="hero-kicker">Airport taxis · you set the price</p>
          <h1>Get from the airport to your hotel, at a price you choose</h1>
          <p className="hero-sub">
            Post your ride with the flight and hotel you have. Taxi companies that can serve it offer you a car, and you
            book the one you like. No account needed.
          </p>
        </div>
      </section>

      <section className="home-section">
        <div className="home-choices">
          <Link to="/traveler" className="card card-link choice">
            <span className="choice-icon">
              <Icon name="plane" size={24} />
            </span>
            <h2>I'm travelling</h2>
            <p className="muted">Post a ride from the airport to your hotel, compare offers, and book a taxi.</p>
            <span className="choice-cta">
              Go to my rides <Icon name="arrow" size={16} />
            </span>
          </Link>
          <Link to="/supplier" className="card card-link choice">
            <span className="choice-icon">
              <Icon name="car" size={24} />
            </span>
            <h2>I run a taxi company</h2>
            <p className="muted">See ride requests you can serve, and assign your cars with a price.</p>
            <span className="choice-cta">
              Open the supplier board <Icon name="arrow" size={16} />
            </span>
          </Link>
        </div>
      </section>

      <section className="how">
        <h2>How it works</h2>
        <ol className="how-steps">
          <li>
            <h3>Post your ride</h3>
            <p>Pick your flight, hotel, passengers and bags. We show the suggested price range for that route.</p>
          </li>
          <li>
            <h3>Compare offers</h3>
            <p>Taxi companies with a free car that fits your party assign one with their price. Sort and compare.</p>
          </li>
          <li>
            <h3>Book and keep your number</h3>
            <p>Book one taxi. You get a booking number to track the trip later, by number or by name.</p>
          </li>
        </ol>
      </section>
    </>
  );
}
