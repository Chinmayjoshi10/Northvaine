import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api, safeHref } from "../api";
import type { Bidder, BriefView, Dossier, Row } from "../types";
import { useLoad } from "../useLoad";
import { link } from "../routes";
import { optionsFor } from "./CaseSheet";
import { useDecisions } from "./decide";
import { LessonNote } from "./LessonNote";
import {
  SLOT,
  domain,
  nice,
  projectOf,
  shortDate,
  toDecide,
  typeOf,
  windowOf,
} from "./lead";
import { Shell } from "./Shell";
import "./station.css"; // shared motion keyframes
import "./connections.css";

// Connections: one lead's chain, drawn from the authority to you. Every line is a record or
// is marked as inferred; the node nobody knows yet is drawn as unknown, never filled in.

export function ConnectionsPage(props: { client: string; day: string; rank?: number }) {
  const { client, day } = props;
  const brief = useLoad(() => api.brief(client, day), [client, day]);
  const rows = useMemo(
    () =>
      brief.state === "ready"
        ? [...brief.data.accounts, ...brief.data.tenders, ...brief.data.weaker]
        : [],
    [brief],
  );
  // This view draws public-contract chains (authority, project, contractor). Import and news
  // leads have a different chain, shown on their case page, so they are not drawn here.
  const contracts = rows.filter(isContract);
  const rank =
    props.rank ??
    (brief.state === "ready"
      ? (toDecide(contracts, brief.data.as_of)[0] ?? contracts[0])?.rank
      : undefined);
  const row = rows.find((r) => r.rank === rank) ?? null;
  const crumb = (
    <>
      Connections <span className="sl">/</span>{" "}
      <b>{row ? `${nice(row.company)} · ${projectOf(row)}` : client}</b>
    </>
  );
  if (brief.state === "ready" && row && !isContract(row))
    return (
      <Shell client={client} day={day} screen="connections" crumb={crumb}>
        <div className="nv-page">
          <p className="alert">
            Connections draws public contracts: who runs the project, who won it, and who orders.
            This lead comes from {row.stream === "trade" ? "import records" : "the news"}, so its
            chain is on <a href={link("app", client, day, "case", row.rank)}>its case page</a>.
          </p>
        </div>
      </Shell>
    );
  if (brief.state !== "ready" || !row)
    return (
      <Shell client={client} day={day} screen="connections" crumb={crumb}>
        <div className="nv-page">
          {brief.state === "loading" ? (
            <div className="wait" aria-busy="true" />
          ) : brief.state === "error" ? (
            <p className="alert">{brief.message}</p>
          ) : (
            <p className="alert">
              No public contract to connect in this edition. Import and news leads show their
              chain on their case page.
            </p>
          )}
        </div>
      </Shell>
    );
  return (
    <Connections
      key={row.rank}
      client={client}
      day={day}
      brief={brief.data}
      row={row}
      crumb={crumb}
    />
  );
}

function isContract(r: Row): boolean {
  return r.stream === "tender" || r.stream === "award";
}

/** A node on the right of the contract: the contractor on record, or a likely winner. */
interface Party {
  name: string;
  stated: boolean;
  bidder: Bidder | null;
}

type Pick = { kind: "authority" } | { kind: "project" } | { kind: "party"; i: number } | { kind: "buyer" };

function confidence(b: Bidder): number {
  return b.wins / (b.wins + 1);
}

