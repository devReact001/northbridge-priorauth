"""Render the fictional payer policies in policies/src/*.md to policies/pdf/*.pdf.

Requires reportlab (pip install -r backend/requirements-rag.txt).
Source format: '# title', '## number Heading', '- bullet', blank line = new paragraph.

Run from the project root:
    python scripts/make_policy_pdfs.py
"""

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "policies" / "src"
OUT = ROOT / "policies" / "pdf"

FOOTER = "Fictional policy for portfolio use. Not clinical guidance. Page {n}"


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontName="Helvetica-Bold", fontSize=18,
                                alignment=TA_LEFT, spaceAfter=14),
        "h": ParagraphStyle("h", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12,
                            spaceBefore=12, spaceAfter=4),
        "p": ParagraphStyle("p", parent=base["BodyText"], fontName="Helvetica", fontSize=10.5, leading=14),
    }


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.drawString(inch, 0.6 * inch, FOOTER.format(n=doc.page))
    canvas.restoreState()


def _flush_bullets(story, bullets, styles):
    if bullets:
        items = [ListItem(Paragraph(escape(b), styles["p"]), leftIndent=14) for b in bullets]
        story.append(ListFlowable(items, bulletType="bullet", start="-", leftIndent=14))
        bullets.clear()


def render(md_path: Path) -> Path:
    styles = _styles()
    story, bullets, para = [], [], []

    def flush_para():
        if para:
            story.append(Paragraph(escape(" ".join(para)), styles["p"]))
            story.append(Spacer(1, 4))
            para.clear()

    for raw in md_path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("# "):
            story.append(Paragraph(escape(line[2:]), styles["title"]))
        elif line.startswith("## "):
            flush_para()
            _flush_bullets(story, bullets, styles)
            story.append(Paragraph(escape(line[3:]), styles["h"]))
        elif line.startswith("- "):
            flush_para()
            bullets.append(line[2:])
        elif not line:
            flush_para()
            _flush_bullets(story, bullets, styles)
        else:
            _flush_bullets(story, bullets, styles)
            para.append(line)
    flush_para()
    _flush_bullets(story, bullets, styles)

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / f"{md_path.stem}.pdf"
    doc = SimpleDocTemplate(str(out_path), pagesize=letter, leftMargin=inch, rightMargin=inch,
                            topMargin=inch, bottomMargin=inch, title=md_path.stem,
                            author="Meridian Health Plan (fictional)")
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return out_path


if __name__ == "__main__":
    for md in sorted(SRC.glob("*.md")):
        print("wrote", render(md))
