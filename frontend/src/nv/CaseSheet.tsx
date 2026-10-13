import { useEffect, useState } from "react";
import { safeHref } from "../api";
import { FAILURE_CHIPS } from "../types";
import type { Link, Row } from "../types";
import {
  SLOT,
  domain,
  headline,
  nice,
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
  return [
    { kind: "take", label: "I’ll take it" },
    { kind: "later", label: "Not now" },
    { kind: "drop", label: "Not for us" },
  ];
}

export function CaseSheet(props: {
  row: Row | null;
  decided: string | null;
  onDecide: (d: Decision) => Promise<void>;
  onClose: () => void;
}) {
  const { row, decided, onDecide, onClose } = props;
  const [picked, setPicked] = useState<number | null>(null);
  const [askWhy, setAskWhy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setPicked(null);
    setAskWhy(false);
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
        : null;

  const decide = async (d: Decision) => {
    setSaving(true);
    setError(null);
    try {
      await onDecide(d);
      setAskWhy(false);
    } catch (e) {
      setError(
        e instanceof Error
          ? `Not saved: ${e.message} Try again.`
          : "Not saved. Try again.",
      );
    } finally {
      setSaving(false);
    }
  };

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
          <div className="sec">
            <span className="caps">Your decision</span>
            <p className="ask2">Is this one for you?</p>
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
            {decided && !askWhy && (
              <div className="thanks">
                Noted. I’ll weigh this in the next run.
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
                  : "Purchasing, for this project"}
              </span>
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
}
