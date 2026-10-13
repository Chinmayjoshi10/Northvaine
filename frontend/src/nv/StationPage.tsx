import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../api";
import type { BriefView, Row } from "../types";
import { useLoad } from "../useLoad";
import { link } from "../routes";
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
      <b>{brief.state === "ready" ? brief.data.offer : client}</b>
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
  for (const r of [...act, ...closing(0, 7), ...awards, ...closing(8, 14), ...qualify]) {
    const key = projectOf(r);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(r);
  }
  return out.slice(0, 4);
}

/** The dateline's place: the authority when the record states it, else the company. */
function where(r: Row): string {
  const auth = r.chain?.find((l) => l.slot === "authority" && l.state !== "unknown");
  return auth ? auth.label : r.company;
}

function question(r: Row): string {
  if (r.stream === "tender" && r.account_role === "direct_purchaser")
    return "Bid on this tender?";
  if (r.stream === "tender") return "Approach the likely bidders before the award?";
  return `Take ${nice(r.company)}?`;
}

function sentence(s: string): string {
  const t = s.trim();
  return t ? t.charAt(0).toUpperCase() + t.slice(1).replace(/[.;]?$/, ".") : "";
}

const VERB: Record<string, string> = {
  tender_published: "opened a tender",
  contract_awarded: "won a contract",
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
  const decisions = useMemo(() => toDecide(rows, brief.as_of), [rows, brief.as_of]);
  const { decided, decide, followed, follow, learning, lesson, dismiss } =
    useDecisions(client, brief);
  const [open, setOpen] = useState<Row | null>(null);
  const [fresh, setFresh] = useState<number | null>(null);

  // "new": not in the edition before this one, matched by company identity
  useEffect(() => {
    let live = true;
    api.clients().then(
      async (all) => {
        const runs = all.find((c) => c.client_id === client)?.runs ?? [];
        const prev = runs.filter((d) => d < brief.as_of).sort().pop();
        if (!prev) return;
        const before = await api.brief(client, prev);
        const keys = new Set(
          [...before.accounts, ...before.tenders, ...before.weaker].map(
            (r) => r.company_key ?? r.company,
          ),
        );
        if (live)
          setFresh(rows.filter((r) => !keys.has(r.company_key ?? r.company)).length);
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [client, brief.as_of, rows]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const places = useMemo(() => {
    const hot = new Set(decisions.map((r) => r.rank));
    const by = new Map<string, Place>();
    for (const r of rows) {
      if (!r.country || /not stated/.test(r.country)) continue;
      const p = by.get(r.country) ?? { country: r.country, total: 0, toDecide: 0 };
      p.total += 1;
      if (hot.has(r.rank)) p.toDecide += 1;
      by.set(r.country, p);
    }
    return [...by.values()];
  }, [rows, decisions]);
  const unplaced = rows.filter((r) => !r.country || /not stated/.test(r.country)).length;

  // the masthead: the newest award is the news; otherwise the most urgent decision
  const lead =
    [...rows]
      .filter((r) => awardDay(r))
      .sort((a, b) => awardDay(b)!.localeCompare(awardDay(a)!))[0] ?? decisions[0];
  const soonest = rows
    .filter((r) => daysLeft(r) !== null)
    .sort((a, b) => daysLeft(a)! - daysLeft(b)!)[0];
  const weekAwards = rows.filter((r) => {
    const d = awardDay(r);
    return d !== null && daysBetween(d, brief.as_of) <= 7;
  }).length;
  const lede: ReactNode[] = [];
  if (soonest) {
    const d = daysLeft(soonest)!;
    lede.push(
      <span key="t">
        <b>{nice(soonest.company)}</b>’s tender closes{" "}
        {d === 0 ? "today" : d === 1 ? "tomorrow" : `in ${d} days`}.{" "}
      </span>,
    );
  }
  if (weekAwards)
    lede.push(
      <span key="a">
        {weekAwards === 1 ? "One contract was" : `${weekAwards} contracts were`} awarded
        this week.{" "}
      </span>,
    );
  lede.push(<span key="r">Every fact below is checked against its source.</span>);

  const feed = useMemo(() => {
    const byRank = new Map(rows.map((r) => [r.rank, r]));
    const seen = new Set<string>();
    return (brief.log ?? [])
      .filter((l) => l.kind !== "set_aside" && l.rank !== null && byRank.has(l.rank))
      .filter((l) => {
        const k = `${l.rank}:${l.kind}`;
        if (seen.has(k)) return false;
        seen.add(k);
        return true;
      })
      .slice(0, 6)
      .map((l) => ({ l, r: byRank.get(l.rank!)! }));
  }, [brief.log, rows]);

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
      counts={{ leads: rows.length }}
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
                <button type="button" className="hlink" onClick={() => setOpen(lead)}>
                  {title(lead)}
                </button>
              ) : (
                "A quiet edition"
              )}
            </h1>
            <p className="lede">{lede}</p>
          </div>
          <div className="stats">
            <div className="stat sig">
              <b>{decisions.length}</b>
              <span className="caps">to decide</span>
            </div>
            {fresh !== null && (
              <div className="stat">
                <b>{fresh}</b>
                <span className="caps">new</span>
              </div>
            )}
            <a className="stat" href={link("app", client, day, "leads")}>
              <b>{rows.length}</b>
              <span className="caps">on record</span>
            </a>
          </div>
        </header>

        <section className="map" aria-label="Territory">
          <div className="hd">
            <span className="caps">Territory</span>
            <span className="legend mono">
              <span>
                <i className="m y" />
                to decide
              </span>
              <span>
                <i className="m h" />
                on record
              </span>
            </span>
          </div>
          <TerritoryMap places={places} />
          <div className="mapnote">
            <span>Placed by country, as each record states it</span>
            {unplaced > 0 && (
              <span>
                {unplaced} {unplaced === 1 ? "lead states" : "leads state"} no country
              </span>
            )}
          </div>
        </section>

        <section className="dec" aria-label="To decide">
          <div className="hd">
            <span className="caps">To decide · most urgent first</span>
            <span className="mono">{decisions.length}</span>
          </div>
          {decisions.length === 0 && (
            <p className="quiet">Nothing needs a decision in this edition.</p>
          )}
          {decisions.map((r, i) => {
            const d = daysLeft(r);
            const hot = stageOf(r) === "Act now" || (d !== null && d <= 7) || !!awardDay(r);
            // the chain's steps are a procurement record's; other leads do not have them
            const missing =
              r.stream === "tender" || r.stream === "award" ? unknownSteps(r) : [];
            const done = decided[r.rank];
            return (
              <article
                className="d"
                key={r.rank}
                style={{ animationDelay: `${120 + i * 70}ms` }}
              >
                <div className="meta">
                  <span className="dateline">
                    <b>{nice(where(r))}</b>{" "}
                    · {r.contract_nature ? `${r.contract_nature} ` : ""}
                    {typeOf(r).toLowerCase()}
                  </span>
                  <span className={`wait${hot ? " hot" : ""}`}>{windowOf(r)}</span>
                </div>
                <h2 className="q">
                  <button type="button" onClick={() => setOpen(r)}>
                    {question(r)}
                  </button>
                </h2>
                <p className="why">
                  <b>{projectOf(r)}.</b> {sentence(r.caution)}
                  {missing.length > 0 && ` Not yet known: ${missing.join(", ")}.`}
                </p>
                {done ? (
                  <div className="opts">
                    <span className="did mono">✓ {done}</span>
                    <button type="button" className="btn" onClick={() => setOpen(r)}>
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
        <section className="feed cell" aria-label="Latest developments">
          <div className="hd">
            <span className="caps">Latest on record</span>
            <span className="mono">newest first</span>
          </div>
          {feed.length === 0 && <p className="quiet">No dated developments in this run.</p>}
          {feed.map(({ l, r }) => (
            <button type="button" className="e" key={`${l.rank}:${l.kind}`} onClick={() => setOpen(r)}>
              <span className="mono">{l.at ? shortDate(l.at) : "—"}</span>
              <i
                className={`m ${decisions.includes(r) ? "y" : r.stream === "award" ? "s" : "h"}`}
              />
              <span className="t">
                {nice(l.company ?? r.company)} {VERB[l.kind] ?? l.kind.replace(/_/g, " ")}
                <em> · {projectOf(r)}</em>
              </span>
            </button>
          ))}
        </section>

        <section className="taught cell" aria-label="What your answers changed">
          <div className="hd">
            <span className="caps">What your answers changed</span>
            {learning && <span className="mono">{learning.answers} answers</span>}
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
