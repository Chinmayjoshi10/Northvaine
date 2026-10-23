import { useEffect, useState } from "react";
import { safeHref } from "../api";
import { FAILURE_CHIPS, OUTCOMES } from "../types";
import type { Dot, Link, Row } from "../types";
import { HAPPENED, WRONG } from "./decide";
import type { FollowUp } from "./decide";
import {
  DOT_KIND,
  SLOT,
  domain,
  headline,
  nice,
  shortDate,
  stageOf,
  stripCountry,
  typeOf,
} from "./lead";

// One lead, opened as a sheet over the list. The decision is the feedback: one tap, saved.

export type Decision =
  | { kind: "take"; label: string }
  | { kind: "later"; label: string }
  | { kind: "drop"; label: string; reason: string };

export function optionsFor(
  r: Row,
): { kind: "take" | "later" | "drop"; label: string }[] {
  if (r.stream === "tender" && r.account_role === "direct_purchaser")
    return [
      { kind: "take", label: "Bid on it" },
      { kind: "later", label: "Not now" },
      { kind: "drop", label: "Not for us" },
    ];
  if (r.stream === "tender")
    return [
      { kind: "take", label: "Pursue it" },
      { kind: "later", label: "Wait for the award" },
      { kind: "drop", label: "Not for us" },
    ];
  if (r.stream === "trade")
    return [
      { kind: "take", label: "Approach them" },
      { kind: "later", label: "Not now" },
      { kind: "drop", label: "Not a buyer" },
    ];
  return [
    { kind: "take", label: "I’ll take it" },
    { kind: "later", label: "Not now" },
    { kind: "drop", label: "Not for us" },
  ];
}

/** The date and the source of one dot, the source linked when it has a page. */
export function DotSource({ dot }: { dot: Dot }) {
  const href = dot.url ? safeHref(dot.url) : null;
  return (
    <span className="mono dot-src">
      {dot.date ? `${shortDate(dot.date)} · ` : ""}
      {href ? (
        <a href={href} target="_blank" rel="noreferrer noopener">
          {dot.source ?? domain(dot.url)} ↗
        </a>
      ) : (
        (dot.source ?? "")
      )}
    </span>
  );
}

function notSaved(e: unknown): string {
  return e instanceof Error ? `Not saved: ${e.message} Try again.` : "Not saved. Try again.";
}

/** The decision and its follow-ups, shared by the sheet and the full case page. */
export function DecisionBox(props: {
  row: Row;
  question: string;
  decided: string | null;
  onDecide: (d: Decision) => Promise<void>;
  followed?: string[];
  onFollow?: (f: FollowUp) => Promise<void>;
}) {
  const { row, question, decided, onDecide, followed = [], onFollow } = props;
  const [askWhy, setAskWhy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setAskWhy(false);
    setError(null);
  }, [row.rank]);

  const save = async (act: () => Promise<void>) => {
    setSaving(true);
    setError(null);
    try {
      await act();
      setAskWhy(false);
    } catch (e) {
      setError(notSaved(e));
    } finally {
      setSaving(false);
    }
  };
  const decide = (d: Decision) => save(() => onDecide(d));
  const follow = (f: FollowUp) => (onFollow ? save(() => onFollow(f)) : undefined);
  const took = decided !== null && optionsFor(row)[0].label === decided;
  const happened = followed
    .filter((n) => n.startsWith(HAPPENED))
    .map((n) => n.slice(HAPPENED.length))
    .pop();

  return (
    <div className="sec">
      <span className="caps">Your decision</span>
      <p className="ask2">{question}</p>
      <div className="opts">
        {optionsFor(row).map((o, i) => (
          <button
            key={o.kind}
            type="button"
            className={`btn${(decided ? decided === o.label : i === 0) ? " rec" : ""}`}
            disabled={saving}
            onClick={() =>
              o.kind === "drop"
                ? setAskWhy(true)
                : decide({ kind: o.kind, label: o.label })
            }
          >
            {o.label}
          </button>
        ))}
      </div>
      {askWhy && (
        <div className="why">
          <span className="caps">Why not?</span>
          <div className="opts">
            {FAILURE_CHIPS.map((c) => (
              <button
                key={c}
                type="button"
                className="btn"
                disabled={saving}
                onClick={() =>
                  decide({ kind: "drop", label: "Not for us", reason: c })
                }
              >
                {c}
              </button>
            ))}
          </div>
        </div>
      )}
      {decided && !askWhy && !took && <div className="thanks">Noted.</div>}
      {took && onFollow && (
        <div className="why">
          <span className="caps">What happened?</span>
          <div className="opts">
            {OUTCOMES.map((o) => (
              <button
                key={o}
                type="button"
                className={`btn${happened === o ? " rec" : ""}`}
                disabled={saving}
                onClick={() => follow({ kind: "outcome", outcome: o })}
              >
                {o === "none" ? "no reply yet" : o}
              </button>
            ))}
          </div>
        </div>
      )}
      {error && (
        <div className="err" role="alert">
          {error}
        </div>
      )}
      <div className="fine">
        Your answer teaches Northvaine. Nothing is ever sent for you.
      </div>
    </div>
  );
}

