"""Turn a policy PDF into section-level chunks.

Real payer PDFs are structured documents, so we chunk by section, not by fixed size.
Headings are detected from the PDF itself (bold font + a section number), which is far more
reliable than guessing from line text. Every chunk keeps its policy id, section number and
page so retrieval results can be cited exactly.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

TITLE_RE = re.compile(r"^(MP-[A-Z]+-\d{3})\s+(.+)$")
SECTION_RE = re.compile(r"^(\d+(?:\.\d+)?)\s+(\S.*)$")
FOOTER_RE = re.compile(r"^Fictional policy for portfolio use.*Page \d+$")
MAX_CHARS = 1200


@dataclass
class Chunk:
    policy_id: str
    policy_title: str
    section: str
    heading: str
    page: int
    text: str  # what gets embedded and searched: includes a context header

    @property
    def key(self) -> tuple[str, str]:
        return (self.policy_id, self.section)


def _is_bold(chars) -> bool:
    if not chars:
        return False
    return sum("bold" in c.get("fontname", "").lower() for c in chars) / len(chars) > 0.6


def _split_long(body: str, max_chars: int = MAX_CHARS) -> list[str]:
    if len(body) <= max_chars:
        return [body]
    parts, current = [], ""
    for sentence in re.split(r"(?<=[.;:])\s+", body):
        if current and len(current) + len(sentence) + 1 > max_chars:
            parts.append(current.strip())
            current = ""
        current += sentence + " "
    if current.strip():
        parts.append(current.strip())
    return parts


def chunk_pdf(path: Path) -> list[Chunk]:
    policy_id, policy_title = Path(path).stem, Path(path).stem
    sections: list[dict] = []
    current = None

    with pdfplumber.open(str(path)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for line in page.extract_text_lines(return_chars=True):
                text = line["text"].strip()
                if not text or FOOTER_RE.match(text):
                    continue
                bold = _is_bold(line["chars"])
                if bold and (m := TITLE_RE.match(text)):
                    policy_id, policy_title = m.group(1), m.group(2)
                elif bold and (m := SECTION_RE.match(text)):
                    current = {"section": m.group(1), "heading": m.group(2), "page": page_no, "lines": []}
                    sections.append(current)
                elif current is not None:
                    current["lines"].append(text)
                elif bold:
                    policy_title += " " + text  # long titles wrap onto a second bold line

    chunks: list[Chunk] = []
    for sec in sections:
        body = " ".join(sec["lines"]).replace("• ", "- ")
        header = f"{policy_id} {policy_title} | Section {sec['section']} {sec['heading']}"
        for part in _split_long(body):
            chunks.append(
                Chunk(policy_id, policy_title, sec["section"], sec["heading"], sec["page"], f"{header}\n{part}")
            )
    return chunks


def chunk_directory(pdf_dir: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for pdf in sorted(Path(pdf_dir).glob("*.pdf")):
        chunks.extend(chunk_pdf(pdf))
    return chunks
