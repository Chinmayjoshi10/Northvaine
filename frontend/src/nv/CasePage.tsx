import { useMemo } from "react";
import type { ReactNode } from "react";
import { api, safeHref } from "../api";
import type { BriefView, Claim, Dossier, Link as Step, LogItem, Row } from "../types";
import { link } from "../routes";
import { useLoad } from "../useLoad";
import { DecisionBox, DotSource } from "./CaseSheet";
import { useDecisions } from "./decide";
import {
  DOT_KIND,
  SLOT,
  awardDay,
  domain,
  headline,
  longDate,
  nice,
  shortDate,
  stripCountry,
} from "./lead";
import { Shell } from "./Shell";
import { readable } from "./StationPage";
import "./case.css";

/** Display text: no citation tags or escape slashes, the first sentence, cut at a word. */
function plain(text: string, max: number): string {
  const clean = text.replace(/\s*\[C\d+\]/g, "").replace(/\\/g, "").trim();
  const first = clean.split(/(?<=\.)\s+(?=[A-Z])/)[0];
  return first.length > max ? `${first.slice(0, max).replace(/\s+\S*$/, "")}…` : first;
}

// The full case page: one lead, read top to bottom, with the decision beside it.
// Every line comes from the dossier or the run record; nothing here is written for the page.

const STAGES = ["Detected", "Watching", "Developing", "Act now", "Won", "Lost"] as const;
type Stage = (typeof STAGES)[number];

/**
 * Where the lead stands, from the data only. A "bid now" / "contact now" status or an act-now
 * label is Act now; a just-changed label, or an award/announcement with a stated requirement,
 * is Developing; anything else is Watching. Won and Lost stay unlit: there is no outcome data.
 */
function stageFor(r: Row): Stage {
  if (r.status === "bid now" || r.status === "contact now" || r.label === "act_now")
    return "Act now";
  if (
    r.label === "just_changed" ||
    ((r.stream === "award" || r.stream === "announcement") && r.requirement === "stated")
  )
    return "Developing";
  return "Watching";
}

/** The claim to quote: the one behind the requirement when there is one, else the first with a quote. */
function strongest(d: Dossier): Claim | undefined {
  return d.claims.find((c) => c.ref === d.requirement_ref) ?? d.claims.find((c) => c.quote);
}

function sentenceOf(s: string): string {
  const t = s.trim();
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : "";
}

export function CasePage(props: { client: string; day: string; rank: number }) {
  const { client, day, rank } = props;
  const brief = useLoad(() => api.brief(client, day), [client, day]);
  const dossier = useLoad(() => api.entry(client, day, rank), [client, day, rank]);
  const crumb = (
    <>
      Station <span className="sl">/</span>{" "}
      <b>{dossier.state === "ready" ? nice(dossier.data.company) : client}</b>
    </>
  );
  if (brief.state === "ready" && dossier.state === "ready")
    return (
      <Case client={client} day={day} brief={brief.data} dossier={dossier.data} crumb={crumb} />
    );
  const failed =
    brief.state === "error" ? brief.message : dossier.state === "error" ? dossier.message : null;
  return (
    <Shell client={client} day={day} screen="station" crumb={crumb}>
      <div className="nv-page">
        {failed ? (
          <p className="alert">
            {failed} <a href={link("app", client, day)}>Back to Station</a>
          </p>
        ) : (
          <div className="wait" aria-busy="true" />
        )}
      </div>
    </Shell>
  );
}

