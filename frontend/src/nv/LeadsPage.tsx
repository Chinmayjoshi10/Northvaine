import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { BriefView, Row } from "../types";
import { link } from "../routes";
import { useLoad } from "../useLoad";
import { CaseSheet } from "./CaseSheet";
import { useDecisions } from "./decide";
import { LessonNote } from "./LessonNote";
import {
  clientLabel,
  decisionsOf,
  isHot,
  longDate,
  nice,
  roleOf,
  stageOf,
  stripCountry,
  typeOf,
  windowOf,
} from "./lead";
import { Shell } from "./Shell";
import "./leads.css";

const OPPORTUNITY_WORDS = [
  "Connected",
  "Approach now",
  "Build a relationship",
  "Looking for it",
  "Watch list",
];

// Leads: every lead in one list, each with its type; a lead opens as a sheet over the list.

export function LeadsPage({ client, day }: { client: string; day: string }) {
  const brief = useLoad(() => api.brief(client, day), [client, day]);
  const crumb = (
    <>
      Leads <span className="sl">/</span>{" "}
      <b>{brief.state === "ready" ? clientLabel(brief.data) : client}</b>
    </>
  );
  if (brief.state !== "ready")
    return (
      <Shell client={client} day={day} screen="leads" crumb={crumb}>
        <div className="nv-page">
          {brief.state === "loading" ? (
            <div className="wait" aria-busy="true" />
          ) : (
            <p className="alert">{brief.message}</p>
          )}
        </div>
      </Shell>
    );
  return <Leads client={client} day={day} brief={brief.data} crumb={crumb} />;
}

function Leads(props: {
  client: string;
  day: string;
  brief: BriefView;
  crumb: React.ReactNode;
}) {
  const { client, day, brief, crumb } = props;
  const rows = useMemo(
    () => [...brief.accounts, ...brief.tenders, ...brief.weaker],
    [brief],
  );
  const [filter, setFilter] = useState("All");
  const [current, setCurrent] = useState<number | null>(null);
  const { decided, decide, followed, follow, learning, lesson, dismiss } =
    useDecisions(client, brief);
  const sheetRef = useRef<HTMLDivElement>(null);

  // D125: when the rows carry an opportunity the filters are its labels, else the lead types
  const byOpportunity = rows.some((r) => r.opportunity);
  const kindOf = (r: Row) =>
    byOpportunity ? (r.opportunity?.word ?? "Other") : typeOf(r);
  const kinds = byOpportunity
    ? OPPORTUNITY_WORDS.filter((w) => rows.some((r) => kindOf(r) === w))
    : null;

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const r of rows) c[kindOf(r)] = (c[kindOf(r)] ?? 0) + 1;
    return c;
  }, [rows, byOpportunity]);
  const shown = rows.filter((r) => filter === "All" || kindOf(r) === filter);
  const open = current !== null && shown[current] ? shown[current] : null;

  const step = useCallback(
    (d: number) => {
      if (current === null) return;
      const n = current + d;
      if (n < 0 || n >= shown.length) return;
      const parts =
        sheetRef.current?.querySelectorAll<HTMLElement>("[data-content]") ?? [];
      parts.forEach((p) => p.classList.add(d > 0 ? "out-up" : "out-down"));
      window.setTimeout(() => {
        setCurrent(n);
        parts.forEach((p) => {
          p.classList.remove("out-up", "out-down");
          p.classList.add(d > 0 ? "out-down" : "out-up");
        });
        requestAnimationFrame(() =>
          requestAnimationFrame(() =>
            parts.forEach((p) => p.classList.remove("out-up", "out-down")),
          ),
        );
      }, 180);
      document
        .querySelector(`[data-row="${n}"]`)
        ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    },
    [current, shown.length],
  );

  useEffect(() => {
    if (open === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setCurrent(null);
      if (e.key === "ArrowDown") {
        e.preventDefault();
        step(1);
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        step(-1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, step]);

  const { weekday, date } = longDate(brief.as_of);
  const act = useMemo(() => decisionsOf(brief, rows).length, [brief, rows]);

  return (
    <Shell
      client={client}
      day={day}
      screen="leads"
      crumb={crumb}
      counts={{ leads: rows.length }}
      peek={open !== null}
      overlay={
        <>
          <div className="nv-scrim" onClick={() => setCurrent(null)} />
          <div ref={sheetRef}>
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
              onClose={() => setCurrent(null)}
            />
          </div>
          <LessonNote lesson={lesson} learning={learning} onClose={dismiss} />
        </>
      }
    >
      <div className="nv-page">
        <div className="ed">
          <span className="caps">{weekday} edition</span>
          <span className="rule" />
          <span className="mono">{date}</span>
        </div>
        <h1 className="hl lh">Leads</h1>
        <p className="lsub">
          {rows.length} leads, every fact checked against its source.{" "}
          {act > 0
            ? `${act} to decide.`
            : "Nothing needs a decision today."}
        </p>

        <div className="filters" role="group" aria-label="Lead type">
          {[
            ["All", rows.length] as const,
            ...(kinds
              ? kinds.map((k) => [k, counts[k] ?? 0] as const)
              : Object.entries(counts)),
          ].map(
            ([k, n]) => (
              <button
                key={k}
                type="button"
                className="chip"
                aria-pressed={filter === k}
                onClick={() => {
                  setFilter(k);
                  setCurrent(null);
                }}
              >
                {k === "All" || byOpportunity ? k : `${k}s`}
                <span className="mono">{n}</span>
              </button>
            ),
          )}
          <span className="right mono">ranked by evidence, then timing</span>
        </div>

        <div className="lhead" aria-hidden="true">
          <span>Chain</span>
          <span>Company</span>
          <span>Type</span>
          <span>What happened</span>
          <span>Window</span>
          <span>Stage</span>
        </div>
        {shown.length === 0 && (
          <p className="empty">No leads of this type in this run.</p>
        )}
        {shown.map((r, i) => (
          <button
            key={r.rank}
            type="button"
            data-row={i}
            className={`lrow${decided[r.rank] ? " done" : ""}`}
            aria-current={current === i ? "true" : undefined}
            style={{ animationDelay: `${Math.min(i, 14) * 28}ms` }}
            onClick={() => setCurrent(i)}
          >
            <span className="glyph" aria-label="How much of the chain is known">
              {(r.chain ?? []).map((l) => (
                <i
                  key={l.slot}
                  className={`m ${l.state === "stated" ? "s" : l.state === "inferred" ? "h" : "u"}`}
                />
              ))}
            </span>
            <span className="co">
              <b>{nice(r.company)}</b>
              <span>
                {r.country} · {roleOf(r)}
              </span>
            </span>
            <span className={`type ${typeOf(r).toLowerCase()}`}>
              {typeOf(r)}
            </span>
            <span className="what">{stripCountry(r.what)}</span>
            <span className={`win${isHot(r) ? " hot" : ""}`}>
              {windowOf(r)}
            </span>
            <span className={`stage${stageOf(r) === "Act now" ? " act" : ""}`}>
              {stageOf(r)}
            </span>
            <span className="noted" aria-hidden="true" />
          </button>
        ))}
      </div>
    </Shell>
  );
}
