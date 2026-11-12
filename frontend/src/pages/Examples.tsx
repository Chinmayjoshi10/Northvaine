import { useState } from "react";
import { api } from "../api";
import type { ExampleCard } from "../api";
import { link } from "../routes";
import { useLoad } from "../useLoad";

// Ready-made radars for different industries (finished runs, made safe and published as static
// files by scripts/export_examples.py). Shown so a visitor sees what Northvaine produces for a
// business like theirs without waiting for a run. The live "Build my radar" stays the main action.
// Nothing here names an industry: the cards come from the data.

function Facts({ card }: { card: ExampleCard }) {
  return (
    <dl className="landing-ex-facts">
      <div>
        <dt>Companies checked</dt>
        <dd>{card.found}</dd>
      </div>
      <div>
        <dt>Set aside before you see them</dt>
        <dd>{card.set_aside}</dd>
      </div>
      <div className="signal">
        <dt>Shown with proof</dt>
        <dd>{card.shown}</dd>
      </div>
    </dl>
  );
}

export function Examples() {
  const cards = useLoad(() => api.examples(), []);
  const [chosen, setChosen] = useState(0);
  // No examples published (or the files are not there): the section simply is not shown.
  if (cards.state !== "ready" || cards.data.length === 0) return null;
  const list = cards.data;
  const card = list[Math.min(chosen, list.length - 1)];
  return (
    <section className="landing-section" id="examples">
      <div className="landing-wrap">
        <div className="landing-eyebrow">Examples</div>
        <h2>
          See a finished radar <em>for a business like yours.</em>
        </h2>
        <p className="landing-ex-lede">
          Real runs for {list.length} different industries, opened exactly as you would use them.
          Every fact links to its source; examples are read-only and described by what the
          business does.
        </p>
        <div className="landing-ex-tabs" role="tablist" aria-label="Example industries">
          {list.map((c, i) => (
            <button
              key={c.client}
              type="button"
              role="tab"
              id={`ex-tab-${i}`}
              aria-selected={i === chosen}
              aria-controls="ex-panel"
              className="landing-ex-tab"
              onClick={() => setChosen(i)}
            >
              {c.industry}
            </button>
          ))}
        </div>
        <article
          className="landing-ex-panel"
          id="ex-panel"
          role="tabpanel"
          aria-labelledby={`ex-tab-${Math.min(chosen, list.length - 1)}`}
        >
          <div>
            <span className="landing-k">{card.industry}</span>
            <h3>{card.name}</h3>
            <p>{card.summary}</p>
            <a className="landing-btn dark" href={link("app", card.client, "latest")}>
              Open this radar
              <span className="lm-arrow" aria-hidden="true">
                →
              </span>
            </a>
          </div>
          <Facts card={card} />
        </article>
      </div>
    </section>
  );
}
