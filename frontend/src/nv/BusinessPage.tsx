import { api } from "../api";
import type { BusinessView } from "../types";
import { link } from "../routes";
import { useLoad } from "../useLoad";
import { Shell } from "./Shell";
import "./business.css";

// Your business: what the radar was told about the client, so they can see why it finds what
// it finds. Read-only for now; corrections go through "Talk to us".

const SOURCE: Record<string, string> = {
  hmrc: "UK import records (HMRC)",
  fts: "UK public tenders (Find a Tender)",
  ted: "EU public tenders and awards (TED)",
  usaspending: "US public contracts (USAspending)",
  worldbank: "World Bank projects",
  tavily: "News and company websites (Tavily)",
};

function Block(props: { title: string; items: string[]; empty?: string; note?: string }) {
  return (
    <section className="biz-block">
      <h2 className="mono">{props.title}</h2>
      {props.note && <p className="biz-note">{props.note}</p>}
      {props.items.length > 0 ? (
        <ul className="biz-tags">
          {props.items.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      ) : (
        <p className="biz-empty">{props.empty ?? "Not set."}</p>
      )}
    </section>
  );
}

function Body({ b, client, day }: { b: BusinessView; client: string; day: string }) {
  const codes = (scheme: string) =>
    b.product_codes.filter((c) => c.startsWith(`${scheme}:`)).map((c) => c.slice(scheme.length + 1));
  return (
    <div className="biz">
      <p className="biz-eyebrow mono">Your business</p>
      <h1>{b.name ?? "What the radar knows about you"}</h1>
      <p className="biz-offer">{b.offer}</p>
      <p className="biz-note">
        This is what Northvaine was told about you. Every search and every lead comes from it.
        Something wrong? <a href={link("contact")}>Talk to us</a> and we will correct it.
      </p>
      <div className="biz-grid">
        <Block title="Your products, in your words" items={b.offer_terms} />
        <Block
          title="Related products"
          items={b.related_terms}
          note="A lead that names one of these is a possibility to check, never a match."
          empty="None."
        />
        <Block title="Where you sell" items={b.markets} />
        <Block title="Who buys from you" items={b.buyer_roles} />
        <Block
          title="Competition, never shown as leads"
          items={b.not_buyers}
          empty="None named."
        />
        <section className="biz-block">
          <h2 className="mono">Current customers left out</h2>
          <p className="biz-big">{b.existing_customers}</p>
          <p className="biz-note">Never shown as new leads. Their names stay private.</p>
        </section>
        <Block title="Customs codes" items={codes("hs")} empty="None: import records are not searched." />
        <Block title="Tender codes" items={codes("cpv")} empty="None: tenders are found by search only." />
      </div>
      <section className="biz-block biz-wide">
        <h2 className="mono">Where the radar looks</h2>
        <ul className="biz-sources">
          {b.searches.map((s) => (
            <li key={s.source}>
              <span>{SOURCE[s.source] ?? s.source}</span>
              <span className="mono">
                {s.count} {s.count === 1 ? "search" : "searches"}
              </span>
            </li>
          ))}
        </ul>
      </section>
      <a className="biz-back mono" href={link("app", client, day)}>
        ← Station
      </a>
    </div>
  );
}

export function BusinessPage({ client, day }: { client: string; day: string }) {
  const business = useLoad(() => api.business(client), [client]);
  const crumb = (
    <>
      Station / <b>Your business</b>
    </>
  );
  return (
    <Shell client={client} day={day} screen="business" crumb={crumb}>
      {business.state === "loading" && <p className="biz-empty biz">Loading…</p>}
      {business.state === "error" && (
        <p className="biz-empty biz" role="alert">
          No business profile is saved for this radar yet.
        </p>
      )}
      {business.state === "ready" && <Body b={business.data} client={client} day={day} />}
    </Shell>
  );
}
