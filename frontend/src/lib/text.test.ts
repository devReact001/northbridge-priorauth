import { describe, expect, it } from "vitest";
import { findQuoteSpans, placeholders, splitByQuotes } from "./text";
import { compact, percent, seconds } from "./format";

describe("placeholders", () => {
  it("finds bracketed blanks once each, sorted", () => {
    expect(placeholders("Dear [Ordering provider name],\n... [Date] ... [Date]")).toEqual(["[Date]", "[Ordering provider name]"]);
  });
  it("ignores ordinary brackets such as citations and digits", () => {
    expect(placeholders("see note [1] and [2024] and [x]")).toEqual([]);
  });
  it("finds nothing in a finished letter", () => {
    expect(placeholders("Sincerely, Dr. Arjun Rao")).toEqual([]);
  });
});

describe("quote highlighting", () => {
  const note = "Reports locking and catching of the right knee, worse on stairs.\nPositive McMurray   test.";

  it("locates a quote regardless of case, whitespace and line breaks", () => {
    const spans = findQuoteSpans(note, ["positive mcmurray test."]);
    expect(spans).toHaveLength(1);
    expect(note.slice(spans[0].start, spans[0].end)).toBe("Positive McMurray   test.");
  });

  it("matches curly quotes against straight ones", () => {
    const text = "Patient says “the knee locks” daily.";
    const spans = findQuoteSpans(text, ['"the knee locks"']);
    expect(text.slice(spans[0].start, spans[0].end)).toBe("“the knee locks”");
  });

  it("merges overlapping quotes and ignores quotes that are not in the text", () => {
    const spans = findQuoteSpans(note, ["locking and catching of the right knee", "right knee, worse on stairs", "not in the note at all"]);
    expect(spans).toHaveLength(1);
    expect(note.slice(spans[0].start, spans[0].end)).toBe("locking and catching of the right knee, worse on stairs");
  });

  it("splits text into plain and highlighted pieces that add back up to the original", () => {
    const pieces = splitByQuotes(note, ["locking and catching"]);
    expect(pieces.map((p) => p.marked)).toEqual([false, true, false]);
    expect(pieces.map((p) => p.text).join("")).toBe(note);
  });

  it("skips very short quotes that would highlight everything", () => {
    expect(findQuoteSpans(note, ["no", "a"])).toEqual([]);
  });

  it("chart facts (not in the note) simply do not highlight", () => {
    expect(findQuoteSpans(note, ["Observation/obs-2 (2026-03-24): McMurray test: positive"])).toEqual([]);
  });
});

describe("formatting", () => {
  it("formats durations, counts and rates", () => {
    expect(seconds(450)).toBe("450 ms");
    expect(seconds(4200)).toBe("4.2 s");
    expect(seconds(48000)).toBe("48 s");
    expect(seconds(null)).toBe("–");
    expect(compact(950)).toBe("950");
    expect(compact(4274)).toBe("4.3K");
    expect(compact(52000)).toBe("52K");
    expect(percent(0.667)).toBe("67%");
    expect(percent(null)).toBe("–");
  });
});
