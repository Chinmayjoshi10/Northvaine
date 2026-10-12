import { useMemo, useState } from "react";
import { api, safeHref } from "../api";
import { link } from "../routes";
import type { BriefView, Link, Row } from "../types";
import { useLoad } from "../useLoad";
import "../morning.css";

// The Morning: what the run did overnight, and the few situations that deserve attention.
// Every number is counted from the run record and every solid mark is a verified quote.

const ACT = new Set(["contact now", "bid now"]);
const SLOT_NAMES: Record<Link["slot"], string> = {
  authority: "Authority",
  project: "Project",
  contract: "Contract",
  contractor: "Contractor",
  buyer: "Buys what you sell",
};
const REASONS: Record<string, string> = {
  unidentified: "no identifiable organisation",
  not_a_buyer: "not a buyer",
  competitor: "a competitor",
  reseller: "sells what you sell",
  publisher: "a publisher, not a buyer",
};

function longDate(day: string): string {
  const d = new Date(`${day}T06:00:00Z`);
  return d.toLocaleDateString("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

function words(n: number): string {
  const small = [
    "no",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
  ];
  return n <= 10 ? small[n] : String(n);
}

function cap(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function domain(url: string | null): string {
  if (!url) return "";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

export function MorningPage({ client, day }: { client: string; day: string }) {
  const loaded = useLoad(() => api.brief(client, day), [client, day]);
  if (loaded.state === "loading")
    return <div className="mv mv-wait" aria-busy="true" />;
  if (loaded.state === "error")
    return (
      <div className="mv">
        <p className="mv-error" role="alert">
          {loaded.message}
        </p>
      </div>
    );
  return <Morning brief={loaded.data} day={day} />;
}

function Morning({ brief, day }: { brief: BriefView; day: string }) {
  const situations = useMemo(
    () => [...brief.accounts, ...brief.tenders],
    [brief],
  );
  const act = situations.filter((r) => ACT.has(r.status));
  const watch = situations.filter((r) => !ACT.has(r.status));
  const f = brief.funnel;
  const setAside = f ? Object.values(f.rejected).reduce((a, b) => a + b, 0) : 0;

  return (
    <div className="mv">
      <header className="mv-mast">
        <span className="mv-word">Northvaine</span>
        <span className="mv-mono">{longDate(brief.as_of)}</span>
        <span className="mv-mono mv-right">
          watching for <em>{brief.offer}</em>
        </span>
      </header>

      <section className="mv-lede" aria-label="Overnight summary">
        <p className="mv-voice mv-rise">
          While you were away I read <b>{f?.documents ?? "the"}</b> documents
          {f ? (
            <>
              . <b>{f.candidates}</b> named an organisation that might matter; I
              set <b>{setAside}</b> aside and investigated the rest.
            </>
          ) : (
            "."
          )}
        </p>
        <p className="mv-voice mv-rise mv-d1">
          {act.length > 0 ? (
            <>
              <span className="mv-signal">{cap(words(act.length))}</span>{" "}
              {act.length === 1 ? "needs" : "need"} you today.{" "}
            </>
          ) : (
            <>Nothing needs you today. </>
          )}
          {watch.length > 0 && <>I am following {words(watch.length)} more.</>}
        </p>
        {f && <Field funnel={f} act={act.length} watch={watch.length} />}
      </section>

      {act.length > 0 && (
        <Group
          title="Act"
          note="a commercial window is open"
          rows={act}
          day={day}
          brief={brief}
          signal
        />
      )}
      <Group
        title="Watching"
        note="developing; Northvaine is following"
        rows={watch}
        day={day}
        brief={brief}
      />

      <footer className="mv-foot mv-mono">
        <span>
          Solid: a verified quote. Hollow: inferred. Dashed: not yet known.
        </span>
        <span>A person decides and makes contact.</span>
      </footer>
    </div>
  );
}

/** One dot per organisation found; they settle into what became of them. */
function Field({
  funnel,
  act,
  watch,
}: {
  funnel: NonNullable<BriefView["funnel"]>;
  act: number;
  watch: number;
}) {
  const setAside = Object.entries(funnel.rejected);
  const followed = Math.max(0, funnel.briefed - act - watch);
  const cols: { label: string; n: number; kind: string; note?: string }[] = [
    ...setAside.map(([reason, n]) => ({
      label: "set aside",
      n,
      kind: "aside",
      note: REASONS[reason] ?? reason,
    })),
    { label: "below the line", n: followed, kind: "kept" },
    { label: "watching", n: watch, kind: "watch" },
    { label: "act", n: act, kind: "act" },
  ].filter((c) => c.n > 0);
  let i = 0;
  return (
    <div
      className="mv-field"
      role="img"
      aria-label={`${funnel.candidates} organisations found, ${act} to act on, ${watch} watched`}
    >
      {cols.map((c) => (
        <div key={c.label + c.kind} className={`mv-col mv-${c.kind}`}>
          <div
            className="mv-dots"
            style={{ gridTemplateColumns: `repeat(${Math.min(c.n, 10)}, 7px)` }}
          >
            {Array.from({ length: c.n }, () => (
              <i
                key={i}
                style={{
                  animationDelay: `${Math.min(1400, (i++ * 23) % 1400)}ms`,
                }}
              />
            ))}
          </div>
          <div className="mv-col-label mv-mono">
            <b>{c.n}</b> {c.label}
            {c.note && <span> · {c.note}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

const FULL = 3; // the Morning shows a handful; the rest stay one line each

function Group(props: {
  title: string;
  note: string;
  rows: Row[];
  day: string;
  brief: BriefView;
  signal?: boolean;
}) {
  const { title, note, rows, day, brief, signal } = props;
  const [more, setMore] = useState(false);
  if (rows.length === 0) return null;
  const href = (r: Row) => link("c", brief.client_id, day, "e", r.rank);
  const rest = rows.slice(FULL);
  return (
    <section
      className={`mv-group${signal ? " is-signal" : ""}`}
      aria-label={title}
    >
      <h2 className="mv-group-head">
        <span>{title}</span>
        <span className="mv-mono">{note}</span>
      </h2>
      <ol className="mv-list">
        {rows.slice(0, FULL).map((r) => (
          <Situation key={r.rank} row={r} href={href(r)} signal={signal} />
        ))}
      </ol>
      {rest.length > 0 && (
        <>
          <button
            className="mv-more mv-mono"
            onClick={() => setMore(!more)}
            aria-expanded={more}
          >
            {more ? "Fold" : `${rest.length} more I am following`}
          </button>
          {more && (
            <ol className="mv-compact">
              {rest.map((r) => (
                <li key={r.rank}>
                  <a href={href(r)}>
                    <Glyph chain={r.chain ?? []} />
                    <span className="mv-c-name">{r.company}</span>
                    <span className="mv-mono">
                      {r.country} · {r.contract_nature ?? r.stream} ·{" "}
                      {r.why_now}
                    </span>
                  </a>
                </li>
              ))}
            </ol>
          )}
        </>
      )}
    </section>
  );
}

/** The chain in five marks: how far a situation has resolved, at a glance. */
function Glyph({ chain }: { chain: Link[] }) {
  return (
    <span
      className="mv-glyph"
      aria-label={`${chain.filter((l) => l.state === "stated").length} of ${chain.length} steps stated`}
    >
      {chain.map((l) => (
        <i key={l.slot} className={`is-${l.state}`} />
      ))}
    </span>
  );
}

function Situation({
  row,
  href,
  signal,
}: {
  row: Row;
  href: string;
  signal?: boolean;
}) {
  const chain = row.chain ?? [];
  const [open, setOpen] = useState<number | null>(null);
  const known = chain.filter((l) => l.state === "stated").length;
  const picked = open === null ? null : chain[open];
  return (
    <li className="mv-sit">
      <div className="mv-sit-head">
        <span className={`mv-bracket${signal ? " is-signal" : ""}`}>
          <span className="mv-name">{row.company}</span>
        </span>
        <span className="mv-mono mv-meta">
          {row.country} · {row.contract_nature ?? row.stream} · {row.why_now}
        </span>
        <span className={`mv-status mv-mono${signal ? " is-signal" : ""}`}>
          {row.status}
        </span>
      </div>

      <div
        className="mv-chain"
        role="list"
        aria-label={`Commercial chain, ${known} of ${chain.length} steps stated`}
      >
        {chain.map((l, idx) => (
          <button
            key={l.slot}
            role="listitem"
            className={`mv-link is-${l.state}${open === idx ? " is-open" : ""}`}
            onClick={() => setOpen(open === idx ? null : idx)}
            disabled={!l.quote}
            aria-expanded={open === idx}
            title={
              l.quote
                ? "Show the source"
                : l.state === "unknown"
                  ? "Not yet known"
                  : undefined
            }
          >
            <span className="mv-node" aria-hidden />
            <span className="mv-slot mv-mono">{SLOT_NAMES[l.slot]}</span>
            <span className="mv-label">{l.label}</span>
          </button>
        ))}
        <span className="mv-link is-you" role="listitem">
          <span className="mv-node" aria-hidden />
          <span className="mv-slot mv-mono">You</span>
          <span className="mv-label">your offer</span>
        </span>
      </div>

      {picked?.quote && (
        <blockquote className="mv-quote">
          <p>“{picked.quote}”</p>
          <footer className="mv-mono">
            {picked.state === "inferred" ? "inferred from " : ""}
            {safeHref(picked.url ?? "") ? (
              <a
                href={safeHref(picked.url ?? "") ?? undefined}
                target="_blank"
                rel="noreferrer noopener"
              >
                {domain(picked.url)} ↗
              </a>
            ) : (
              domain(picked.url)
            )}
          </footer>
        </blockquote>
      )}

      <p className="mv-caution">
        {row.caution}. <a href={href}>Open the case →</a>
      </p>
    </li>
  );
}
