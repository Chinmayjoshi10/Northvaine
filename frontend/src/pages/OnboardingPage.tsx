import { useEffect, useState } from "react";
import { api, wakeLiveApi } from "../api";
import type { OnboardingAnswers, OnboardingSession, Proposal } from "../types";
import { link } from "../routes";
import "../nv/nv.css";
import "./landing.css";

// "Build my radar" (D105): start -> catalogue (or skip) -> your answers -> the radar runs.
type Step = "start" | "catalogue" | "answers" | "running";

const lines = (text: string) =>
  text
    .split(/\n|,/)
    .map((s) => s.trim())
    .filter(Boolean);

function useSession(id: string | null, every: number) {
  const [session, setSession] = useState<OnboardingSession | null>(null);
  useEffect(() => {
    if (!id) return;
    let stop = false;
    const tick = async () => {
      try {
        const s = await api.onboarding(id);
        if (!stop) setSession(s);
      } catch {
        // keep polling; a brief network error should not end onboarding
      }
    };
    void tick();
    const timer = window.setInterval(tick, every);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [id, every]);
  return session;
}

function Field(props: {
  id: string;
  label: string;
  hint?: string;
  value: string;
  onChange: (v: string) => void;
  rows?: number;
  required?: boolean;
}) {
  return (
    <>
      <label htmlFor={props.id}>{props.label}</label>
      {props.hint && <p className="onb-hint">{props.hint}</p>}
      <textarea
        id={props.id}
        rows={Math.max(props.rows ?? 3, props.value.split("\n").length + 1)}
        value={props.value}
        required={props.required}
        onChange={(e) => props.onChange(e.target.value)}
      />
    </>
  );
}

const CHANNELS: { value: OnboardingAnswers["channel"]; label: string }[] = [
  { value: "direct", label: "End buyers (they use or install it)" },
  { value: "distributors", label: "Distributors and stockists (they resell it)" },
  { value: "both", label: "Both" },
];

function Answers({
  session,
  onDone,
}: {
  session: OnboardingSession;
  onDone: (a: OnboardingAnswers) => void;
}) {
  const p: Proposal = session.proposal!;
  const [offer, setOffer] = useState(p.offer);
  const [terms, setTerms] = useState(p.offer_terms.join("\n"));
  const [markets, setMarkets] = useState(p.markets.join(", "));
  const [buyers, setBuyers] = useState(p.buyer_roles.join("\n"));
  const [notBuyers, setNotBuyers] = useState(p.not_buyers.join("\n"));
  const roles = session.not_buyer_roles ?? [];
  const [roleKeys, setRoleKeys] = useState<string[]>(roles.map((r) => r.key));
  const toggleRole = (key: string) =>
    setRoleKeys((cur) => (cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key]));
  const [channel, setChannel] = useState<OnboardingAnswers["channel"]>("both");
  const [customers, setCustomers] = useState("");
  const [hs, setHs] = useState(p.hs_codes.join(", "));
  const [cpv, setCpv] = useState(p.cpv_codes.join(", "));
  const [phrases, setPhrases] = useState(p.search_phrases.join("\n"));
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    onDone({
      company: session.company,
      website: session.website,
      offer,
      offer_terms: lines(terms),
      related_terms: p.related_terms,
      markets: lines(markets).map((m) => m.toUpperCase()),
      buyer_roles: lines(buyers),
      not_buyers: lines(notBuyers),
      not_buyer_roles: roleKeys,
      hs_codes: lines(hs),
      cpv_codes: lines(cpv),
      search_phrases: lines(phrases),
      existing_customers: lines(customers),
      channel,
    });
  };
  return (
    <form className="contact-form" onSubmit={submit}>
      <p className="contact-lede">
        {session.site_read
          ? "We read your website and suggested answers. Check each one; change anything that is wrong."
          : "We could not read your website, so please fill these in."}
      </p>
      <Field
        id="o-offer"
        label="What do you sell?"
        hint="One or two sentences: what you make or sell, and to whom."
        value={offer}
        onChange={setOffer}
        rows={4}
        required
      />
      <Field
        id="o-terms"
        label="Your products, in your words"
        hint="One per line. These are the words we look for in tenders, news and records."
        value={terms}
        onChange={setTerms}
        rows={5}
        required
      />
      <Field
        id="o-markets"
        label="Where do you sell, or want to sell?"
        hint="Country codes, e.g. GB, DE, US."
        value={markets}
        onChange={setMarkets}
        rows={1}
        required
      />
      <Field
        id="o-buyers"
        label="Who buys from you?"
        hint="One per line, e.g. importers, distributors, contractors."
        value={buyers}
        onChange={setBuyers}
        rows={4}
        required
      />
      <fieldset className="onb-roles">
        <legend>Who do you sell to?</legend>
        {CHANNELS.map((c) => (
          <label key={c.value} className="onb-check">
            <input
              type="radio"
              name="o-channel"
              checked={channel === c.value}
              onChange={() => setChannel(c.value)}
            />
            <span>{c.label}</span>
          </label>
        ))}
      </fieldset>
      <Field
        id="o-not"
        label="Who is competition, not a buyer?"
        hint="One per line. We never show these as leads."
        value={notBuyers}
        onChange={setNotBuyers}
        rows={2}
      />
      {roles.length > 0 && (
        <fieldset className="onb-roles">
          <legend>Firms that only handle goods for others</legend>
          <p className="onb-hint">
            Companies that only move, clear or store goods for others. Untick if they buy from you.
          </p>
          {roles.map((r) => (
            <label key={r.key} className="onb-check">
              <input
                type="checkbox"
                checked={roleKeys.includes(r.key)}
                onChange={() => toggleRole(r.key)}
              />
              <span>{r.label}</span>
            </label>
          ))}
        </fieldset>
      )}
      <Field
        id="o-customers"
        label="Current customers to leave out (optional)"
        hint="Company names, one per line. They are never shown as new."
        value={customers}
        onChange={setCustomers}
        rows={2}
      />
      <details className="onb-more">
        <summary>Product codes and searches (optional)</summary>
        <Field
          id="o-hs"
          label="Customs codes (6 digits)"
          hint="Checked against the UK tariff. Used to find importers of your products."
          value={hs}
          onChange={setHs}
          rows={1}
        />
        <Field
          id="o-cpv"
          label="Tender codes (CPV, 8 digits)"
          hint="Used to find public tenders and contract awards."
          value={cpv}
          onChange={setCpv}
          rows={1}
        />
        <Field
          id="o-phrases"
          label="News searches"
          hint="One per line: signs a company is about to buy what you sell."
          value={phrases}
          onChange={setPhrases}
          rows={3}
        />
      </details>
      {p.dropped.length > 0 && (
        <details className="onb-more">
          <summary>Left out by our checks ({p.dropped.length})</summary>
          <ul>
            {p.dropped.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </details>
      )}
      <button className="landing-btn dark" type="submit">
        Build my radar
      </button>
    </form>
  );
}

