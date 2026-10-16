import { useEffect, useState } from "react";
import stationDark from "../assets/station-dark.jpg";
import { link } from "../routes";
import content from "./landingContent.json";
import "../nv/nv.css";
import "./landing.css";

const cases = content.cases;
const industryLeads = content.industryLeads;

function Intro({ replay }: { replay: boolean }) {
  const [visible, setVisible] = useState(true);
  const [word, setWord] = useState("");
  const [marked, setMarked] = useState(false);
  const [calculating, setCalculating] = useState(false);

  useEffect(() => {
    let stopped = false;
    const timers = new Set<number>();
    const wait = (ms: number) =>
      new Promise<void>((resolve) => {
        const timer = window.setTimeout(resolve, ms);
        timers.add(timer);
      });
    let seen = true;
    try {
      seen = sessionStorage.getItem("nv-seen") === "1";
    } catch {
      // A private window may block storage. Showing no forced intro is the safe fallback.
    }
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches || (seen && !replay)) {
      setVisible(false);
      return;
    }
    setVisible(true);
    setMarked(false);
    setCalculating(false);
    try {
      sessionStorage.setItem("nv-seen", "1");
    } catch {
      // The animation still works for this visit.
    }
    void (async () => {
      await wait(500);
      for (const next of ["Your", "competitors", "don’t", "know", "yet"]) {
        if (stopped) return;
        setWord(next);
        await wait(400);
      }
      if (stopped) return;
      setWord("");
      setCalculating(true);
      await wait(1300);
      setCalculating(false);
      setWord("You");
      await wait(420);
      if (stopped) return;
      setWord("will");
      setMarked(true);
      await wait(1300);
      if (!stopped) setVisible(false);
    })();
    return () => {
      stopped = true;
      timers.forEach(window.clearTimeout);
    };
  }, [replay]);

  return (
    <div className={`landing-voice${visible ? "" : " done"}`} aria-hidden={!visible}>
      <div className={`landing-voice-word${marked ? " mark" : ""}`}>
        <span>{word}</span><i className="landing-tri" />
      </div>
      <div className={`landing-calc${calculating ? " on" : ""}`}><i /></div>
      <button className="landing-skip mono" type="button" onClick={() => setVisible(false)}>skip →</button>
    </div>
  );
}

function LeadCard() {
  const [index, setIndex] = useState(0);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = window.setInterval(() => setIndex((value) => (value + 1) % cases.length), 6400);
    return () => window.clearInterval(timer);
  }, []);
  const lead = cases[index];
  return (
    <div className="landing-stack" aria-live="polite">
      <div className="landing-ghost g2" /><div className="landing-ghost g1" />
      <div className="landing-lead-card" key={lead.company}>
        <div className="landing-lead-top"><span className="mono">{lead.for}</span><span className="landing-seal"><i />Verified</span></div>
        <div className="landing-company">{lead.company}</div>
        <div className="landing-place mono">{lead.place}</div>
        <div className="landing-intent-block">
          <span className="landing-k">Intent</span>
          <div className="landing-intent"><b>{lead.intent}</b><span className={`landing-meter${lead.level >= 4 ? " hot" : ""}`}>{[0, 1, 2, 3, 4].map((bar) => <i className={bar < lead.level ? "on" : ""} key={bar} />)}</span><span className="mono">{lead.strength}</span></div>
        </div>
        <div className="landing-lead-grid"><div><span className="landing-k">Why now</span>{lead.why}</div><div><span className="landing-k">Who decides</span>{lead.who}</div></div>
        <div className="landing-quote">{lead.quote}<span className="mono">verified against the original record</span></div>
        <div className="landing-actions"><span className="landing-act">{lead.action}</span><span className="landing-ghost-button">Assign</span><span className="mono">added to your leads</span></div>
      </div>
    </div>
  );
}

function WebsiteCta({ label }: { label: string }) {
  return <a className="landing-btn dark" href={link("onboarding")}>{label}</a>;
}

