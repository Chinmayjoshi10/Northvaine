import type { ReactNode } from "react";
import type { Loaded } from "./useLoad";

/** Shows loading and error states; renders `children` with the data when ready. */
export function Await<T>({
  result,
  children,
}: {
  result: Loaded<T>;
  children: (data: T) => ReactNode;
}) {
  if (result.state === "loading") return <p className="muted">Loading…</p>;
  if (result.state === "error") return <p role="alert">{result.message}</p>;
  return <>{children(result.data)}</>;
}

const STATUS_CLASS: Record<string, string> = {
  "contact now": "pill ok",
  "qualify first": "pill info",
  "watch only": "pill muted-pill",
};

export function StatusPill({ status }: { status: string }) {
  return <span className={STATUS_CLASS[status] ?? "pill"}>{status}</span>;
}

/** A sentence an AI wrote, labelled as such. */
export function ModelText({ text, model }: { text: string; model: boolean }) {
  return (
    <p>
      {model && <span className="label">model-written</span>} {text}
    </p>
  );
}
