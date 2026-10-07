/** Hash link for a route, every part encoded. */
export function link(...parts: (string | number)[]): string {
  return "#/" + parts.map((p) => encodeURIComponent(String(p))).join("/");
}
