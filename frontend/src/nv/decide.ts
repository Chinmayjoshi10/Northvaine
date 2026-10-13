import { useEffect, useState } from "react";
import { api } from "../api";
import type { BriefView, FeedbackRecord, Row } from "../types";
import type { Decision } from "./CaseSheet";

// A decision on a lead is the feedback (D95): one tap, saved for the run it was made on.

export function useDecisions(client: string, brief: BriefView) {
  const [decided, setDecided] = useState<Record<number, string>>({});

  // answers already given for this run, so every screen shows what has been decided
  useEffect(() => {
    // the run's own date: "latest" is a route word, not a date the feedback store knows
    api.feedback(client, brief.as_of).then(
      (records: FeedbackRecord[]) => {
        const seen: Record<number, string> = {};
        for (const f of records) seen[f.rank] = f.note || "decided";
        setDecided(seen);
      },
      () => undefined,
    );
  }, [client, brief.as_of]);

  const decide = async (r: Row, d: Decision) => {
    const body: Omit<FeedbackRecord, "received_at"> = {
      client: brief.client_id,
      as_of: brief.as_of,
      rank: r.rank,
      company: r.company,
      correct: d.kind === "drop" && d.reason === "wrong fact" ? false : null,
      relevant: d.kind === "drop" ? false : true,
      new: null,
      actionable: d.kind === "take" ? true : d.kind === "later" ? false : null,
      failure_chip:
        d.kind === "drop" ? (d.reason as FeedbackRecord["failure_chip"]) : null,
      accepted_for_contact:
        d.kind === "take" ? true : d.kind === "drop" ? false : null,
      known_already: null,
      new_intelligence: null,
      contacted: null,
      outcome: null,
      note: d.label,
    };
    await api.sendFeedback(body);
    setDecided((prev) => ({ ...prev, [r.rank]: d.label }));
  };

  return { decided, decide };
}
