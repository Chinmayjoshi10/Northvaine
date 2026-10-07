import { useEffect, useState } from "react";

export type Loaded<T> =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; data: T };

/** Run an async loader when `deps` change. */
export function useLoad<T>(loader: () => Promise<T>, deps: unknown[]): Loaded<T> {
  const [result, setResult] = useState<Loaded<T>>({ state: "loading" });
  useEffect(() => {
    let live = true;
    setResult({ state: "loading" });
    loader().then(
      (data) => live && setResult({ state: "ready", data }),
      (error: unknown) =>
        live &&
        setResult({
          state: "error",
          message: error instanceof Error ? error.message : "Something went wrong.",
        }),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return result;
}
