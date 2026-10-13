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
