import { useEffect, useRef, useState, type RefObject } from "react";
import content from "./landingContent.json";
import { motionOk } from "./useReveal";

// Ports of the locked design's script behaviours (docs/design/final/landing.html):
// resolveTile(), sideways() and thread(). Each is an effect with cleanup. Without motion
// (reduced motion, no IntersectionObserver) the final state is shown at once.

const ease3 = (k: number) => 1 - Math.pow(1 - k, 3);

/** Timers that are all cleared when the effect is torn down. */
function makeClock() {
  const timers = new Set<number>();
  let frame = 0;
  let stopped = false;
  return {
    get stopped() {
      return stopped;
    },
    sleep: (ms: number) =>
      new Promise<void>((resolve) => {
        const timer = window.setTimeout(() => {
          timers.delete(timer);
          resolve();
        }, ms);
        timers.add(timer);
      }),
    raf: (fn: FrameRequestCallback) => {
      frame = requestAnimationFrame(fn);
    },
    stop: () => {
      stopped = true;
      timers.forEach(window.clearTimeout);
      cancelAnimationFrame(frame);
    },
  };
}

/** "What it does" tile 2: the chain resolves step by step, then loops (design resolveTile). */
export function ResolveTile() {
  const pts = content.resolve;
  const [animated] = useState(motionOk);
  const [shown, setShown] = useState(animated ? 0 : pts.length);
  const [prog, setProg] = useState<number[]>(animated ? [0, 0, 0] : [1, 1, 1]);

  useEffect(() => {
    if (!animated) return;
    const clock = makeClock();
    const grow = (i: number) =>
      new Promise<void>((resolve) => {
        const t0 = performance.now();
        const step = (now: number) => {
          if (clock.stopped) return;
          const k = Math.min(1, (now - t0) / 520);
          setProg((p) => p.map((v, j) => (j === i ? ease3(k) : v)));
          if (k < 1) clock.raf(step);
          else resolve();
        };
        clock.raf(step);
      });
    void (async () => {
      while (!clock.stopped) {
        setShown(0);
        setProg([0, 0, 0]);
        for (let i = 0; i < pts.length; i++) {
          setShown(i + 1);
          if (i < pts.length - 1) {
            await clock.sleep(280);
            await grow(i);
          }
        }
        await clock.sleep(2800);
      }
    })();
    return clock.stop;
  }, [animated, pts]);

  return (
    <div className="landing-resolve">
      <svg width="340" height="200" viewBox="0 0 340 200" aria-hidden="true">
        {pts.slice(0, -1).map((a, i) => {
          const b = pts[i + 1];
          return (
            <line
              key={a.k}
              className={`rs-line${i === 2 ? " buyer" : ""}`}
              x1={a.x}
              y1={a.y}
              x2={a.x + (b.x - a.x) * prog[i]}
              y2={a.y + (b.y - a.y) * prog[i]}
            />
          );
        })}
        {pts.map((p, i) => {
          const up = p.y < 100;
          return (
            <g key={p.k} opacity={shown > i ? 1 : 0}>
              {i === pts.length - 1 ? (
                <circle className="rs-you" cx={p.x} cy={p.y} r={6} />
              ) : (
                <rect className="rs-sq" x={p.x - 5} y={p.y - 5} width={10} height={10} />
              )}
              <text className="k" x={p.x} y={up ? p.y - 16 : p.y + 24} textAnchor="middle">{p.k.toUpperCase()}</text>
              {p.n && <text x={p.x} y={up ? p.y - 29 : p.y + 38} textAnchor="middle">{p.n}</text>}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

const NARROW = "(max-width: 760px)";

/**
 * The sideways chapter (design sideways()): on wide screens the section pins and vertical
 * scroll moves the track across. Elsewhere (small screens, reduced motion, no script) the
 * track stays a horizontal swipe track. The section class `pinned` is the only switch.
 */
export function useSideways(
  section: RefObject<HTMLElement | null>,
  track: RefObject<HTMLElement | null>,
  bar: RefObject<HTMLElement | null>,
  setCurrent: (n: number) => void,
) {
  useEffect(() => {
    const sec = section.current;
    const strip = track.current;
    const fill = bar.current;
    if (!sec || !strip || !fill) return;
    const cards = Array.from(strip.children) as HTMLElement[];
    const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let pinned = false;
    let dist = 0;
    let queued = false;

    const reset = () => {
      sec.style.height = "";
      strip.style.transform = "";
      fill.style.width = "";
      cards.forEach((c) => {
        c.style.transform = "";
        c.style.opacity = "";
      });
    };
    const size = () => {
      pinned = !window.matchMedia(NARROW).matches && !reduced();
      sec.classList.toggle("pinned", pinned);
      if (!pinned) {
        reset();
        return;
      }
      dist = Math.max(0, strip.scrollWidth - window.innerWidth);
      sec.style.height = `${dist + window.innerHeight}px`;
    };
    const frame = () => {
      queued = false;
      if (!pinned) return;
      const p = Math.min(1, Math.max(0, -sec.getBoundingClientRect().top / Math.max(1, dist)));
      strip.style.transform = `translate3d(${-p * dist}px,0,0)`;
      fill.style.width = `${p * 100}%`;
      const mid = window.innerWidth / 2;
      let best = 0;
      let bestD = 1e9;
      cards.forEach((c, i) => {
        const r = c.getBoundingClientRect();
        const d = Math.abs(r.left + r.width / 2 - mid);
        const k = Math.min(1, d / window.innerWidth);
        c.style.transform = `scale(${1 - k * 0.05})`;
        c.style.opacity = String(1 - k * 0.35);
        if (d < bestD && i < cards.length - 1) {
          bestD = d;
          best = i;
        }
      });
      setCurrent(best + 1);
    };
    const queue = () => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(frame);
    };
    const relayout = () => {
      size();
      frame();
    };
    relayout();
    window.addEventListener("resize", relayout);
    window.addEventListener("scroll", queue, { passive: true });
    void document.fonts?.ready.then(relayout);
    return () => {
      window.removeEventListener("resize", relayout);
      window.removeEventListener("scroll", queue);
      sec.classList.remove("pinned");
      reset();
    };
  }, [section, track, bar, setCurrent]);
}

/** Offset of `el` from `root` in layout terms (ignores transforms; the pinned header counts at its natural spot). */
function layoutBox(el: HTMLElement, root: HTMLElement) {
  let x = 0;
  let y = 0;
  let node: HTMLElement | null = el;
  while (node && node !== root) {
    if (!node.classList.contains("landing-pin")) {
      x += node.offsetLeft;
      y += node.offsetTop;
    }
    node = node.offsetParent as HTMLElement | null;
  }
  return { x, y, w: el.offsetWidth, h: el.offsetHeight };
}

/** The thread (design thread()): one line through every section, drawn by the reader's scroll. */
export function Thread({ rebuildKey }: { rebuildKey: unknown }) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    const svg = svgRef.current;
    const root = svg?.parentElement;
    if (!svg || !root) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const NS = "http://www.w3.org/2000/svg";
    let path: SVGPathElement | null = null;
    let nodes: Array<[number, SVGRectElement]> = [];
    let end: SVGCircleElement | null = null;
    let samples: Array<[number, number]> = [];
    let total = 0;
    let queued = false;
    const timers = new Set<number>();

    const make = <K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string | number>) => {
      const e = document.createElementNS(NS, tag);
      for (const k in attrs) e.setAttribute(k, String(attrs[k]));
      svg.appendChild(e);
      return e;
    };

    const frame = () => {
      queued = false;
      if (!path || !end) return;
      const y = window.innerHeight * 0.62 - root.getBoundingClientRect().top;
      let len = 0;
      for (const [l, py] of samples) {
        if (py <= y) len = l;
        else break;
      }
      // The last screen cannot scroll further: finish the line into the mark.
      if (window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 6) len = total;
      path.style.strokeDashoffset = String(total - len);
      nodes.forEach(([ny, r]) => r.classList.toggle("on", ny <= y));
      end.classList.toggle("on", len >= total - 10);
    };
    const queue = () => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(frame);
    };

    const build = () => {
      svg.replaceChildren();
      path = null;
      end = null;
      nodes = [];
      samples = [];
      if (window.matchMedia("(max-width: 900px)").matches) return;
      const tri = root.querySelector<HTMLElement>(".landing-final .landing-tri");
      const eyebrows = Array.from(root.querySelectorAll<HTMLElement>(".landing-eyebrow")).filter((e) => e.offsetParent !== null);
      if (!tri || eyebrows.length === 0) return;
      const W = root.clientWidth;
      const H = root.scrollHeight;
      svg.setAttribute("height", String(H));
      svg.setAttribute("width", String(W));
      svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
      const gx = Math.max(24, (W - 1240) / 2 + 40) - 22;
      const pts = eyebrows.map((e) => {
        const b = layoutBox(e, root);
        return { x: gx, y: b.y + b.h / 2, dark: !!e.closest(".landing-product") };
      });
      const t = layoutBox(tri, root);
      const last = { x: t.x + t.w / 2, y: t.y + t.h / 2 };
      let d = `M ${pts[0].x} ${pts[0].y}`;
      for (let i = 1; i < pts.length; i++) {
        const a = pts[i - 1];
        const b = pts[i];
        const wob = (i % 2 ? 1 : -1) * 10;
        d += ` C ${a.x + wob} ${a.y + (b.y - a.y) * 0.45}, ${b.x - wob} ${b.y - (b.y - a.y) * 0.45}, ${b.x} ${b.y}`;
      }
      const a = pts[pts.length - 1];
      const turn = last.y + 2; // down the margin, then across under the heading, into the mark
      d += ` L ${a.x} ${turn - 60} C ${a.x} ${turn - 10}, ${a.x + 30} ${turn}, ${a.x + 80} ${turn} L ${last.x - 26} ${turn}`;
      make("path", { d, class: "base" });
      path = make("path", { d, class: "ink" });
      total = path.getTotalLength();
      path.style.strokeDasharray = `${total} ${total}`;
      path.style.strokeDashoffset = String(total);
      for (let l = 0; l <= total; l += 8) samples.push([l, path.getPointAtLength(l).y]);
      pts.forEach((pt) => {
        const r = make("rect", { x: pt.x - 4, y: pt.y - 4, width: 8, height: 8, class: `node${pt.dark ? " dark" : ""}` });
        nodes.push([pt.y, r]);
      });
      end = make("circle", { cx: last.x - 18, cy: last.y + 2, r: 5, class: "end" });
      frame();
    };
    const later = (ms: number) => {
      const timer = window.setTimeout(() => {
        timers.delete(timer);
        build();
      }, ms);
      timers.add(timer);
    };

    build();
    later(120);
    later(1500); // after the opening has settled
    const rebuild = () => requestAnimationFrame(build);
    window.addEventListener("scroll", queue, { passive: true });
    window.addEventListener("resize", rebuild);
    void document.fonts?.ready.then(() => later(50));
    // The page height changes when the sideways section is sized: follow it.
    let ro: ResizeObserver | null = null;
    if (typeof ResizeObserver !== "undefined") {
      let lastH = root.scrollHeight;
      ro = new ResizeObserver(() => {
        if (root.scrollHeight !== lastH) {
          lastH = root.scrollHeight;
          rebuild();
        }
      });
      ro.observe(root);
    }
    return () => {
      window.removeEventListener("scroll", queue);
      window.removeEventListener("resize", rebuild);
      ro?.disconnect();
      timers.forEach(window.clearTimeout);
      svg.replaceChildren();
    };
  }, [rebuildKey]);

  return <svg className="landing-thread" ref={svgRef} aria-hidden="true" />;
}
