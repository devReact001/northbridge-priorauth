import { splitByQuotes } from "@/lib/text";

/** The clinical note with every quote the assessment relied on highlighted. */
export function NoteViewer({ note, quotes }: { note: string; quotes: string[] }) {
  const pieces = splitByQuotes(note, quotes);
  return (
    <pre className="max-h-[28rem] overflow-auto whitespace-pre-wrap rounded-lg bg-surface-2 p-3 font-mono text-[13px] leading-relaxed text-ink">
      {pieces.map((p, i) =>
        p.marked ? (
          <mark key={i} className="quote">
            {p.text}
          </mark>
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </pre>
  );
}