export function OnboardingPage() {
  const [step, setStep] = useState<Step>("start");
  const [id, setId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [waking, setWaking] = useState(false);
  const [start, setStart] = useState({ company: "", website: "", email: "" });
  const [catalogueNote, setCatalogueNote] = useState("");
  const session = useSession(id, step === "running" ? 4000 : 2000);

  const begin = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    setWaking(true);
    await wakeLiveApi(); // static demo only: free hosting sleeps when idle
    setWaking(false);
    const r = await api.onboardingStart(start).catch(() => null);
    setBusy(false);
    if (r?.status === 409) {
      window.location.hash = link("contact", "used");
      return;
    }
    if (!r || !r.ok) {
      setError(
        "We could not start. Check the email address and website, and try again.",
      );
      return;
    }
    const s = (await r.json()) as OnboardingSession;
    setId(s.id);
    setStep("catalogue");
  };

  const upload = async (file: File | undefined) => {
    if (!file || !id) return;
    setBusy(true);
    setCatalogueNote("");
    try {
      const c = await api.onboardingCatalogue(id, file);
      setCatalogueNote(
        c.readable
          ? `Read ${c.pages} pages of your catalogue.`
          : `Your catalogue (${c.pages} pages) is mostly images, so we could read little text from it. Your answers will guide the radar instead.`,
      );
    } catch {
      setCatalogueNote(
        "That file could not be read. Upload a PDF under 25 MB, or skip this step.",
      );
    }
    setBusy(false);
  };

  const toAnswers = async () => {
    if (!id) return;
    await api.onboardingPropose(id).catch(() => null);
    setStep("answers");
  };

  const confirm = async (answers: OnboardingAnswers) => {
    if (!id) return;
    try {
      await api.onboardingAnswers(id, answers);
      setStep("running");
    } catch {
      setError(
        "Some answers are missing. Every field above the optional ones is needed.",
      );
    }
  };

  useEffect(() => {
    if (session?.stage === "done" && session.client_id) {
      window.location.hash = link("app", session.client_id, "latest");
    }
  }, [session?.stage, session?.client_id]);

  return (
    <div className="nv landing contact" data-theme="light">
      <nav className="landing-nav">
        <div className="landing-wrap">
          <a className="landing-wordmark" href={link()}>
            NORTHVAINE
          </a>
          <a className="landing-nav-link" href={link("contact")}>
            Talk to us
          </a>
        </div>
      </nav>
      <main className="contact-main" id="main">
        <p className="landing-eyebrow">
          Build my radar · step{" "}
          {["start", "catalogue", "answers", "running"].indexOf(step) + 1} of 4
        </p>
        {step === "start" && (
          <>
            <h1>Find the companies about to buy what you sell.</h1>
            <p className="contact-lede">
              Your first radar is free. It takes a few minutes.
            </p>
            <form className="contact-form" onSubmit={begin}>
              <label htmlFor="s-company">Company</label>
              <input
                id="s-company"
                required
                maxLength={200}
                value={start.company}
                onChange={(e) =>
                  setStart({ ...start, company: e.target.value })
                }
                autoComplete="organization"
              />
              <label htmlFor="s-website">Company website</label>
              <input
                id="s-website"
                required
                maxLength={300}
                value={start.website}
                placeholder="example.com"
                onChange={(e) =>
                  setStart({ ...start, website: e.target.value })
                }
              />
              <label htmlFor="s-email">Work email</label>
              <input
                id="s-email"
                required
                type="email"
                maxLength={320}
                value={start.email}
                onChange={(e) => setStart({ ...start, email: e.target.value })}
                autoComplete="email"
              />
              {waking && (
                <p className="onb-hint" role="status">
                  Waking up the radar server (free hosting sleeps when idle) - about a minute.
                </p>
              )}
              {error && (
                <p className="contact-error" role="alert">
                  {error}
                </p>
              )}
              <button
                className="landing-btn dark"
                type="submit"
                disabled={busy}
              >
                {busy ? "Starting…" : "Continue"}
              </button>
            </form>
          </>
        )}
        {step === "catalogue" && (
          <>
            <h1>Add your catalogue</h1>
            <p className="contact-lede">
              Optional. A PDF catalogue helps us learn the exact names of your
              products. While you decide, we are reading your website.
            </p>
            <div className="contact-form">
              <label htmlFor="c-file">Catalogue (PDF, up to 25 MB)</label>
              <input
                id="c-file"
                type="file"
                accept="application/pdf"
                onChange={(e) => void upload(e.target.files?.[0])}
                disabled={busy}
              />
              {busy && <p className="onb-hint">Reading your catalogue…</p>}
              {catalogueNote && (
                <p className="onb-hint" role="status">
                  {catalogueNote}
                </p>
              )}
              <div className="onb-row">
                <button
                  className="landing-btn dark"
                  type="button"
                  onClick={toAnswers}
                  disabled={busy}
                >
                  Continue
                </button>
                <button
                  className="landing-btn line"
                  type="button"
                  onClick={toAnswers}
                  disabled={busy}
                >
                  Skip
                </button>
              </div>
            </div>
          </>
        )}
        {step === "answers" && (
          <>
            <h1>Tell us about your buyers</h1>
            {session?.stage === "proposed" && session.proposal ? (
              <Answers session={session} onDone={confirm} />
            ) : session?.stage === "failed" ? (
              <p className="contact-error" role="alert">
                {session.error} <a href={link("contact")}>Talk to us</a> and we
                will set it up with you.
              </p>
            ) : (
              <p className="contact-lede" role="status">
                Reading your website{session?.catalogue ? " and catalogue" : ""}{" "}
                and preparing suggested answers…
              </p>
            )}
            {error && (
              <p className="contact-error" role="alert">
                {error}
              </p>
            )}
          </>
        )}
        {step === "running" && (
          <>
            <h1>Building your radar</h1>
            {session?.stage === "failed" ? (
              <p className="contact-error" role="alert">
                {session.error} <a href={link("contact")}>Talk to us</a> and we
                will run it for you.
              </p>
            ) : (
              <p className="contact-lede" role="status">
                Searching tenders, import records and news for buyers of what
                you sell, then checking every fact against its source. This
                takes about five minutes; this page opens your first edition
                when it is ready.
              </p>
            )}
          </>
        )}
      </main>
    </div>
  );
}
