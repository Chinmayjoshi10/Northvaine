import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../api";
import type { BriefView, Row } from "../types";
import { link } from "../routes";
import { useLoad } from "../useLoad";
import { CaseSheet, optionsFor } from "./CaseSheet";
import { useDecisions } from "./decide";
import {
  awardDay,
  clientLabel,
  daysLeft,
  decisionsOf,
  headline,
  longDate,
  nice,
  projectOf,
  shortDate,
  stageOf,
  typeOf,
  unknownSteps,
  windowOf,
} from "./lead";
import { LessonNote, progressLine } from "./LessonNote";
import { Shell } from "./Shell";
import { TerritoryMap, laneCountries, regionName } from "./TerritoryMap";
import type { Place } from "./TerritoryMap";
import "./leads.css";
import "./station.css";

// Station: the edition. What happened, where, and the few decisions that cost something to
// delay. Every line is assembled from the run record; nothing here is written by a model.

export function StationPage({ client, day }: { client: string; day: string }) {
  const brief = useLoad(() => api.brief(client, day), [client, day]);
  const crumb = (
    <>
      Station <span className="sl">/</span>{" "}
      <b>{brief.state === "ready" ? clientLabel(brief.data) : client}</b>
    </>
  );
  if (brief.state !== "ready")
    return (
      <Shell client={client} day={day} screen="station" crumb={crumb}>
        <div className="nv-page">
          {brief.state === "loading" ? (
            <div className="wait" aria-busy="true" />
          ) : (
            <p className="alert">{brief.message}</p>
          )}
        </div>
      </Shell>
    );
  return <Station client={client} day={day} brief={brief.data} crumb={crumb} />;
}

const MONTH = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec";

/** The urgency tag: a stated tender deadline or award, else a date in the label's reason, else nothing. */
function urgency(r: Row): string | null {
  if (
    daysLeft(r) !== null ||
    awardDay(r) ||
    /closes (today|tomorrow)/.test(r.why_now)
  )
    return windowOf(r);
  // A label's dates are past changes, not deadlines: show the latest as "changed Mon YYYY".
  const dates = (r.label_reason ?? "").match(/\d{4}-\d{2}(?:-\d{2})?/g);
  if (!dates) return null;
  const [y, m] = dates.sort()[dates.length - 1].split("-");
  return `changed ${MONTH.split("|")[Number(m) - 1]} ${y}`;
}

/** A caution that only points at a section of the brief says nothing here. */
export function readable(caution: string): boolean {
  return !/\bsections?\s*\d|read section/i.test(caution);
}

/** The clock time when `at` carries one, else the short date. */
function stamp(at: string | null): string {
  if (!at) return "—";
  const m = at.match(/T(\d{2}:\d{2})/);
  return m ? m[1] : shortDate(at);
}

/** The company in bold when the text names it, else the company followed by the text. */
function withCompany(text: string, company: string | null): ReactNode {
  if (!company) return text;
  const i = text.indexOf(company);
  if (i < 0)
    return (
      <>
        <b>{nice(company)}</b> {text}
      </>
    );
  return (
    <>
      {text.slice(0, i)}
      <b>{nice(company)}</b>
      {text.slice(i + company.length)}
    </>
  );
}

/** A short fact for a map label: the first fact of the label's reason, cut at a word. */
function shortFact(r: Row): string {
  const t = (r.label_reason ?? "").split(";")[0].trim();
  return t.length > 40 ? `${t.slice(0, 40).replace(/\s+\S*$/, "")}…` : t;
}

/** The dateline's place: the authority when the record states it, else the company. */
function where(r: Row): string {
  const auth = r.chain?.find(
    (l) => l.slot === "authority" && l.state !== "unknown",
  );
  return auth ? auth.label : r.company;
}

function question(r: Row): string {
  if (r.stream === "tender" && r.account_role === "direct_purchaser")
    return "Bid on this tender?";
  if (r.stream === "tender")
    return "Approach the likely bidders before the award?";
  if (r.stream === "trade") return `Approach ${nice(r.company)}?`;
  return `Take ${nice(r.company)}?`;
}