function Connections(props: {
  client: string;
  day: string;
  brief: BriefView;
  row: Row;
  crumb: ReactNode;
}) {
  const { client, day, brief, row, crumb } = props;
  const dossier = useLoad(() => api.entry(client, day, row.rank), [client, day, row.rank]);
  const d: Dossier | null = dossier.state === "ready" ? dossier.data : null;
  const { decided, decide, learning, lesson, dismiss } = useDecisions(client, brief);
  const [pick, setPick] = useState<Pick>({ kind: "party", i: 0 });

  const chain = row.chain ?? [];
  const at = (slot: string) => chain.find((l) => l.slot === slot);
  const authority = at("authority");
  const project = at("project");
  const contractor = at("contractor");
  const buyer = at("buyer");

  const parties: Party[] = useMemo(() => {
    if (row.stream === "tender" && d?.likely_bidders.length)
      return [...d.likely_bidders]
        .sort((a, b) => b.wins - a.wins)
        .slice(0, 5)
        .map((b) => ({ name: b.name, stated: false, bidder: b }));
    if (contractor && contractor.state === "stated")
      return [{ name: contractor.label, stated: true, bidder: null }];
    return [];
  }, [row, d, contractor]);

  const direct = row.stream === "tender" && row.account_role === "direct_purchaser";
  const proj = projectOf(row);
  const short = proj.length > 44 ? `${proj.slice(0, 44).replace(/\s+\S*$/, "")}…` : proj;
  const title = direct
    ? `${nice(row.company)} buys directly: ${short}`
    : row.stream === "tender"
      ? `Who will order the materials for ${short}?`
      : `Will ${nice(row.company)} buy from you?`;
  const twice = parties.filter((p) => (p.bidder?.wins ?? 0) > 1).length;
  const lede = direct
    ? "The authority buys the goods itself. A bid before the deadline is the way in."
    : row.stream === "tender"
      ? parties.length
        ? `The authority runs the tender, but the winning contractor orders the materials. ${parties.length} ${parties.length === 1 ? "firm has" : "firms have"} won similar work on record${twice ? `; ${twice === 1 ? "one has" : `${twice} have`} won more than once` : ""}.`
        : "The authority runs the tender; the winner is not known until the award."
      : `${nice(row.company)} won the contract.${buyer?.state !== "stated" ? " Who orders the materials is not yet known." : ""}`;

  const timeline = useMemo(() => {
    const out: { label: string; day: string; kind: "s" | "f" }[] = [];
    let first = true;
    for (const w of d?.when ?? []) {
      const ev = w.match(/^Event date: (\d{4}-\d{2}-\d{2})/);
      if (ev) {
        out.push({ label: first ? (row.stream === "award" ? "Awarded" : "Published") : "Updated", day: ev[1], kind: "s" });
        first = false;
      }
      const win = w.match(/to (\d{4}-\d{2}-\d{2})/);
      if (win && row.stream === "tender") out.push({ label: "Closes", day: win[1], kind: "f" });
    }
    return out.sort((a, b) => a.day.localeCompare(b.day));
  }, [d, row.stream]);

  // Geometry: columns across the stage, likely winners spread down it.
  const stage = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(900);
  useEffect(() => {
    const el = stage.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(560, e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const H = 460;
  const x = { auth: 8, proj: W * 0.2, party: W * 0.44, buyer: W * 0.86, you: W - 14 };
  const mid = H / 2;
  const ys =
    parties.length <= 1
      ? [mid]
      : parties.map((_, i) => 40 + (i * (H - 80)) / (parties.length - 1));
  const curve = (x1: number, y1: number, x2: number, y2: number) => {
    const c = (x2 - x1) * 0.55;
    return `M${x1},${y1} C${x1 + c},${y1} ${x2 - c},${y2} ${x2},${y2}`;
  };
  const line = (state: string | undefined) =>
    state === "stated" ? "ln s" : state === "inferred" ? "ln h" : "ln u";

  const sel: Pick = pick.kind === "party" && !parties[pick.i] ? { kind: "authority" } : pick;
  const selected = (p: Pick) => JSON.stringify(p) === JSON.stringify(sel);
  const done = decided[row.rank];

  return (
    <Shell
      client={client}
      day={day}
      screen="connections"
      crumb={crumb}
      overlay={<LessonNote lesson={lesson} learning={learning} onClose={dismiss} />}
    >
      <div className="cx">
        <section className="stagearea">
          <span className="dateline">
            <b>{nice(authority && authority.state !== "unknown" ? authority.label : row.company)}</b>{" "}
            · {row.contract_nature ? `${row.contract_nature} ` : ""}
            {typeOf(row).toLowerCase()} · {windowOf(row)}
          </span>
          <h1 className="hl">{title}</h1>
          <p className="lede">{lede}</p>

          <div className="cxstage" ref={stage}>
            <div className="cols" aria-hidden="true">
              <span style={{ left: x.auth }}>Authority</span>
              <span style={{ left: x.proj }}>Project</span>
              <span style={{ left: x.party }}>
                {row.stream === "tender" ? "Likely winners · inferred" : "Contractor"}
              </span>
              <span style={{ left: x.buyer - 30 }}>Buys what you sell</span>
            </div>
            <svg width={W} height={H} className="g" role="img" aria-label="How this lead connects to you">
              <g className="lines">
                <path className={line(project?.state)} d={`M${x.auth},${mid} L${x.proj},${mid}`} />
                {parties.map((p, i) => (
                  <path
                    key={`a${i}`}
                    className={`${p.stated ? "ln s" : "ln h"}${selected({ kind: "party", i }) ? " on" : ""}`}
                    d={curve(x.proj, mid, x.party, ys[i])}
                    style={{ animationDelay: `${500 + i * 120}ms` }}
                  />
                ))}
                {parties.map((_, i) => (
                  <path
                    key={`b${i}`}
                    className="ln u faint"
                    d={curve(x.party + 260, ys[i], x.buyer, mid)}
                    style={{ animationDelay: `${1100 + i * 80}ms` }}
                  />
                ))}
                {parties.length === 0 && (
                  <path className="ln u faint" d={`M${x.proj},${mid} L${x.buyer},${mid}`} />
                )}
                <path className="ln you" d={`M${x.buyer + 8},${mid} L${x.you},${mid}`} />
              </g>

              <Node x={x.auth} y={mid} kind={authority?.state} on={selected({ kind: "authority" })} onClick={() => setPick({ kind: "authority" })} delay={0}>
                <text className="ser" x={0} y={30}>{clip(nice(authority?.label ?? row.company), Math.floor((x.proj - x.auth - 18) / 8.5))}</text>
                <text className="sub" x={0} y={46}>authority · {authority?.state === "stated" ? "on record" : "inferred"}</text>
              </Node>
              <Node x={x.proj} y={mid} kind={project?.state} on={selected({ kind: "project" })} onClick={() => setPick({ kind: "project" })} delay={250}>
                <text className="ser" x={0} y={30}>{clip(proj, Math.floor((x.party - x.proj - 30) / 8.5))}</text>
                <text className="sub" x={0} y={46}>{row.contract_nature ?? "contract"} · {row.stream === "tender" ? "tender open" : "awarded"}</text>
              </Node>
              {parties.map((p, i) => (
                <Node key={p.name} x={x.party} y={ys[i]} kind={p.stated ? "stated" : "inferred"} on={selected({ kind: "party", i })} onClick={() => setPick({ kind: "party", i })} delay={700 + i * 120} label>
                  {p.bidder && (
                    <text className="conf" x={-12} y={-12} textAnchor="end">
                      {confidence(p.bidder).toFixed(2)}
                    </text>
                  )}
                  <text x={16} y={4}>{clip(nice(p.name), 34)}</text>
                  <text className="sub" x={16} y={20}>
                    {p.bidder
                      ? `${p.bidder.wins} similar ${p.bidder.wins === 1 ? "win" : "wins"}${p.bidder.last_won ? ` · last ${shortDate(p.bidder.last_won)}` : ""}`
                      : "won the contract · on record"}
                  </text>
                </Node>
              ))}
              <Node x={x.buyer} y={mid} kind={buyer?.state} on={selected({ kind: "buyer" })} onClick={() => setPick({ kind: "buyer" })} delay={1300}>
                <text className="it" x={0} y={34}>
                  {buyer?.state === "unknown" ? (row.stream === "tender" ? "unknown until" : "not yet") : "inferred:"}
                </text>
                <text className="it" x={0} y={52}>
                  {buyer?.state === "unknown" ? (row.stream === "tender" ? "the award" : "known") : "needs what you sell"}
                </text>
              </Node>
              <g className="you" transform={`translate(${x.you},${mid})`}>
                <circle className="wash" r={13} />
                <circle className="core" r={6.5} />
                <text x={0} y={-22} textAnchor="middle">YOU</text>
              </g>
            </svg>
          </div>

          {timeline.length > 0 && (
            <div className="time">
              <span className="caps">How it unfolds</span>
              <Timeline items={timeline} today={brief.as_of} award={row.stream === "tender"} />
            </div>
          )}
        </section>

        <aside className="side">
          <Detail pick={sel} row={row} parties={parties} />
          <div className="acts">
            {done ? (
              <span className="did mono">✓ {done}</span>
            ) : (
              optionsFor(row).map((o, j) =>
                o.kind === "drop" ? (
                  <a key={o.kind} className="btn" href={link("app", client, day, "leads")}>
                    {o.label}…
                  </a>
                ) : (
                  <button
                    key={o.kind}
                    type="button"
                    className={`btn${j === 0 ? " rec" : ""}`}
                    onClick={() => decide(row, { kind: o.kind as "take" | "later", label: o.label })}
                  >
                    {o.label}
                  </button>
                ),
              )
            )}
          </div>
        </aside>
      </div>
    </Shell>
  );
}

function clip(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`;
}

function Node(props: {
  x: number;
  y: number;
  kind: string | undefined;
  on: boolean;
  onClick: () => void;
  delay: number;
  label?: boolean;
  children: ReactNode;
}) {
  const { x, y, kind, on, onClick, delay, label, children } = props;
  return (
    <g
      className={`nd ${kind === "stated" ? "s" : kind === "inferred" ? "h" : "u"}${on ? " on" : ""}`}
      transform={`translate(${x},${y})`}
      style={{ animationDelay: `${delay}ms` }}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onClick()}
    >
      {on && label && <rect className="sel" x={-14} y={-18} width={300} height={46} rx={3} />}
      <rect className="sq" x={-6} y={-6} width={12} height={12} />
      {kind === "stated" && <rect className="dot" x={-2.5} y={-2.5} width={5} height={5} />}
      {children}
    </g>
  );
}

function Timeline(props: {
  items: { label: string; day: string; kind: "s" | "f" }[];
  today: string;
  award: boolean;
}) {
  const { items, today, award } = props;
  const days = [...items.map((i) => i.day), today];
  const t0 = Date.parse(days.reduce((a, b) => (a < b ? a : b)));
  const t1 = Date.parse(days.reduce((a, b) => (a > b ? a : b)));
  const span = Math.max(1, t1 - t0);
  // the right fifth is kept for what comes after the last date on record
  const pos = (d: string) => `${4 + ((Date.parse(d) - t0) / span) * (award ? 74 : 92)}%`;
  return (
    <div className="tl">
      <div className="track">
        {items.map((i) => (
          <i key={i.label + i.day} className={`tick ${i.kind}`} style={{ left: pos(i.day) }} />
        ))}
        <i className="tick now" style={{ left: pos(today) }} />
        {award && <i className="tick f" style={{ left: "96%" }} />}
      </div>
      <div className="labels">
        {items.map((i) => (
          <span key={i.label + i.day} style={{ left: pos(i.day) }}>
            <b>{i.label}</b>
            {shortDate(i.day)}
          </span>
        ))}
        <span className="now" style={{ left: pos(today) }}>
          <b>This edition</b>
          {shortDate(today)}
        </span>
        {award && (
          <span style={{ left: "96%" }}>
            <b>Award</b>after closing
          </span>
        )}
      </div>
    </div>
  );
}

function Detail(props: { pick: Pick; row: Row; parties: Party[] }) {
  const { pick, row, parties } = props;
  const chain = row.chain ?? [];
  const slotOf = (s: string) => chain.find((l) => l.slot === s);
  if (pick.kind === "party" && parties[pick.i]) {
    const p = parties[pick.i];
    const b = p.bidder;
    const href = b ? safeHref(b.source_url) : null;
    const stated = slotOf("contractor");
    return (
      <>
        <span className="caps">Selected · {p.stated ? "contractor on record" : "likely winner"}</span>
        <h2>{nice(p.name)}</h2>
        <div className="role">
          {p.stated ? "Won this contract" : "Has won similar work"}
          {b?.country ? ` · ${b.country}` : ""}
        </div>
        <blockquote className="pull">
          {b ? b.quote : stated?.quote}
          <cite>
            {b ? "award notice" : "this notice"} ·{" "}
            {href ? (
              <a href={href} target="_blank" rel="noreferrer noopener">
                {domain(b!.source_url)} ↗
              </a>
            ) : (
              domain(stated?.url ?? null)
            )}
            {b?.last_won ? ` · ${shortDate(b.last_won)}` : ""}
          </cite>
        </blockquote>
        {b && (
          <div className="kv">
            <span className="caps">Similar wins</span>
            <span>{b.wins} on record</span>
            <span className="caps">Last won</span>
            <span>{b.last_won ? shortDate(b.last_won) : "date not stated"}</span>
            <span className="caps">Confidence</span>
            <span>
              {confidence(b).toFixed(2)} <span className="mono">wins ÷ (wins + 1)</span>
            </span>
          </div>
        )}
        <p className="infer">
          {p.stated
            ? "Contractors order the materials for the works they win. Whether this one buys what you sell is not yet on record."
            : "If they win, they will order the materials. Reaching them before the award puts you on their supplier list when it matters."}{" "}
          <span className="tag">inferred</span>
        </p>
      </>
    );
  }
  const l = slotOf(pick.kind === "party" ? "authority" : pick.kind);
  const href = l?.url ? safeHref(l.url) : null;
  return (
    <>
      <span className="caps">Selected · {l ? SLOT[l.slot].toLowerCase() : pick.kind}</span>
      <h2>{l ? nice(l.label) : "Not on record"}</h2>
      <div className="role">
        {l?.state === "stated" ? "On record" : l?.state === "inferred" ? "Inferred" : "Not yet known"}
      </div>
      {l?.quote ? (
        <blockquote className="pull">
          {l.quote}
          <cite>
            {href ? (
              <a href={href} target="_blank" rel="noreferrer noopener">
                {domain(l.url)} ↗
              </a>
            ) : (
              domain(l.url)
            )}
          </cite>
        </blockquote>
      ) : (
        <p className="infer">Nothing on record says this yet. It is drawn as unknown, not guessed.</p>
      )}
    </>
  );
}
