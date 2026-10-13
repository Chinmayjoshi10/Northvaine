import { useEffect } from "react";
import type { Learning, Lesson } from "../types";
import { nice } from "./lead";
import "./learn.css";

// After an answer: what it changed, in the server's words, and how far the learning has come.

export function progressLine(l: Learning): string {
  if (l.active) return "Your answers now choose the next edition’s searches.";
  const n = Math.round(l.labels);
  const need = Math.round(l.needed);
  return `${n} of ${need} answers before your answers choose the searches.`;
}

export function LessonNote(props: {
  lesson: Lesson | null;
  learning: Learning | null;
  onClose: () => void;
}) {
  const { lesson, learning, onClose } = props;
  useEffect(() => {
    if (!lesson) return;
    const t = window.setTimeout(onClose, 12_000);
    return () => window.clearTimeout(t);
  }, [lesson, onClose]);
  if (!lesson) return null;
  return (
    <div className="nv-lesson" role="status" key={lesson.received_at}>
      <span className="caps">
        Because you said “{lesson.said}” on {nice(lesson.company)}
      </span>
      <p>{lesson.change}</p>
      {learning && <span className="mono">{progressLine(learning)}</span>}
      <button type="button" className="x" onClick={onClose} aria-label="Dismiss">
        ✕
      </button>
    </div>
  );
}