function Case(props: {
  client: string;
  day: string;
  brief: BriefView;
  dossier: Dossier;
  crumb: ReactNode;
}) {
  const { client, day, brief, dossier: d, crumb } = props;
  const rows = useMemo(
    () => [...brief.accounts, ...brief.tenders, ...brief.weaker],
    [brief],
  );
  const row = rows.find((r) => r.rank === d.rank) ?? null;
  const { decided, decide, followed, follow } = useDecisions(client, brief);

  if (!row)
    return (
      <Shell client={client} day={day} screen="station" crumb={crumb}>
        <div className="nv-page">
          <p className="alert">
            This case is not in this edition. <a href={link("app", client, day)}>Back to Station</a>
          </p>
        </div>
      </Shell>
    );

  const chain = row.chain ?? [];
  const by = (state: Step["state"]) => chain.filter((l) => l.state === state);
  const lit = STAGES.indexOf(stageFor(row));
  const claim = strongest(d);
  const claimHref = claim ? safeHref(claim.url) : null;
  const published = awardDay(row);
  const stated = d.claims.filter((c) => c.statement.trim() !== "");
  // newest first in the run record; a history reads oldest first
  const allDots = row.dots ?? d.dots ?? [];
  const newest = allDots.slice(0, 4);
  // with dots, every dated or sourced fact is the history (each with its source)
  const history: LogItem[] =
    allDots.length > 0 ? [] : (brief.log ?? []).filter((l) => l.rank === d.rank).reverse();
  const title =
    row.stream === "tender" || row.stream === "award"
      ? headline(row)
      : row.stream === "trade"
        ? `${nice(row.company)} imports your product`
        : `${nice(row.company)}: ${plain(row.what, 90)}`;
  const against = readable(d.caution) ? sentenceOf(d.caution).replace(/[.;]?$/, ".") : "";

  return (
    <Shell client={client} day={day} screen="station" crumb={crumb} counts={{
        leads: rows.length,
        motion: rows.filter((r) => r.back_in_motion).length,
      }}>
      <div className="nv-case">
        <article className="art">
          <a className="back mono" href={link("app", client, day)}>
            ← Station
          </a>
          <div className="top">
            <span className="dateline">
              <b>{d.country}</b> · {longDate(brief.as_of).date}
            </span>
            <ol className="stage" aria-label="Stage">
              {STAGES.map((s, i) => (
                <li
                  key={s}
                  className={i === lit ? "on" : i < lit ? "past" : ""}
                  aria-current={i === lit ? "step" : undefined}
                >
                  {s}
                </li>
              ))}
            </ol>
          </div>

          <h1 className="hl">{title}</h1>
          {d.headline && (
            <p className="lede">
              <b>{d.headline}</b> {d.why_you ?? ""}
            </p>
          )}
          {d.demand.text && (
            <p className="lede">
              {d.requirement === "inferred" ? (
                <>
                  <span className="infer">{sentenceOf(d.demand.text)}</span>
                  <span className="tag">inferred</span>
                </>
              ) : (
                sentenceOf(d.demand.text)
              )}
            </p>
          )}

          {claim?.quote && (
            <blockquote className="pull">
              {claim.quote}
              <cite>
                {claim.source}
                {domain(claim.url) && <> · {domain(claim.url)}</>}
                {published && <> · published {shortDate(published)}</>}
                {claimHref && (
                  <>
                    {" "}
                    <a href={claimHref} target="_blank" rel="noreferrer noopener">
                      Open the source ↗
                    </a>
                  </>
                )}
              </cite>
            </blockquote>
          )}

          {newest.length > 0 ? (
            <ol
              className="chain"
              aria-label="Where it comes from"
              style={{ gridTemplateColumns: `repeat(${newest.length}, minmax(0, 1fr)) 56px` }}
            >
              {[...newest].reverse().map((dot, i) => (
                <li key={i} className="link stated">
                  <span className="node" aria-hidden="true" />
                  <span className="caps">{DOT_KIND[dot.kind]}</span>
                  <span className="l">{dot.line}</span>
                  <DotSource dot={dot} />
                </li>
              ))}
              <li className="link you">
                <span className="node" aria-hidden="true" />
                <span className="caps">You</span>
              </li>
            </ol>
          ) : (
            chain.length > 0 && (
            <ol
              className="chain"
              aria-label="Commercial chain"
              style={{ gridTemplateColumns: `repeat(${chain.length}, minmax(0, 1fr)) 56px` }}
            >
              {chain.map((l) => (
                <li key={l.slot} className={`link ${l.state}`}>
                  <span className="node" aria-hidden="true" />
                  <span className="caps">{SLOT[l.slot]}</span>
                  <span className="l">{nice(stripCountry(l.label))}</span>
                  {l.state === "unknown" && <span className="sr"> (not yet known)</span>}
                </li>
              ))}
              <li className="link you">
                <span className="node" aria-hidden="true" />
                <span className="caps">You</span>
              </li>
            </ol>
            )
          )}

          <div className="kiu">
            <section aria-label="On record">
              <span className="caps">On record</span>
              {stated.map((c) => (
                <div className="r" key={c.ref}>
                  <i className="m s" />
                  <span>
                    {sentenceOf(c.statement)}
                    <sup>{c.ref}</sup>
                  </span>
                </div>
              ))}
              {(d.timing_signals ?? []).map((t) => (
                <div className="r" key={t}>
                  <i className="m s" />
                  <span>{t}</span>
                </div>
              ))}
              {stated.length === 0 && (d.timing_signals ?? []).length === 0 && (
                <div className="r u">nothing yet</div>
              )}
            </section>
            <section aria-label="Inferred">
              <span className="caps">Inferred</span>
              {by("inferred").map((l) => (
                <div className="r h" key={l.slot}>
                  <i className="m h" />
                  <span>
                    {SLOT[l.slot]}: {nice(stripCountry(l.label))}
                  </span>
                </div>
              ))}
              {d.buyer_reason.text && (
                <div className="r h">
                  <i className="m h" />
                  <span>{sentenceOf(d.buyer_reason.text)}</span>
                </div>
              )}
              {by("inferred").length === 0 && !d.buyer_reason.text && (
                <div className="r u">nothing</div>
              )}
            </section>
            <section aria-label="Not yet known">
              <span className="caps">Not yet known</span>
              {d.uncertain.map((u, i) => (
                <div className="r u" key={i}>
                  <i className="m u" />
                  <span>{u.text}</span>
                </div>
              ))}
              {d.uncertain.length === 0 && <div className="r u">nothing open</div>}
            </section>
          </div>
        </article>

        <aside className="side">
          <DecisionBox
            row={row}
            question={d.decision_line || "Is this one for you?"}
            decided={decided[row.rank] ?? null}
            onDecide={(x) => decide(row, x)}
            followed={followed[row.rank] ?? []}
            onFollow={(f) => follow(row, f)}
          />

          <div className="sec">
            <span className="caps">How to reach them · company only</span>
            {d.from_list && (
              <p className="edlabel">
                <span className="mono lab-chip">From your list</span>
                <span className="lab-why">
                  One of your target accounts, checked like any other lead.
                </span>
              </p>
            )}
            {d.possible_distributor && (
              <p className="edlabel">
                <span className="mono lab-chip">Possible distributor</span>
                <span className="lab-why">
                  A possible partner: it sells your kind of product. Decide whether it is a
                  distributor for you or a competitor.
                </span>
              </p>
            )}
            <div className="kv">
              <span className="caps">Buyer</span>
              <span>{d.who_buys ?? <span className="dash">not stated yet</span>}</span>
              {d.who_roles.length > 0 && (
                <>
                  <span className="caps">Roles</span>
                  <span>{d.who_roles.join(", ")}</span>
                </>
              )}
              {d.company_site && (
                <>
                  <span className="caps">Site</span>
                  <span>
                    <a href={`https://${d.company_site}`} target="_blank" rel="noreferrer">
                      {d.company_site}
                    </a>
                    {d.site_proof && <> · Site confirmed by {d.site_proof}</>}
                  </span>
                </>
              )}
              {!d.company_site && !d.company_contact && (
                <>
                  <span className="caps">Site</span>
                  <span className="dash">not found in this run</span>
                </>
              )}
              {d.reach?.register_url && (
                <>
                  <span className="caps">Register</span>
                  <span>
                    <a href={d.reach.register_url} target="_blank" rel="noreferrer">
                      {d.reach.register_label ?? "Official company register"}
                    </a>
                  </span>
                </>
              )}
              {(d.matched_lines ?? []).length > 0 && (
                <>
                  <span className="caps">Catalogue</span>
                  <span>
                    Matches your catalogue lines: {(d.matched_lines ?? []).join(", ")}
                  </span>
                </>
              )}
              {d.company_contact?.email && (
                <>
                  <span className="caps">Email</span>
                  <span>
                    <a href={`mailto:${d.company_contact.email}`}>{d.company_contact.email}</a>
                  </span>
                </>
              )}
              {d.company_contact?.phone && (
                <>
                  <span className="caps">Phone</span>
                  <span>{d.company_contact.phone}</span>
                </>
              )}
              {d.company_contact && (
                <>
                  <span className="caps">Source</span>
                  <span>
                    from{" "}
                    <a href={d.company_contact.url} target="_blank" rel="noreferrer">
                      {new URL(d.company_contact.url).host}
                    </a>
                  </span>
                </>
              )}
              {(d.sources_seen ?? []).length >= 2 && (
                <>
                  <span className="caps">Seen in</span>
                  <span>{(d.sources_seen ?? []).join(", ")}</span>
                </>
              )}
              {d.like_customers.length > 0 && (
                <>
                  <span className="caps">Like your customers</span>
                  <span>{d.like_customers.join(". ")}</span>
                </>
              )}
              {(d.say ?? d.opening_question) && (
                <>
                  <span className="caps">Ask</span>
                  <span>{d.say ?? d.opening_question}</span>
                </>
              )}
            </div>
          </div>

          <div className="sec">
            <span className="caps">History</span>
            {history.length === 0 &&
            allDots.length === 0 &&
            !d.stage_action &&
            !row?.developments?.length ? (
              <p className="dash">nothing recorded yet</p>
            ) : (
              <ol className="tl">
                {allDots.map((dot, i) => (
                  <li className="ev" key={`dot${i}`}>
                    <DotSource dot={dot} />
                    {dot.line}
                  </li>
                ))}
                {history.map((l, i) => (
                  <li className="ev" key={i}>
                    <span className="mono">{l.at ? shortDate(l.at) : "—"}</span>
                    {plain(l.text, 140)}
                  </li>
                ))}
                {(row?.developments ?? []).map((t, i) => (
                  <li className="ev" key={`dev${i}`}>
                    <span className="mono">{shortDate(brief.as_of)}</span>
                    {t}
                  </li>
                ))}
                {d.stage_action && (
                  <li className="ev f">
                    <span className="mono">next</span>
                    {sentenceOf(d.stage_action)}
                  </li>
                )}
              </ol>
            )}
          </div>

          {against && (
            <div className="sec">
              <span className="caps">Evidence against</span>
              <p className="against">{against}</p>
            </div>
          )}
        </aside>
      </div>
    </Shell>
  );
}