function sentence(s: string): string {
  const t = s.trim();
  return t ? t.charAt(0).toUpperCase() + t.slice(1).replace(/[.;]?$/, ".") : "";
}

const LABEL: Record<string, string> = {
  act_now: "Act now",
  just_changed: "Just changed",
  account_to_work: "Account to work",
};

const VERB: Record<string, string> = {
  tender_published: "opened a tender",
  contract_awarded: "won a contract",
  imports_recorded: "imports your product",
  product_launch: "launched a product",
  facility_opened: "opened a facility",
  expansion: "is expanding",
  funding: "raised funding",
};

const OPP_ORDER: Record<string, number> = {
  connected: 0,
  approach_now: 1,
  relationship: 2,
  looking: 3,
  watch: 4,
};
const OPP_KIND: Record<string, "act" | "developing" | "watching"> = {
  connected: "act",
  approach_now: "act",
  relationship: "developing",
  looking: "developing",
  watch: "watching",
};

function Station(props: {
  client: string;
  day: string;
  brief: BriefView;
  crumb: ReactNode;
}) {
  const { client, day, brief, crumb } = props;
  const rows = useMemo(
    () => [...brief.accounts, ...brief.tenders, ...brief.weaker],
    [brief],
  );
  // The daily edition (D103) leads when the run made one; older runs keep the urgency order.
  const decisions = useMemo(() => {
    return decisionsOf(brief, rows);
  }, [rows, brief]);
  // a day with no edition still shows the few watch-list companies worth a look
  const watchBest = useMemo(
    () =>
      (brief.watch_best ?? [])
        .map((n) => rows.find((r) => r.rank === n))
        .filter((r): r is Row => r !== undefined),
    [rows, brief],
  );
  const { decided, decide, followed, follow, learning, lesson, dismiss } =
    useDecisions(client, brief);
  const [open, setOpen] = useState<Row | null>(null);
  const [showAll, setShowAll] = useState(false);
  // new vs returning comes from the run record (a row is returning when the previous run had it)
  const returning = rows.filter((r) => r.returning === true).length;
  const fresh = rows.length - returning;
  const firstEdition = !brief.previous;

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const places = useMemo(() => {
    const hot = new Set(decisions.map((r) => r.rank));
    const mine = new Set(brief.accounts.map((r) => r.rank));
    const by = new Map<string, Place & { lead: Row }>();
    for (const r of rows) {
      if (!r.country || /not stated/.test(r.country)) continue;
      const at = r.place;
      const id = at ? `${r.country}@${at.lat},${at.lon}` : r.country;
      const p = by.get(id) ?? {
        country: r.country,
        ...(at ? { lat: at.lat, lon: at.lon, label: at.label } : {}),
        total: 0,
        toDecide: 0,
        kind: "watching" as const,
        account: false,
        lead: r,
      };
      p.total += 1;
      if (hot.has(r.rank)) {
        p.toDecide += 1;
        p.kind = "act";
      } else if (p.kind !== "act" && stageOf(r) === "Developing")
        p.kind = "developing";
      if (mine.has(r.rank)) p.account = true;
      // the label names the place's best row: by opportunity label when the rows have one,
      // else a decision first, else the best rank
      const sr = OPP_ORDER[r.opportunity?.label ?? ""] ?? 9;
      const sl = OPP_ORDER[p.lead.opportunity?.label ?? ""] ?? 9;
      const better =
        sr !== sl && Math.min(sr, sl) < 9
          ? sr < sl
          : hot.has(r.rank) !== hot.has(p.lead.rank)
            ? hot.has(r.rank)
            : r.rank < p.lead.rank;
      if (better) p.lead = r;
      by.set(id, p);
    }
    return [...by.values()].map(({ lead, ...p }) => {
      const fact = shortFact(lead);
      const opp = lead.opportunity;
      return {
        ...p,
        // the marker's colour is the best label among its leads, when the rows carry one
        kind: opp ? OPP_KIND[opp.label] : p.kind,
        rank: lead.rank,
        tip: {
          company: nice(lead.company),
          word: opp?.word,
          why: opp?.why_now || lead.why_now,
        },
        note: fact ? `${nice(lead.company)} · ${fact}` : nice(lead.company),
      };
    });
  }, [rows, decisions, brief.accounts]);
  const homeName = brief.home_country ? regionName(brief.home_country) : null;
  const showLanes =
    !!homeName && laneCountries(places, brief.markets, brief.home_country).length > 0;
  const unplaced = rows.filter(
    (r) => !r.country || /not stated/.test(r.country),
  ).length;

  // the masthead: today's most urgent decision; the newest award only when there is none
  const lead =
    decisions[0] ??
    [...rows]
      .filter((r) => awardDay(r))
      .sort((a, b) => awardDay(b)!.localeCompare(awardDay(a)!))[0];
  // the dek: the lead's own reason, then plain counts of the rest; zero counts are skipped
  const dek: ReactNode[] = [];
  const top = decisions[0];
  if (top?.headline) {
    if (top.why_you) dek.push(<span key="l">{top.why_you} </span>);
  } else if (top?.label_reason) {
    dek.push(
      <span key="l">
        <b>{nice(top.company)}</b>: {top.label_reason.replace(/[.\s]+$/, "")}
        .{" "}
      </span>,
    );
  }
  const labelled = rows.filter((r) => r !== top);
  const changed = labelled.filter((r) => r.label === "just_changed").length;
  const toWork = labelled.filter((r) => r.label === "account_to_work").length;
  if (changed || toWork) {
    const parts: string[] = [];
    if (changed) parts.push(`${changed} more changed recently`);
    if (toWork)
      parts.push(`${toWork} ${toWork === 1 ? "account" : "accounts"} to work`);
    dek.push(<span key="n">{parts.join("; ")}.</span>);
  }

  const feed = useMemo(() => {
    const byRank = new Map(rows.map((r) => [r.rank, r]));
    return (brief.log ?? []).map((l) => ({
      l,
      r: l.rank !== null ? (byRank.get(l.rank) ?? null) : null,
    }));
  }, [brief.log, rows]);
  const shown = showAll ? feed : feed.slice(0, 8);

  const title = (r: Row): string => {
    if (r.stream === "tender" || r.stream === "award") return headline(r, 44);
    const ev = (brief.log ?? []).find((l) => l.rank === r.rank && VERB[l.kind]);
    return ev ? `${nice(r.company)} ${VERB[ev.kind]}` : headline(r, 44);
  };
  // the masthead keeps who did what, the number and the date; a record's long title stays on the card
  const brief_ = (h: string): string => {
    const cut = h.indexOf(": ");
    const tail = h.lastIndexOf(" (");
    return cut > 0 && tail > cut ? `${h.slice(0, cut)}${h.slice(tail)}` : h;
  };
  // the card's dated line: the opportunity's reason when short, else just its date
  const shortWhy = (r: Row): string => {
    const why = r.opportunity?.why_now ?? "";
    if (why.length <= 60) return why;
    const day = why.match(/\d{4}-\d{2}-\d{2}/g)?.pop();
    return day ? `${r.stream === "tender" ? "opened" : "on record"} ${day}` : "";
  };
  const { weekday, date } = longDate(brief.as_of);
  const f = brief.funnel;
  const setAside = f ? Object.values(f.rejected).reduce((a, b) => a + b, 0) : 0;
  const steps = f
    ? [
        { k: "Documents read", n: f.documents },
        { k: "Companies found", n: f.candidates },
        { k: "Set aside", n: setAside },
        { k: "On record", n: f.briefed },
      ]
    : [];
  const most = Math.max(1, ...steps.map((s) => s.n));

  return (
    <Shell
      client={client}
      day={day}
      screen="station"
      crumb={crumb}
      counts={{
        leads: rows.length,
        motion: rows.filter((r) => r.back_in_motion).length,
      }}
      peek={open !== null}
      overlay={
        <>
          <div className="nv-scrim" onClick={() => setOpen(null)} />
          <CaseSheet
            row={open}
            decided={open ? (decided[open.rank] ?? null) : null}
            onDecide={(d) => (open ? decide(open, d) : Promise.resolve())}
            followed={open ? (followed[open.rank] ?? []) : []}
            onFollow={(f) => (open ? follow(open, f) : Promise.resolve())}
            fullHref={
              open ? link("app", client, day, "case", open.rank) : undefined
            }
            connectionsHref={
              open && (open.stream === "tender" || open.stream === "award")
                ? link("app", client, day, "connections", open.rank)
                : undefined
            }
            onClose={() => setOpen(null)}
          />
          <LessonNote lesson={lesson} learning={learning} onClose={dismiss} />
        </>
      }
    >
      <div className="st">
        <header className="mast">
          <div>
            <div className="ed">
              <span className="caps">{weekday} edition</span>
              <span className="rule" />
              <span className="mono">{date}</span>
            </div>
            <h1 className="hl">
              {lead ? (
                <button
                  type="button"
                  className="hlink"
                  onClick={() => setOpen(lead)}
                >
                  {lead.headline ? brief_(lead.headline) : title(lead)}
                </button>
              ) : (
                "A quiet edition"
              )}
            </h1>
            {dek.length > 0 && <p className="lede">{dek}</p>}
          </div>
          <div className="stats">
            <div className="stat sig">
              <b>{decisions.length}</b>
              <span className="caps">to decide</span>
            </div>
            <div className="stat">
              <b>{fresh}</b>
              <span className="caps">new</span>
            </div>
            <div className="stat">
              <b>{firstEdition ? "—" : returning}</b>
              <span className="caps">returning</span>
              {firstEdition && <span className="cap2">first edition</span>}
            </div>
          </div>
        </header>

        <section className="map" aria-label="Territory">
          <div className="hd">
            <span className="caps">Territory</span>
            <span className="legend mono">
              <span>
                <i className="m y" />
                act
              </span>
              <span>
                <i className="m s" />
                developing
              </span>
              <span>
                <i className="m h" />
                watching
              </span>
              <span>
                <i className="m a" />
                your account
              </span>
              {homeName && (
                <span>
                  <i className="m base" />
                  your base
                </span>
              )}
              {showLanes && (
                <span>
                  <i className="ln" />
                  trade lane
                </span>
              )}
            </span>
          </div>
          <TerritoryMap
            places={places}
            markets={brief.markets}
            home={brief.home_country}
            onOpen={(rank) => setOpen(rows.find((r) => r.rank === rank) ?? null)}
          />
          <div className="mapnote">
            <span>
              {homeName
                ? "One marker per country, sized by leads; lanes run from your base to markets with leads to act on"
                : "Placed by registered office where the record gives one, else by country"}
            </span>
            {unplaced > 0 && (
              <span>
                {unplaced} {unplaced === 1 ? "lead states" : "leads state"} no
                country
              </span>
            )}
          </div>
        </section>

        <section className="dec" aria-label="To decide">
          <div className="hd">
            <span className="caps">To decide · by cost of waiting</span>
            <span className="mono">{decisions.length}</span>
          </div>
          {decisions.length === 0 && (
            <p className="quiet">
              Nothing to act on today.{" "}
              {rows.length > 0 &&
                `${rows.length} ${rows.length === 1 ? "company is" : "companies are"} on watch; you will see one here when it changes.`}
            </p>
          )}
          {decisions.length === 0 && watchBest.length > 0 && (
            <>
              <div className="hd">
                <span className="caps">Worth watching</span>
                <span className="mono">{watchBest.length}</span>
              </div>
              {watchBest.map((r) => (
                <article className="d" key={r.rank}>
                  <div className="meta">
                    <span className="dateline">
                      <b>{nice(where(r))}</b> · {typeOf(r).toLowerCase()}
                    </span>
                  </div>
                  <h2 className="q">
                    <button type="button" onClick={() => setOpen(r)}>
                      {nice(r.company)}
                    </button>
                  </h2>
                  <p className="edlabel">
                    {r.opportunity && (
                      <span className="mono lab-chip">
                        {r.opportunity.word} · {r.opportunity.words}
                      </span>
                    )}
                    {r.from_list && (
                      <span className="mono lab-chip">From your list</span>
                    )}
                    {r.possible_distributor && (
                      <span className="mono lab-chip">Possible distributor</span>
                    )}
                  </p>
                  <p className="why">
                    <b>{r.headline || r.opportunity?.why_now}</b>{" "}
                    {r.why_you ?? ""}
                  </p>
                </article>
              ))}
            </>
          )}
          {decisions.map((r, i) => {
            const d = daysLeft(r);
            const hot =
              stageOf(r) === "Act now" ||
              (d !== null && d <= 7) ||
              !!awardDay(r);
            // the chain's steps are a procurement record's; other leads do not have them
            const missing =
              r.stream === "tender" || r.stream === "award"
                ? unknownSteps(r)
                : [];
            const done = decided[r.rank];
            return (
              <article
                className="d"
                key={r.rank}
                style={{ animationDelay: `${120 + i * 70}ms` }}
              >
                <div className="meta">
                  <span className="dateline">
                    <b>{nice(where(r))}</b> ·{" "}
                    {r.contract_nature ? `${r.contract_nature} ` : ""}
                    {typeOf(r).toLowerCase()}
                  </span>
                  {(shortWhy(r) || urgency(r)) && (
                    <span className={`wait${hot ? " hot" : ""}`}>
                      {shortWhy(r) || urgency(r)}
                    </span>
                  )}
                </div>
                <h2 className="q">
                  <button type="button" onClick={() => setOpen(r)}>
                    {question(r)}
                  </button>
                </h2>
                {(r.opportunity ||
                  (r.timing_signals ?? []).length >= 2 ||
                  (r.sources_seen ?? []).length >= 2 ||
                  r.label ||
                  r.possible_distributor ||
                  r.from_list ||
                  r.back_in_motion) && (
                  <p className="edlabel">
                    {r.opportunity && (
                      <span className="mono lab-chip">
                        {r.opportunity.word} · {r.opportunity.words}
                      </span>
                    )}
                    {!r.opportunity && (r.sources_seen ?? []).length >= 2 && (
                      <span className="mono lab-chip">
                        {(r.sources_seen ?? []).length} SOURCES
                      </span>
                    )}
                    {(r.timing_signals ?? []).length >= 2 && (
                      <span className="mono lab-chip">
                        {(r.timing_signals ?? []).length} SIGNALS
                      </span>
                    )}
                    {r.from_list && (
                      <span className="mono lab-chip">From your list</span>
                    )}
                    {r.possible_distributor && (
                      <span className="mono lab-chip">Possible distributor</span>
                    )}
                    {(r.matched_lines ?? []).length > 0 && (
                      <span className="mono lab-chip">
                        LINE: {(r.matched_lines ?? [])[0]}
                      </span>
                    )}
                    {r.back_in_motion && (
                      <span className="mono lab-chip">Back in motion</span>
                    )}
                    {r.label && (
                      <span className="mono lab-chip">
                        {LABEL[r.label] ?? r.label}
                      </span>
                    )}
                    {r.label && r.label_reason && !r.headline && (
                      <span className="lab-why">{r.label_reason}</span>
                    )}
                  </p>
                )}
                <p className="why">
                  {r.headline ? (
                    <>
                      <b>{r.headline}</b> {r.why_you ?? ""}
                    </>
                  ) : (
                    <>
                      <b>{projectOf(r)}.</b>{" "}
                      {readable(r.caution) && sentence(r.caution)}
                    </>
                  )}
                  {missing.length > 0 &&
                    ` Not yet known: ${missing.join(", ")}.`}{" "}
                  <button
                    type="button"
                    className="against"
                    onClick={() => setOpen(r)}
                  >
                    Evidence against →
                  </button>
                </p>
                {done ? (
                  <div className="opts">
                    <span className="did mono">✓ {done}</span>
                    <button
                      type="button"
                      className="btn"
                      onClick={() => setOpen(r)}
                    >
                      Open the case
                    </button>
                  </div>
                ) : (
                  <div className="opts">
                    {optionsFor(r).map((o, j) => (
                      <button
                        key={o.kind}
                        type="button"
                        className={`btn${j === 0 ? " rec" : ""}`}
                        onClick={() =>
                          // a "no" needs its reason, which the case sheet asks for
                          o.kind === "drop"
                            ? setOpen(r)
                            : decide(r, { kind: o.kind, label: o.label })
                        }
                      >
                        {o.label}
                      </button>
                    ))}
                  </div>
                )}
              </article>
            );
          })}
        </section>

        <div className="bottom">
          <section className="feed cell" aria-label="Overnight">
            <div className="hd">
              <span className="caps">Overnight</span>
              <span className="mono">developments only</span>
            </div>
            {feed.length === 0 && (
              <p className="quiet">No developments in this run.</p>
            )}
            {shown.map(({ l, r }, i) => {
              const mark =
                l.kind === "set_aside"
                  ? "h"
                  : r && (stageOf(r) === "Act now" || decisions.includes(r))
                    ? "y"
                    : "s";
              const body = (
                <>
                  <span className="mono">{stamp(l.at)}</span>
                  <i className={`m ${mark}`} />
                  <span className="t">{withCompany(l.text, l.company)}</span>
                </>
              );
              return r ? (
                <button
                  type="button"
                  className="e"
                  key={i}
                  onClick={() => setOpen(r)}
                >
                  {body}
                </button>
              ) : (
                <div className="e plain" key={i}>
                  {body}
                </div>
              );
            })}
            {feed.length > 8 && (
              <button
                type="button"
                className="more"
                onClick={() => setShowAll(!showAll)}
              >
                {showAll ? "show fewer" : `show all ${feed.length}`}
              </button>
            )}
          </section>

          <section
            className="taught cell"
            aria-label="What your answers changed"
          >
            <div className="hd">
              <span className="caps">What your answers changed</span>
              {learning && (
                <span className="mono">{learning.answers} answers</span>
              )}
            </div>
            {(!learning || learning.lessons.length === 0) && (
              <p className="quiet">
                Answer a decision and I’ll show here what it changed.
              </p>
            )}
            {learning?.lessons.slice(0, 3).map((l) => (
              <div className="l" key={l.received_at}>
                <span className="said">
                  “{l.said}” on <b>{nice(l.company)}</b>:
                </span>{" "}
                {l.change}
              </div>
            ))}
            {learning && learning.answers > 0 && (
              <div className="prog" aria-label={progressLine(learning)}>
                {Array.from({ length: Math.round(learning.needed) }, (_, i) => (
                  <i key={i} className={i < learning.labels ? "on" : ""} />
                ))}
                <span className="mono">{progressLine(learning)}</span>
              </div>
            )}
          </section>

          <section className="run cell" aria-label="This edition">
            <div className="hd">
              <span className="caps">This edition</span>
              <span className="mono">what I read</span>
            </div>
            {steps.map((s, i) => (
              <div className="step" key={s.k}>
                <span>{s.k}</span>
                <span className="bar">
                  <i
                    style={{
                      width: `${(s.n / most) * 100}%`,
                      animationDelay: `${400 + i * 120}ms`,
                    }}
                    className={i === steps.length - 1 ? "on" : ""}
                  />
                </span>
                <b>{s.n}</b>
              </div>
            ))}
            {f && setAside > 0 && (
              <p className="aside">
                Set aside:{" "}
                {Object.entries(f.rejected)
                  .map(([k, n]) => `${n} ${k.replace(/_/g, " ")}`)
                  .join(", ")}
                .
              </p>
            )}
          </section>
        </div>
      </div>
    </Shell>
  );
}
