import { createElement, useEffect, useRef, useState, type RefObject } from "react";

// Quiet landing-page motion (Card G). Everything starts visible; motion is added only when the
// browser supports it and the visitor has not asked for reduced motion.

export function motionOk(): boolean {
  try {
    return (
      typeof IntersectionObserver !== "undefined" &&
      !window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  } catch {
    return false;
  }
}

/** Words that rise one after another from behind a mask (the hero headline). */
export function Words({ text, start = 0 }: { text: string; start?: number }) {
  return createElement(
    "span",
    { "aria-hidden": true },
    text.split(" ").flatMap((word, i) => [
      i > 0 ? " " : null,
      createElement(
        "span",
        { className: "lm-word", key: `${word}${i}` },
        createElement(
          "span",
          { style: { transitionDelay: `${120 + (start + i) * 55}ms` } },
          word,
        ),
      ),
    ]),
  );
}

/** A number that counts up once when it scrolls into view. Shows the final value without motion. */
export function CountUp({ to, ms = 1400 }: { to: number; ms?: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [value, setValue] = useState(to);
  useEffect(() => {
    const el = ref.current;
    if (!el || !motionOk() || to === 0) return;
    setValue(0);
    let frame = 0;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        observer.disconnect();
        const begin = performance.now();
        const step = (now: number) => {
          const t = Math.min(1, (now - begin) / ms);
          setValue(Math.round(to * (1 - Math.pow(1 - t, 3))));
          if (t < 1) frame = requestAnimationFrame(step);
        };
        frame = requestAnimationFrame(step);
      },
      { threshold: 0.4 },
    );
    observer.observe(el);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      setValue(to);
    };
  }, [to, ms]);
  return createElement("span", { ref }, value);
}

/** A slight tilt toward the pointer (at most about two degrees), for fine pointers only. */
export function useTilt(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const el = ref.current;
    if (!el || !motionOk() || !window.matchMedia("(pointer: fine)").matches) return;
    let frame = 0;
    const move = (e: PointerEvent) => {
      const box = el.getBoundingClientRect();
      const x = (e.clientX - box.left) / box.width - 0.5;
      const y = (e.clientY - box.top) / box.height - 0.5;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        el.style.transform = `perspective(1400px) rotateX(${(-y * 3).toFixed(2)}deg) rotateY(${(x * 4).toFixed(2)}deg)`;
      });
    };
    const leave = () => {
      cancelAnimationFrame(frame);
      el.style.transform = "";
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerleave", leave);
    return () => {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerleave", leave);
      cancelAnimationFrame(frame);
    };
  }, [ref]);
}
