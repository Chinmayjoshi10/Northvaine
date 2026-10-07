import { api } from "../api";
import { Await, StatusPill } from "../components";
import { link } from "../routes";
import type { Row } from "../types";
import { useLoad } from "../useLoad";

function Table({ title, rows, client, day }: { title: string; rows: Row[]; client: string; day: string }) {
  return (
    <section aria-labelledby={`h-${title}`}>
      <h2 id={`h-${title}`}>{title}</h2>
      {rows.length === 0 ? (
        <p className="muted">None this time.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Status</th>
                <th scope="col">Company</th>
                <th scope="col">What</th>
                <th scope="col">Requirement</th>
                <th scope="col">Why now</th>
                <th scope="col">Caution</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.rank}>
                  <td data-label="Status">
                    <StatusPill status={r.status} />
                  </td>
                  <td data-label="Company">
                    <a className="row-link" href={link("c", client, day, "e", r.rank)}>
                      {r.company}
                    </a>
                    <div className="muted small">{r.country}</div>
                  </td>
                  <td data-label="What">{r.what}</td>
                  <td data-label="Requirement">
                    <span className="mono">
                      {r.requirement}
                      {r.requirement_ref ? ` [${r.requirement_ref}]` : ""}
                    </span>
                  </td>
                  <td data-label="Why now">{r.why_now}</td>
                  <td data-label="Caution">{r.caution}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function BriefPage({ client, day }: { client: string; day: string }) {
  const view = useLoad(() => api.brief(client, day), [client, day]);
  return (
    <Await result={view}>
      {(b) => (
        <>
          <p className="crumbs">
            <a href={link()}>Clients</a> / {b.client_id}
          </p>
          <h1>Opportunity brief</h1>
          <p className="muted">
            {b.offer} · as of <span className="mono">{b.as_of}</span>
          </p>
          {b.thin && (
            <p className="note" role="note">
              Thin sources: only a few entries are strong enough. Nothing was added to fill the
              space.
            </p>
          )}
          <Table title="Accounts to approach" rows={b.accounts} client={b.client_id} day={b.as_of} />
          <Table title="Tenders to watch" rows={b.tenders} client={b.client_id} day={b.as_of} />
          {b.weaker.length > 0 && (
            <details>
              <summary>Also found, weaker ({b.weaker.length})</summary>
              <ul className="plain">
                {b.weaker.map((r) => (
                  <li key={r.rank}>
                    <a href={link("c", b.client_id, b.as_of, "e", r.rank)}>{r.company}</a>{" "}
                    <span className="muted">
                      {r.stream}, {r.requirement}, {r.why_now}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          )}
          <p className="muted small">
            Requirement <em>stated</em> means a verified quote names what you sell;{" "}
            <em>inferred</em> is a possibility only. <em>Watch only</em> means a tender before
            award: the material buyer is not known yet.
          </p>
          {b.notes.length > 0 && (
            <ul className="plain muted small">
              {b.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </Await>
  );
}