export function CaseSheet(props: {
  row: Row | null;
  decided: string | null;
  onDecide: (d: Decision) => Promise<void>;
  /** Notes of the follow-ups already given ("What happened: …", "Wrong fact: …"). */
  followed?: string[];
  onFollow?: (f: FollowUp) => Promise<void>;
  /** The full case page for this lead, when the caller has a route for it. */
  fullHref?: string;
  /** This lead's chain on the Connections screen. */
  connectionsHref?: string;
  onClose: () => void;
}) {
  const { row, decided, onDecide, followed = [], onFollow, fullHref, connectionsHref, onClose } =
    props;
  const [picked, setPicked] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setPicked(null);
    setError(null);
  }, [row?.rank]);

  if (!row) return <div className="nv-sheet" aria-hidden="true" />;
  const chain = row.chain ?? [];
  const firstQuote = chain.findIndex((l) => l.state === "stated" && l.quote);
  const shown: Link | undefined = chain[picked ?? firstQuote];
  const by = (state: Link["state"]) => chain.filter((l) => l.state === state);
  const inferNote =
    row.stream === "award"
      ? "The works will need materials, and the contractor will be the one ordering them."
      : row.stream === "tender" && row.account_role !== "direct_purchaser"
        ? "The buyer of your product will be the contractor who wins this tender."
        : row.stream === "trade"
          ? "Official import records show it buys goods under your product codes. They do not show its suppliers, or whether it would take a new one."
          : null;

  const save = async (act: () => Promise<void>) => {
    setSaving(true);
    setError(null);
    try {
      await act();
    } catch (e) {
      setError(notSaved(e));
    } finally {
      setSaving(false);
    }
  };
  const follow = (f: FollowUp) => (onFollow ? save(() => onFollow(f)) : undefined);
  const flagged = (slot: Link["slot"]) => followed.includes(`${WRONG}${SLOT[slot]}`);

  return (
    <div
      className="nv-sheet"
      role="dialog"
      aria-modal="true"
      aria-label={nice(row.company)}
    >
      <div className="sbar">
        <span className="dateline">
          <b>{row.country}</b> · {typeOf(row).toLowerCase()} · {row.why_now}
        </span>
        {fullHref && (
          <a className="full" href={fullHref}>
            Open full case →
          </a>
        )}
        {connectionsHref && (
          <a className="full" href={connectionsHref}>
            See how it connects →
          </a>
        )}
        <span className="keys mono">
          <span>
            <kbd>↑</kbd>
            <kbd>↓</kbd>next lead
          </span>
          <span>
            <kbd>esc</kbd>close
          </span>
        </span>
        <button
          className="x"
          type="button"
          onClick={onClose}
          aria-label="Close"
        >
          ✕
        </button>
      </div>

      <div className="sart">
        <div className="content" data-content>
          <span className="dateline">
            <b>{row.country}</b> · {row.contract_nature ?? ""}{" "}
            {typeOf(row).toLowerCase()} · {stageOf(row)}
          </span>
          <h1 className="hl">{headline(row)}</h1>
          {row.opportunity && (
            <p className="mono opp-tag">
              {row.opportunity.word} · {row.opportunity.words}
            </p>
          )}
          {row.opportunity?.why_now && (
            <p className="opp-why">{row.opportunity.why_now}</p>
          )}
          <p className="lede">
            {row.caution.charAt(0).toUpperCase() + row.caution.slice(1)}.{" "}
            {inferNote && (
              <>
                <span className="infer">{inferNote}</span>
                <span className="tag">inferred</span>
              </>
            )}
          </p>
          {shown?.quote && (
            <blockquote className="pull">
              {shown.quote}
              <cite>
                {SLOT[shown.slot]} ·{" "}
                {safeHref(shown.url ?? "") ? (
                  <a
                    href={safeHref(shown.url ?? "") ?? undefined}
                    target="_blank"
                    rel="noreferrer noopener"
                  >
                    {domain(shown.url)} ↗
                  </a>
                ) : (
                  domain(shown.url)
                )}
                {onFollow &&
                  shown.state === "stated" &&
                  (flagged(shown.slot) ? (
                    <span className="flagged">flagged as wrong</span>
                  ) : (
                    <button
                      type="button"
                      className="flag"
                      disabled={saving}
                      title="This fact is wrong: tell Northvaine"
                      onClick={() => follow({ kind: "wrong", step: SLOT[shown.slot] })}
                    >
                      Wrong?
                    </button>
                  ))}
              </cite>
            </blockquote>
          )}

          <div
            className="chain"
            style={{
              gridTemplateColumns: `repeat(${chain.length}, minmax(0, 1fr)) 46px`,
            }}
          >
            {chain.map((l, i) => (
              <div
                key={l.slot}
                className={`link ${l.state}`}
                style={{ animationDelay: `${i * 90}ms` }}
              >
                <span className="node" />
                <button
                  type="button"
                  onClick={() => setPicked(i)}
                  disabled={!l.quote}
                  title={
                    l.quote
                      ? "Show the source"
                      : l.state === "unknown"
                        ? "Not yet known"
                        : undefined
                  }
                >
                  <span className="caps">{SLOT[l.slot]}</span>
                  <span className="l">{nice(stripCountry(l.label))}</span>
                </button>
              </div>
            ))}
            <div className="link you">
              <span className="node" />
              <span className="caps" style={{ color: "var(--signal)" }}>
                You
              </span>
            </div>
          </div>

          {(row.dots ?? []).length > 0 && (
            <ol className="dots" aria-label="Where it comes from">
              {(row.dots ?? []).slice(0, 3).map((d, i) => (
                <li key={i}>
                  <span className="caps">{DOT_KIND[d.kind]}</span>
                  <span>{d.line}</span>
                  <DotSource dot={d} />
                </li>
              ))}
            </ol>
          )}

          <div className="kiu">
            <div>
              <span className="caps">On record</span>
              {by("stated").map((l) => (
                <div className="r" key={l.slot}>
                  <i className="m s" />
                  <span>
                    {SLOT[l.slot]}: {nice(stripCountry(l.label))}
                  </span>
                </div>
              ))}
              {by("stated").length === 0 && (
                <div className="r u">nothing yet</div>
              )}
            </div>
            <div>
              <span className="caps">Inferred</span>
              {by("inferred").map((l) => (
                <div className="r h" key={l.slot}>
                  <i className="m h" />
                  <span>
                    {SLOT[l.slot]}: {nice(stripCountry(l.label))}
                  </span>
                </div>
              ))}
              {by("inferred").length === 0 && (
                <div className="r u">nothing</div>
              )}
            </div>
            <div>
              <span className="caps">Not yet known</span>
              {by("unknown").map((l) => (
                <div className="r u" key={l.slot}>
                  <i className="m u" />
                  <span>{l.label}</span>
                </div>
              ))}
              {by("unknown").length === 0 && (
                <div className="r u">nothing open</div>
              )}
            </div>
          </div>
        </div>
      </div>

      <aside className="sside">
        <div className="content" data-content>
          <DecisionBox
            row={row}
            question="Is this one for you?"
            decided={decided}
            onDecide={onDecide}
            followed={followed}
            onFollow={onFollow}
          />
          {error && (
            <div className="err" role="alert">
              {error}
            </div>
          )}
          <div className="sec">
            <span className="caps">Source</span>
            <div className="kv">
              <span className="caps">Record</span>
              {shown?.url && safeHref(shown.url) ? (
                <a
                  href={safeHref(shown.url) ?? undefined}
                  target="_blank"
                  rel="noreferrer noopener"
                >
                  {domain(shown.url)} ↗
                </a>
              ) : (
                <span>none quoted</span>
              )}
              <span className="caps">Stage</span>
              <span>{stageOf(row)}</span>
              <span className="caps">Evidence</span>
              <span>
                {(row.evidence_level ?? "not assessed").replace(/_/g, " ")}
              </span>
            </div>
          </div>
          <div className="sec">
            <span className="caps">How to reach them · company only</span>
            <div className="kv">
              <span className="caps">Ask for</span>
              <span>
                {row.stream === "tender"
                  ? "The procurement contact on the notice"
                  : row.stream === "trade"
                    ? "Purchasing or the buying team"
                    : "Purchasing, for this project"}
              </span>
              {row.say && (
                <>
                  <span className="caps">Ask</span>
                  <span>{row.say}</span>
                </>
              )}
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
}
