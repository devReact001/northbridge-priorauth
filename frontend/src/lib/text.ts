// Text helpers with no React in them, so they are unit-tested on their own.

/** Bracketed blanks a draft leaves for facts the system does not have, e.g. [Ordering provider name].
 *  Same rule as the backend (workflow/dispatch.py), which is the authority; this only warns early. */
const PLACEHOLDER = /\[[A-Za-z][A-Za-z .'/-]{2,60}\]/g;

export function placeholders(text: string): string[] {
  return Array.from(new Set(text.match(PLACEHOLDER) ?? [])).sort();
}

function fold(ch: string): string {
  if (/\s/.test(ch)) return " ";
  if (ch === "‘" || ch === "’") return "'";
  if (ch === "“" || ch === "”") return '"';
  return ch.toLowerCase();
}

/** Lowercase, straighten quotes and collapse whitespace, remembering where each kept character came from. */
function normalize(text: string): { norm: string; map: number[] } {
  let norm = "";
  const map: number[] = [];
  for (let i = 0; i < text.length; i++) {
    const ch = fold(text[i]);
    if (ch === " " && (norm.length === 0 || norm[norm.length - 1] === " ")) continue;
    norm += ch;
    map.push(i);
  }
  return { norm, map };
}

export interface Span {
  start: number;
  end: number;
}

/** Character ranges of `text` covered by any of the quotes, merged so they never overlap.
 *  Matching ignores case, quote style and runs of whitespace, as the backend's quote check does. */
export function findQuoteSpans(text: string, quotes: string[]): Span[] {
  const { norm, map } = normalize(text);
  const found: Span[] = [];
  for (const quote of quotes) {
    const q = normalize(quote).norm.trim();
    if (q.length < 4) continue;
    let from = 0;
    for (;;) {
      const at = norm.indexOf(q, from);
      if (at === -1) break;
      found.push({ start: map[at], end: map[at + q.length - 1] + 1 });
      from = at + q.length;
    }
  }
  found.sort((a, b) => a.start - b.start || b.end - a.end);
  const merged: Span[] = [];
  for (const s of found) {
    const last = merged[merged.length - 1];
    if (last && s.start <= last.end) last.end = Math.max(last.end, s.end);
    else merged.push({ ...s });
  }
  return merged;
}

export interface Piece {
  text: string;
  marked: boolean;
}

/** Split `text` into alternating plain and highlighted pieces. */
export function splitByQuotes(text: string, quotes: string[]): Piece[] {
  const pieces: Piece[] = [];
  let at = 0;
  for (const s of findQuoteSpans(text, quotes)) {
    if (s.start > at) pieces.push({ text: text.slice(at, s.start), marked: false });
    pieces.push({ text: text.slice(s.start, s.end), marked: true });
    at = s.end;
  }
  if (at < text.length) pieces.push({ text: text.slice(at), marked: false });
  return pieces;
}
