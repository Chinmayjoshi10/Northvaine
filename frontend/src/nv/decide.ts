import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { BriefView, FeedbackRecord, Learning, Lesson, Row } from "../types";
import type { Decision } from "./CaseSheet";

// A decision on a lead is the feedback (D95): one tap, saved for the run it was made on.
// After each answer the server says what it changed (D100), and the page shows it.

/** Follow-ups are saved like decisions; their notes start with these words. */
export const HAPPENED = "What happened: ";
export const WRONG = "Wrong fact: ";

export type FollowUp =
  | { kind: "outcome"; outcome: NonNullable<FeedbackRecord["outcome"]> }
  | { kind: "wrong"; step: string };

export function useDecisions(client: string, brief: BriefView) {
  const [decided, setDecided] = useState<Record<number, string>>({});
  const [followed, setFollowed] = useState<Record<number, string[]>>({});
  const [learning, setLearning] = useState<Learning | null>(null);
  const [lesson, setLesson] = useState<Lesson | null>(null);

  // answers already given for this run, so every screen shows what has been decided
  useEffect(() => {
    // the run's own date: "latest" is a route word, not a date the feedback store knows
    api.feedback(client, brief.as_of).then(
      (records: FeedbackRecord[]) => {
        const seen: Record<number, string> = {};
        const after: Record<number, string[]> = {};
        for (const f of records) {
          if (f.note.startsWith(HAPPENED) || f.note.startsWith(WRONG))
            (after[f.rank] ??= []).push(f.note);
          else seen[f.rank] = f.note || "decided";
        }
        setDecided(seen);
        setFollowed(after);
      },
      () => undefined,
    );
    api.learning(client).then(setLearning, () => undefined);
  }, [client, brief.as_of]);

  const send = async (r: Row, body: Partial<FeedbackRecord> & { note: string }) => {
    await api.sendFeedback({
      client: brief.client_id,
      as_of: brief.as_of,
      rank: r.rank,
      company: r.company,
      correct: null,
      relevant: null,
      new: null,
      actionable: null,
      failure_chip: null,
      accepted_for_contact: null,
      known_already: null,
      new_intelligence: null,
      contacted: null,
      outcome: null,
      ...body,
    });
    // what the answer changed, worded by the server from the real numbers
    try {
      const now = await api.learning(client);
      setLearning(now);
      setLesson(
        now.lessons.find((l) => l.rank === r.rank && l.as_of === brief.as_of) ?? null,
      );
    } catch {
      // the answer is saved; only the explanation is missing
    }
  };

  const decide = async (r: Row, d: Decision) => {
    await send(r, {
      correct: d.kind === "drop" && d.reason === "wrong fact" ? false : null,
      relevant: d.kind === "drop" ? false : true,
      // "later" is timing, not a judgement of the lead (D100)
      actionable: d.kind === "take" ? true : d.kind === "later" ? false : null,
      failure_chip:
        d.kind === "drop" ? (d.reason as FeedbackRecord["failure_chip"]) : null,
      accepted_for_contact:
        d.kind === "take" ? true : d.kind === "drop" ? false : null,
      note: d.label,
    });
    setDecided((prev) => ({ ...prev, [r.rank]: d.label }));
  };

  const follow = async (r: Row, f: FollowUp) => {
    const note =
      f.kind === "outcome" ? `${HAPPENED}${f.outcome}` : `${WRONG}${f.step}`;
    await send(
      r,
      f.kind === "outcome"
        ? {
            relevant: true,
            accepted_for_contact: true,
            contacted: f.outcome !== "none" ? true : null,
            outcome: f.outcome,
            note,
          }
        : { correct: false, failure_chip: "wrong fact", note },
    );
    setFollowed((prev) => ({ ...prev, [r.rank]: [...(prev[r.rank] ?? []), note] }));
  };

  const dismiss = useCallback(() => setLesson(null), []);

  return { decided, decide, followed, follow, learning, lesson, dismiss };
}
