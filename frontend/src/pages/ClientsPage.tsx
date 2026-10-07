import { api } from "../api";
import { Await } from "../components";
import { link } from "../routes";
import { useLoad } from "../useLoad";

export function ClientsPage() {
  const clients = useLoad(() => api.clients(), []);
  return (
    <>
      <h1>Clients</h1>
      <Await result={clients}>
        {(rows) =>
          rows.length === 0 ? (
            <p>
              No radar runs yet. Run <code>scripts/radar.py --client &lt;id&gt;</code> and reload.
            </p>
          ) : (
            <ul className="cards">
              {rows.map((c) => (
                <li key={c.client_id} className="card">
                  <h2>{c.client_id}</h2>
                  {c.offer && <p className="muted">{c.offer}</p>}
                  {c.latest ? (
                    <>
                      <p>
                        Latest run {c.latest}: {c.accounts} to approach, {c.tenders} tender
                        {c.tenders === 1 ? "" : "s"} to watch.
                      </p>
                      <a className="btn primary" href={link("c", c.client_id, c.latest)}>
                        Open brief
                      </a>
                    </>
                  ) : (
                    <p className="muted">No run yet.</p>
                  )}
                </li>
              ))}
            </ul>
          )
        }
      </Await>
    </>
  );
}
