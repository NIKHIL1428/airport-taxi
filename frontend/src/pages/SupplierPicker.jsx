import { Link } from "react-router-dom";
import { ErrorList, useCatalog } from "../components/common.jsx";
import Icon, { Avatar, Stars } from "../components/Icon.jsx";

export default function SupplierPicker() {
  const { catalog, error } = useCatalog();

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Choose your company</h1>
          <p className="muted">Open your company's board to see the ride requests you can serve.</p>
        </div>
      </div>
      {error && <ErrorList errors={error.errors} />}
      {!catalog && !error && <p className="muted">Loading suppliers…</p>}
      <div className="grid">
        {catalog?.suppliers.map((s) => (
          <Link key={s.company_id} to={`/supplier/${s.company_id}`} className="card card-link company-card">
            <div className="company-card-top">
              <Avatar name={s.name} size={48} />
              <div>
                <h3>{s.name}</h3>
                <Stars value={s.rating} />
              </div>
            </div>
            <dl>
              <div>
                <dt>Airports</dt>
                <dd>{s.airports.join(", ")}</dd>
              </div>
              <div>
                <dt>Opening hours</dt>
                <dd>
                  {s.service_from}–{s.service_until}
                </dd>
              </div>
              <div>
                <dt>Cars</dt>
                <dd>{s.vehicles.length}</dd>
              </div>
            </dl>
            <span className="cta">
              Open board <Icon name="arrow" size={16} />
            </span>
          </Link>
        ))}
      </div>
    </>
  );
}
