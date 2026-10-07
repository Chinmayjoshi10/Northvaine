import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api";
import { FAILURE_CHIPS, OUTCOMES } from "../types";
import type { FeedbackRecord } from "../types";

type Tri = boolean | null;

function YesNo({
  legend,
  hint,
  value,
  onChange,
}: {
  legend: string;
  hint?: string;
  value: Tri;
  onChange: (v: Tri) => void;
}) {
  return (
    <fieldset className="q">
      <legend>{legend}</legend>
      {hint && <p className="muted small">{hint}</p>}
      <div className="seg" role="group" aria-label={legend}>
        <button type="button" aria-pressed={value === true} onClick={() => onChange(value === true ? null : true)}>
          Yes
        </button>
        <button type="button" aria-pressed={value === false} onClick={() => onChange(value === false ? null : false)}>
          No
        </button>
      </div>
    </fieldset>
  );
}

export function FeedbackForm(props: { client: string; day: string; rank: number; company: string }) {
  const [correct, setCorrect] = useState<Tri>(null);
  const [relevant, setRelevant] = useState<Tri>(null);
  const [isNew, setIsNew] = useState<Tri>(null);
  const [actionable, setActionable] = useState<Tri>(null);
  const [chip, setChip] = useState("");
  const [known, setKnown] = useState<Tri>(null);
  const [newIntel, setNewIntel] = useState<Tri>(null);
  const [contacted, setContacted] = useState<Tri>(null);
  const [outcome, setOutcome] = useState("");
  const [note, setNote] = useState("");
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [saved, setSaved] = useState(0);

  // Start from the latest saved answers for this entry, if any.
  useEffect(() => {
    let live = true;
    api.feedback(props.client, props.day).then(
      (rows) => {
        const mine = rows.filter((r) => r.rank === props.rank);
        setSaved(mine.length);
        const last = mine[mine.length - 1];
        if (!live || !last) return;
        setCorrect(last.correct);
        setRelevant(last.relevant);
        setIsNew(last.new);
        setActionable(last.actionable);
        setChip(last.failure_chip ?? "");
        setKnown(last.known_already);
        setNewIntel(last.new_intelligence);
        setContacted(last.contacted);
        setOutcome(last.outcome ?? "");
        setNote(last.note);
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [props.client, props.day, props.rank]);

  const anyNo = [correct, relevant, isNew, actionable].includes(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setStatus("saving");
    try {
      const body: Omit<FeedbackRecord, "received_at"> = {
        client: props.client,
        as_of: props.day,
        rank: props.rank,
        company: props.company,
        correct,
        relevant,
        new: isNew,
        actionable,
        failure_chip: anyNo && chip ? chip : null,
        known_already: known,
        new_intelligence: newIntel,
        contacted,
        outcome: outcome || null,
        note,
      };
      await api.sendFeedback(body);
      setSaved((n) => n + 1);
      setStatus("saved");
    } catch {
      setStatus("error");
    }
  }

  return (
    <form className="feedback" onSubmit={submit} aria-labelledby="fb">
      <h2 id="fb">Your feedback</h2>
      <p className="muted small">
        Each save is added to the log; nothing is overwritten.
        {saved > 0 && ` ${saved} saved for this entry so far.`}
      </p>

      <h3>Scorecard</h3>
      <YesNo legend="Correct?" hint="Every fact matches its source." value={correct} onChange={setCorrect} />
      <YesNo legend="Relevant?" hint="A plausible buyer of this offer." value={relevant} onChange={setRelevant} />
      <YesNo
        legend="New, or worth acting on?"
        hint="For your own business: previously unknown to you. Otherwise: would a salesperson act on this?"
        value={isNew}
        onChange={setIsNew}
      />
      <YesNo legend="Actionable?" hint="You know who to approach and why now." value={actionable} onChange={setActionable} />
      {anyNo && (
        <div className="q">
          <label htmlFor="chip">What went wrong?</label>
          <select id="chip" value={chip} onChange={(e) => setChip(e.target.value)}>
            <option value="">Choose one</option>
            {FAILURE_CHIPS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
      )}

      <h3>After contact</h3>
      <YesNo legend="Known already?" value={known} onChange={setKnown} />
      <YesNo
        legend="New intelligence?"
        hint="A new date, project, signal, route or reason to act, even on a known account."
        value={newIntel}
        onChange={setNewIntel}
      />
      <YesNo legend="Contacted?" value={contacted} onChange={setContacted} />
      <div className="q">
        <label htmlFor="outcome">Outcome</label>
        <select id="outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
          <option value="">Not yet</option>
          {OUTCOMES.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      </div>

      <div className="q">
        <label htmlFor="note">Note</label>
        <textarea id="note" rows={3} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} />
      </div>

      <button type="submit" className="btn primary" disabled={status === "saving"}>
        {status === "saving" ? "Saving…" : "Save feedback"}
      </button>
      <p role="status" aria-live="polite">
        {status === "saved" && "Saved."}
        {status === "error" && "Could not save. Try again."}
      </p>
    </form>
  );
}
