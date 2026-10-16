import { useState } from "react";
import { api } from "../api";
import type { ContactIn } from "../types";
import { link } from "../routes";
import "../nv/nv.css";
import "./landing.css";

// "Talk to us" (D104): a request a person answers. No payments in this build.
const EMPTY: ContactIn = {
  kind: "subscribe",
  name: "",
  company: "",
  email: "",
  website: "",
  message: "",
  website_url: "",
};

export function ContactPage({ reason }: { reason?: string }) {
  const [form, setForm] = useState<ContactIn>(EMPTY);
  const [state, setState] = useState<"idle" | "sending" | "sent" | "error">(
    "idle",
  );
  const [error, setError] = useState("");
  const set = (key: keyof ContactIn) => (value: string) =>
    setForm((f) => ({ ...f, [key]: value }));

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setState("sending");
    try {
      await api.contact(form);
      setState("sent");
    } catch {
      setState("error");
      setError(
        "We could not send that. Check the email address and try again.",
      );
    }
  };

  return (
    <div className="nv landing contact" data-theme="light">
      <nav className="landing-nav">
        <div className="landing-wrap">
          <a className="landing-wordmark" href={link()}>
            NORTHVAINE
          </a>
          <a className="landing-nav-link" href={link()}>
            Back to Northvaine
          </a>
        </div>
      </nav>
      <main className="contact-main" id="main">
        <p className="landing-eyebrow">Talk to us</p>
        <h1>Get Northvaine for your business.</h1>
        {reason === "used" ? (
          <p className="contact-lede">
            You have used your free radar. Tell us about your business and we
            will set up daily editions for you.
          </p>
        ) : (
          <p className="contact-lede">
            Tell us what you sell and where. A person reads every request and
            replies within one working day.
          </p>
        )}
        {state === "sent" ? (
          <div className="contact-done" role="status">
            <h2>Thank you. We have your request.</h2>
            <p>We will reply to {form.email} within one working day.</p>
            <a className="landing-btn dark" href={link()}>
              Back to Northvaine
            </a>
          </div>
        ) : (
          <form className="contact-form" onSubmit={submit}>
            <label htmlFor="c-kind">What do you need?</label>
            <select
              id="c-kind"
              value={form.kind}
              onChange={(e) => set("kind")(e.target.value)}
            >
              <option value="subscribe">Daily editions for my business</option>
              <option value="contact">A question</option>
            </select>
            <label htmlFor="c-name">Your name</label>
            <input
              id="c-name"
              required
              maxLength={120}
              value={form.name}
              onChange={(e) => set("name")(e.target.value)}
              autoComplete="name"
            />
            <label htmlFor="c-company">Company</label>
            <input
              id="c-company"
              required
              maxLength={200}
              value={form.company}
              onChange={(e) => set("company")(e.target.value)}
              autoComplete="organization"
            />
            <label htmlFor="c-email">Work email</label>
            <input
              id="c-email"
              required
              type="email"
              maxLength={320}
              value={form.email}
              onChange={(e) => set("email")(e.target.value)}
              autoComplete="email"
            />
            <label htmlFor="c-website">Company website</label>
            <input
              id="c-website"
              maxLength={300}
              value={form.website}
              onChange={(e) => set("website")(e.target.value)}
              placeholder="example.com"
            />
            <label htmlFor="c-message">What do you sell, and where?</label>
            <textarea
              id="c-message"
              rows={4}
              maxLength={2000}
              value={form.message}
              onChange={(e) => set("message")(e.target.value)}
            />
            {/* Hidden from people; bots fill it, and such requests are dropped. */}
            <input
              className="contact-trap"
              tabIndex={-1}
              aria-hidden="true"
              autoComplete="off"
              value={form.website_url}
              onChange={(e) => set("website_url")(e.target.value)}
            />
            {state === "error" && (
              <p className="contact-error" role="alert">
                {error}
              </p>
            )}
            <button
              className="landing-btn dark"
              type="submit"
              disabled={state === "sending"}
            >
              {state === "sending" ? "Sending…" : "Send request"}
            </button>
          </form>
        )}
      </main>
    </div>
  );
}
