import { useMemo } from "react";
import { api } from "../api";
import type { Row } from "../types";
import { link } from "../routes";
import { useLoad } from "../useLoad";
import { nice, shortDate } from "./lead";
import { Shell } from "./Shell";
import "./motion.css";

// Back in motion (D110): companies the radar saw on an earlier night that now show something
// new. Computed by code from the saved runs; nothing here is a guess.

function Item({ r, client, day }: { r: Row; client: string; day: string }) {
  const n = r.seen_runs ?? 0;
  return (
    <li className="mo-item">
      <h2>
        <a href={link("app", client, day, "case", r.rank)}>{nice(r.company)}</a>
      </h2>
      <p className="mo-meta mono">
        {r.country}
        {r.first_seen && <> · first seen {shortDate(r.first_seen)}</>} · seen {n}{" "}
        {n === 1 ? "time" : "times"}
      </p>
      <ul className="mo-changes">
        {(r.developments ?? []).map((t, i) => (
          <li key={i}>{t}</li>
        ))}
      </ul>
      <a className="mo-case mono" href={link("app", client, day, "case", r.rank)}>
        Open the case →
      </a>
    </li>
  );
}

export function MotionPage({ client, day }: { client: string; day: string }) {
  const brief = useLoad(() => api.brief(client, day), [client, day]);
  const moving = useMemo(
    () =>
      brief.state === "ready"
        ? [...brief.data.accounts, ...brief.data.tenders, ...brief.data.weaker].filter(
            (r) => r.back_in_motion,
          )
        : [],
    [brief],
  );
  const crumb = (
    <>
      Station <span className="sl">/</span> <b>Back in motion</b>
    </>
  );
  return (
    <Shell
      client={client}
      day={day}
      screen="motion"
      crumb={crumb}
      counts={{ motion: moving.length }}
    >
      <div className="mo">
        <p className="mo-eyebrow mono">Back in motion</p>
        <h1>Companies seen before, with something new</h1>
        {brief.state === "loading" && <p className="mo-empty">Loading…</p>}
        {brief.state === "error" && (
          <p className="mo-empty" role="alert">
            This run could not be loaded.
          </p>
        )}
        {brief.state === "ready" &&
          (moving.length === 0 ? (
            <p className="mo-empty">
              Nothing has moved since the last runs. Companies seen before appear here when
              something new happens to them.
            </p>
          ) : (
            <ul className="mo-list">
              {moving.map((r) => (
                <Item key={r.rank} r={r} client={client} day={day} />
              ))}
            </ul>
          ))}
      </div>
    </Shell>
  );
}