export function LandingPage({ intro }: { intro: boolean }) {
  useEffect(() => {
    document.title = "Northvaine";
    const reveals = Array.from(document.querySelectorAll<HTMLElement>(".landing .reveal"));
    const observer = new IntersectionObserver((entries) => entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("in");
        observer.unobserve(entry.target);
      }
    }), { threshold: 0.16 });
    reveals.forEach((element) => observer.observe(element));
    return () => observer.disconnect();
  }, []);

  return (
    <div className="nv landing" data-theme="light">
      <Intro replay={intro} />
      <nav className="landing-nav"><div className="landing-wrap">
        <a className="landing-wordmark" href={link()}>NORTHVAINE</a><span className="landing-spacer" />
        <a className="landing-nav-link" href="#what">What it does</a><a className="landing-nav-link" href="#why">Why</a><a className="landing-nav-link" href="#industries">Industries</a><a className="landing-nav-link" href="#how">How it works</a><a className="landing-nav-link" href="#product">The product</a><a className="landing-nav-link" href="#trust">Trust</a>
        <a className="landing-nav-link" href={link("contact")}>Talk to us</a><a className="landing-nav-link" href={link("clients")}>Sign in</a><WebsiteCta label="Try it free" />
      </div></nav>

      <header className="landing-hero"><div className="landing-wrap landing-hero-grid">
        <div><div className="landing-eyebrow">Leads with intent, not lists</div><h1>Find the companies <em>about to buy</em> what you sell.</h1>
          <p className="landing-sub">For manufacturers, distributors and B2B suppliers in any industry. Northvaine finds companies with a real reason to buy from you, right now, often before they start looking for suppliers. Every lead comes with its intent, its timing, who decides, and the proof.</p>
          <div className="landing-ctas"><WebsiteCta label="Find my buyers →" /><a className="landing-btn line" href={link("app", "coldchain_maker", "latest")}>See a live example</a></div>
          <div className="landing-fine mono"><span>Free first radar</span><span>No card</span><span>Set up in minutes</span></div>
        </div><LeadCard />
      </div></header>

      <section className="landing-section" id="what"><div className="landing-wrap">
        <div className="landing-eyebrow reveal">What it does</div><h2 className="reveal">It doesn’t give you more leads. <em>It gives you the right one, with proof.</em></h2>
        <div className="landing-three">
          <article className="landing-feature reveal"><div className="landing-visual"><div className="landing-stream">{content.stream.map(([name, note, state]) => <div className={state} key={name}>{name}<span className="mono">{note}</span></div>)}</div></div><div className="landing-feature-copy"><span className="mono">01 · FINDS</span><h3>Only companies with intent</h3><p>Every company is checked first: would it buy from you, or does it sell what you sell? Competitors and noise never reach you.</p></div></article>
          <article className="landing-feature reveal"><div className="landing-visual landing-chain"><span><i />Project<small>Old-town works</small></span><b /><span><i />Commitment<small>Contract won</small></span><b /><span><i />Buyer<small>SAS Antoniotti</small></span><b className="dashed" /><span className="you"><i />You</span></div><div className="landing-feature-copy"><span className="mono">02 · INVESTIGATES</span><h3>Finds who actually buys</h3><p>The company in the headline is often not the one placing the order. Northvaine follows the chain until it reaches the buyer.</p></div></article>
          <article className="landing-feature reveal"><div className="landing-visual"><div className="landing-proof">Winner: <mark>SAS ANTONIOTTI</mark>; RAFFALLI TRAVAUX PUBLICS; COMPAGNIE DE DIFFUSION DE PANNEAUX DE SIGNALISATION ET ACCESSOIRES<span><i />found word for word in the original record</span></div></div><div className="landing-feature-copy"><span className="mono">03 · PROVES</span><h3>Proves every lead</h3><p>Every fact is checked against its original record before you see it. What is inferred says so. What is unknown stays unknown.</p></div></article>
        </div>
      </div></section>

      <section className="landing-section" id="why"><div className="landing-wrap"><div className="landing-eyebrow reveal">Why sales teams use it</div><h2 className="reveal">More of the right customers, <em>earlier than your competitors.</em></h2>
        <div className="landing-gains reveal"><div><b>Earlier</b><p>Know when a company commits to something that needs your product, while it is still choosing suppliers, not when the request for quotes reaches everyone.</p></div><div><b>Only real buyers</b><p>Competitors, resellers and publishers are removed first. Your team stops chasing companies that sell what you sell.</p></div><div><b>Who places the order</b><p>Not just a company name: the part of the business that buys, the role to ask for, and how to reach the company.</p></div><div><b>Proof you can trust</b><p>Every lead links to its source. No invented facts, no guessed numbers. Your team walks into the call knowing what is true.</p></div></div>
        <div className="landing-who reveal"><span className="mono">WHO IT’S FOR</span><div className="landing-who-grid">{content.audiences.map(([title, description]) => <div key={title}><b>{title}</b><span>{description}</span></div>)}</div></div>
      </div></section>

      <section className="landing-industries" id="industries"><div className="landing-wrap"><div className="landing-industries-head"><div><div className="landing-eyebrow">One lead for every industry</div><h2>Whatever you sell, <em>someone is about to buy it.</em></h2></div><span className="mono">6 real leads · three industries</span></div></div>
        <div className="landing-track">{industryLeads.map((lead) => <article className="landing-industry-card" key={lead[1]}><div className="landing-industry"><span>{lead[0]}</span><span className="landing-seal"><i />Verified</span></div><h3>{lead[1]}</h3><span className="landing-place">{lead[2]}</span><div className="landing-industry-intent"><span><span className="landing-k">Intent</span><b>{lead[3]}</b></span><span className="mono">{lead[8]}</span></div><div className="landing-lead-grid"><div><span className="landing-k">Why now</span>{lead[4]}</div><div><span className="landing-k">Who decides</span>{lead[5]}</div></div><div className="landing-quote">{lead[6]}</div><div className="landing-actions"><span className="landing-act">{lead[7]}</span><span className="landing-ghost-button">Assign</span></div></article>)}
          <article className="landing-industry-card end"><h3>Your industry next.</h3><p>Give it your website and see the companies with a reason to buy from you.</p><WebsiteCta label="Find my buyers →" /></article>
        </div>
      </section>

      <section className="landing-section" id="how"><div className="landing-wrap"><div className="landing-eyebrow reveal">How it works</div><h2 className="reveal">Give it your website. <em>Get your buyers.</em></h2><div className="landing-steps reveal">
        <article><span className="mono">01</span><h3>It learns what you sell</h3><p>From your own website. You see what it understood, each point with a quote from your site, and correct anything.</p><div className="landing-mini">{content.learnRows.map(([label, value, note]) => <div key={label}><span>{label}</span>{label === "From" ? <em>{value}</em> : value}{note && <b>{note}</b>}</div>)}</div></article>
        <article><span className="mono">02</span><h3>It builds your radar</h3><p>What intent looks like for your business, who ends up placing the order, and what to ignore. Built for you, never a generic list.</p><div className="landing-mini">{content.radarRows.map(([label, value]) => <div key={label}><span>{label}</span>{value}</div>)}</div></article>
        <article><span className="mono">03</span><h3>Your team acts first</h3><p>The few opportunities worth your time, ranked by what waiting costs. One tap to assign, pursue or pass. Every decision makes the next leads sharper.</p><div className="landing-mini">{content.actionRows.map(([label, value, note]) => <div key={value}><span>{label}</span>{value}<b>{note}</b></div>)}</div></article>
      </div><div className="landing-ctas reveal"><WebsiteCta label="Build my radar, free →" /><a className="landing-btn line" href="#product">See the product</a></div></div></section>

      <section className="landing-product" id="product"><div className="landing-wrap"><div className="landing-eyebrow reveal">The product</div><h2 className="reveal">A station for commercial decisions. <em>Not another lead list.</em></h2><p className="landing-lede reveal">Your territory, the decisions waiting by what waiting costs, what changed in your market, and who on your team owns each opportunity.</p><div className="landing-stage reveal"><img src={stationDark} alt="The Northvaine Station" /></div><div className="landing-caption mono"><span>Companies and situations from a real run. Every fact verified.</span><span>Team and CRM details are examples.</span></div><div className="landing-stats reveal"><div><b>51</b><span>companies assessed for one supplier</span></div><div><b>11</b><span>removed as sellers or noise</span></div><div className="signal"><b>1</b><span>ready to act, with proof</span></div><div><b>0</b><span>facts without a source</span></div></div><WebsiteCta label="Try it on your market →" /></div></section>

      <section className="landing-section" id="trust"><div className="landing-wrap"><div className="landing-eyebrow reveal">Trust</div><h2 className="reveal">It watches markets, <em>never people.</em></h2><div className="landing-rules reveal"><div><b>No source, no claim.</b><p>A fact without a verified quote is never shown, scored or used.</p></div><div><b>Companies only.</b><p>It follows organisations and public records. It never profiles individuals.</p></div><div><b>A person decides.</b><p>Northvaine prepares the decision. Prices, terms and outreach stay yours.</p></div><div><b>Nothing sent for you.</b><p>It recommends. It never contacts anyone on your behalf.</p></div></div></div></section>

      <section className="landing-final" id="start"><div className="landing-wrap"><div className="landing-say"><span>Give</span><span>me</span><span>your</span><span>website</span></div><i className="landing-tri" /><div className="landing-final-actions"><WebsiteCta label="Build my radar →" /><a className="landing-btn line" href={link("app", "coldchain_maker", "latest")}>See a live example</a></div><div className="landing-fine mono"><span>Free first radar</span><span>No card</span><span>Set up in minutes</span></div></div></section>
      <footer className="landing-footer"><div className="landing-wrap mono"><span>NORTHVAINE · reasoning by NVIDIA Nemotron on Nebius Token Factory · search by Tavily</span><span>Open source · Apache 2.0</span></div></footer>
    </div>
  );
}
