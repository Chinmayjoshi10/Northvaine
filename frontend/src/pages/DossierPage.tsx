import type { ReactNode } from "react";
import { api, safeHref } from "../api";
import { Await, ModelText, StatusPill } from "../components";
import { link } from "../routes";
import type { Dossier } from "../types";
import { useLoad } from "../useLoad";
import { FeedbackForm } from "./FeedbackForm";

function Section({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section className="section" aria-labelledby={`s${n}`}>
      <h2 id={`s${n}`}>
        <span className="mono num">{n}</span> {title}
      </h2>
      {children}
    </section>
  );
}

function ExternalLink({ url }: { url: string }) {
  const href = safeHref(url);
  return href ? (
    <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="break">
      {url}
    </a>
  ) : (
    <span className="break mono">{url} (link not shown)</span>
  );
}

function Body({ d, client, day }: { d: Dossier; client: string; day: string }) {
  return (
    <>
      <p className="crumbs">
        <a href={link()}>Clients</a> / <a href={link("c", client, day)}>{client} brief</a> /{" "}
        {d.rank}
      </p>
      <h1>{d.company}</h1>
      <p>
        <StatusPill status={d.status} /> <span className="muted">{d.country}</span>{" "}
        <span className="mono">evidence: {d.strength}</span>
      </p>
      <p className="note" role="note">
        <strong>Caution:</strong> {d.caution}
      </p>
      <p className="muted small">{d.stream_note}</p>
      {d.rank_reasons.length > 0 && (
        <details>
          <summary>Why it is ranked here</summary>
          <ul>
            {d.rank_reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </details>
      )}

      <Section n={1} title="Who">
        <p>
          {d.company}, {d.country}. Roles: {d.who_roles.join(", ") || "not stated"}.
        </p>
      </Section>
      <Section n={2} title="What happened">
        <p>{d.what}</p>
      </Section>
      <Section n={3} title="When">
        <ul>
          {d.when.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      </Section>
      <Section n={4} title="Why it creates demand">
        <ModelText text={d.demand.text} model={d.demand.model_written && d.demand.text !== "not stated"} />
      </Section>
      <Section n={5} title="Evidence">
        {d.claims.length === 0 && <p>not stated</p>}
        {d.claims.map((c) => (
          <figure key={c.ref} className="claim">
            <figcaption>
              <span className="mono ref">[{c.ref}]</span> {c.statement}
            </figcaption>
            <blockquote>{c.quote}</blockquote>
            {c.is_value && (
              <p className="muted small">
                Value of the whole contract, not the share for what you sell.
              </p>
            )}
            <p className="small">
              Source: {c.source} · <ExternalLink url={c.url} />
            </p>
          </figure>
        ))}
      </Section>
      <Section n={6} title="Sources">
        <ul className="plain">
          {d.sources.map((s) => (
            <li key={`${s.url}${s.name}`}>
              <ExternalLink url={s.url} />
              <div className="muted small">
                {s.name} · available {s.available} · {s.kinds.join(", ")}
              </div>
            </li>
          ))}
          {d.sources.length === 0 && <li>not stated</li>}
        </ul>
      </Section>
      <Section n={7} title="Why a buyer, not a competitor or publisher">
        <p>
          Requirement: <strong>{d.requirement}</strong>
          {d.requirement_ref ? ` [${d.requirement_ref}]` : ""}
          {d.requirement !== "stated" &&
            " (no verified quote names what you sell; treat this as a possibility)"}
          .
        </p>
        {d.who_buys && <p>Who buys: {d.who_buys}</p>}
        <p>Direct buyer: {d.direct_buyer}.</p>
        <ModelText
          text={d.buyer_reason.text}
          model={d.buyer_reason.model_written && d.buyer_reason.text !== "not stated"}
        />
        {d.likely_bidders.length > 0 && (
          <>
            <h3>Likely bidders</h3>
            <p className="muted small">
              Companies that won similar awards in the same country recently, from official award
              records.
            </p>
            <ul className="plain">
              {d.likely_bidders.map((b) => (
                <li key={b.name + b.source_url} className="claim">
                  <strong>{b.name}</strong>{" "}
                  <span className="muted">
                    {b.country ?? "country not stated"} · {b.wins} win{b.wins === 1 ? "" : "s"}
                    {b.last_won ? ` · last ${b.last_won}` : ""}
                  </span>
                  <blockquote>{b.quote}</blockquote>
                  <p className="small">
                    <ExternalLink url={b.source_url} />
                  </p>
                </li>
              ))}
            </ul>
          </>
        )}
      </Section>
      <Section n={8} title="What is uncertain">
        {d.uncertain.length === 0 ? (
          <p>Nothing flagged.</p>
        ) : (
          <ul>
            {d.uncertain.map((u, i) => (
              <li key={i}>
                {u.model_written && <span className="label">model-written</span>} {u.text}
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section n={9} title="Suggested action">
        <p>
          Status: <strong>{d.status}</strong>. Caution: {d.caution}.
        </p>
        {d.stage_action && <p>Next step for this stage: {d.stage_action}</p>}
        {d.opening_question && <p>Opening question: {d.opening_question}</p>}
        <ModelText
          text={d.suggestion.text}
          model={d.suggestion.model_written && d.suggestion.text !== "not stated"}
        />
        <p className="muted">{d.decision_line}</p>
      </Section>

      <FeedbackForm client={client} day={day} rank={d.rank} company={d.company} />
    </>
  );
}

export function DossierPage({ client, day, rank }: { client: string; day: string; rank: number }) {
  const entry = useLoad(() => api.entry(client, day, rank), [client, day, rank]);
  return <Await result={entry}>{(d) => <Body d={d} client={client} day={day} />}</Await>;
}
