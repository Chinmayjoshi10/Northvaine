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
  daysLeft,
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
import { TerritoryMap } from "./TerritoryMap";
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

/** The client's name; else the offer cut at its first comma or 48 characters. Never the whole sentence. */
function clientLabel(b: BriefView): string {
  const name = b.client_name?.trim();
  if (name) return name;
  const first = b.offer.split(",")[0].trim();
  return first.length > 48
    ? `${first.slice(0, 48).replace(/\s+\S*$/, "")}…`
    : first;
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

const DAY = 86_400_000;

function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(b) - Date.parse(a.slice(0, 10))) / DAY);
}

/**
 * The decisions, most urgent first: anything marked act-now, then tenders closing within a
 * week, then awards from the last two weeks (the winner orders soon after), then tenders
 * closing within two, then leads still to qualify, by rank. One per project: co-winners of
 * one contract are one decision.
 */
function toDecide(rows: Row[], asOf: string): Row[] {
  const act = rows.filter((r) => stageOf(r) === "Act now");
  const closing = (lo: number, hi: number) =>
    rows
      .filter((r) => {
        const d = daysLeft(r);
        return d !== null && d >= lo && d <= hi;
      })
      .sort((a, b) => daysLeft(a)! - daysLeft(b)!);
  const awards = rows
    .filter((r) => {
      const d = awardDay(r);
      return d !== null && daysBetween(d, asOf) <= 14;
    })
    .sort((a, b) => awardDay(b)!.localeCompare(awardDay(a)!));
  const out: Row[] = [];
  const seen = new Set<string>();
  const qualify = rows.filter((r) => stageOf(r) === "Developing");
  for (const r of [
    ...act,
    ...closing(0, 7),
    ...awards,
    ...closing(8, 14),
    ...qualify,
  ]) {
    const key = projectOf(r);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(r);
  }
  return out.slice(0, 4);
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
    const picked = (brief.edition ?? [])
      .map((e) => rows.find((r) => r.rank === e.rank))
      .filter((r): r is Row => r !== undefined);
    return picked.length > 0 ? picked : toDecide(rows, brief.as_of);
  }, [rows, brief.edition, brief.as_of]);
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
      const p = by.get(r.country) ?? {
        country: r.country,
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
      // the label names the country's most urgent row: a decision first, else the best rank
      const better =
        hot.has(r.rank) !== hot.has(p.lead.rank)
          ? hot.has(r.rank)
          : r.rank < p.lead.rank;
      if (better) p.lead = r;
      by.set(r.country, p);
    }
    return [...by.values()].map(({ lead, ...p }) => {
      const fact = shortFact(lead);
      return {
        ...p,
        note: fact ? `${nice(lead.company)} · ${fact}` : nice(lead.company),
      };
    });
  }, [rows, decisions, brief.accounts]);
  const unplaced = rows.filter(
    (r) => !r.country || /not stated/.test(r.country),
  ).length;

  // the masthead: the newest award is the news; otherwise the most urgent decision
  const lead =
    [...rows]
      .filter((r) => awardDay(r))
      .sort((a, b) => awardDay(b)!.localeCompare(awardDay(a)!))[0] ??
    decisions[0];
  // the dek: the lead's own reason, then plain counts of the rest; zero counts are skipped
  const dek: ReactNode[] = [];
  const top = decisions[0];
  if (top?.label_reason) {
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
                  {title(lead)}
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
            </span>
          </div>
          <TerritoryMap places={places} />
          <div className="mapnote">
            <span>Placed by country, as each record states it</span>
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
            <p className="quiet">Nothing needs a decision in this edition.</p>
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
                  {urgency(r) && (
                    <span className={`wait${hot ? " hot" : ""}`}>
                      {urgency(r)}
                    </span>
                  )}
                </div>
                <h2 className="q">
                  <a href={link("app", client, day, "case", r.rank)}>
                    {question(r)}
                  </a>
                </h2>
                {((r.timing_signals ?? []).length >= 2 || r.label || r.back_in_motion) && (
                  <p className="edlabel">
                    {(r.timing_signals ?? []).length >= 2 && (
                      <span className="mono lab-chip">
                        {(r.timing_signals ?? []).length} SIGNALS
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
                    {r.label && r.label_reason && (
                      <span className="lab-why">{r.label_reason}</span>
                    )}
                  </p>
                )}
                <p className="why">
                  <b>{projectOf(r)}.</b>{" "}
                  {readable(r.caution) && sentence(r.caution)}
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
