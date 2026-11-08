"""Condenses a debate case file (.docx) down to the parts that actually carry
meaning for classifying it, instead of handing an LLM the whole document.

Debate-file formatting conventions this leans on:
  - Tags (the bolded one-line claim above a piece of evidence) and cites
    (the bolded+underlined author/date line) are short, mostly-bold
    paragraphs -- kept in full.
  - Heading-styled paragraphs (section headers like "Advantage 1", "1AC",
    "Solvency") are kept in full as structural markers.
  - Inside a card's body, only the underlined and/or highlighted spans are
    what's actually read aloud in-round; everything else is cut-card filler
    that debaters themselves skip. We keep only those spans, joined with
    " ... " where we skipped non-highlighted text in between.
  - Anything else (unformatted block-quote filler) is dropped entirely.

This is a heuristic, not a guarantee -- case files aren't formatted with
perfect consistency. If a real sample file condenses poorly, the thresholds
below (BOLD_TAG_RATIO, TAG_MAX_LEN) are the first things to tune.
"""

from __future__ import annotations

import docx

BOLD_TAG_RATIO = 0.6
TAG_MAX_LEN = 500


def _is_tag_like(paragraph) -> bool:
    text = paragraph.text.strip()
    if not text or len(text) > TAG_MAX_LEN:
        return False
    total_chars = 0
    bold_chars = 0
    for run in paragraph.runs:
        run_len = len(run.text.strip())
        if run_len == 0:
            continue
        total_chars += run_len
        if run.font.bold:
            bold_chars += run_len
    if total_chars == 0:
        return False
    return (bold_chars / total_chars) >= BOLD_TAG_RATIO


def _is_marked_run(run) -> bool:
    if run.font.underline:
        return True
    highlight = run.font.highlight_color
    return highlight is not None


def _extract_marked_spans(paragraph) -> str:
    spans: list[str] = []
    buffer: list[str] = []
    for run in paragraph.runs:
        text = run.text
        if not text.strip():
            continue
        if _is_marked_run(run):
            buffer.append(text)
        else:
            if buffer:
                spans.append("".join(buffer).strip())
                buffer = []
    if buffer:
        spans.append("".join(buffer).strip())
    spans = [s for s in spans if s]
    return " ... ".join(spans)


def extract_condensed_text(docx_path: str, max_chars: int = 20000) -> str:
    document = docx.Document(docx_path)
    kept_lines: list[str] = []

    for paragraph in document.paragraphs:
        style_name = (paragraph.style.name or "").lower() if paragraph.style else ""
        text = paragraph.text.strip()
        if not text:
            continue

        if style_name.startswith("heading") or style_name == "title":
            kept_lines.append(f"## {text}")
            continue

        if _is_tag_like(paragraph):
            kept_lines.append(text)
            continue

        marked = _extract_marked_spans(paragraph)
        if marked:
            kept_lines.append(marked)

    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    text = paragraph.text.strip()
                    if not text:
                        continue
                    if _is_tag_like(paragraph):
                        kept_lines.append(text)
                    else:
                        marked = _extract_marked_spans(paragraph)
                        if marked:
                            kept_lines.append(marked)

    condensed = "\n".join(kept_lines)
    return condensed[:max_chars]
