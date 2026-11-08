"""Best-effort condenser for debate case files posted as PDF instead of .docx.

PDFs don't expose underline/highlight the way .docx runs do, so this can only
reliably detect bold text (via font name) for tags/cites. Card-body "read"
spans are NOT recovered here -- if a case file is PDF-only, the condensed
text will be tags + cites only, missing evidence bodies. Prefer .docx when
available; this exists so a PDF-only upload still produces something usable
instead of failing outright.
"""

from __future__ import annotations

import pdfplumber

BOLD_HINTS = ("bold", "black", "heavy", "semibold", "-bd", "bd,")


def _is_bold_fontname(fontname: str) -> bool:
    lowered = fontname.lower()
    return any(hint in lowered for hint in BOLD_HINTS)


def extract_condensed_text(pdf_path: str, max_chars: int = 20000) -> str:
    kept_lines: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            words = page.extract_words(extra_attrs=["fontname"])
            if not words:
                continue

            lines: dict[int, list[dict]] = {}
            for word in words:
                line_key = round(word["top"])
                lines.setdefault(line_key, []).append(word)

            for _, line_words in sorted(lines.items()):
                line_words.sort(key=lambda w: w["x0"])
                text = " ".join(w["text"] for w in line_words).strip()
                if not text:
                    continue

                bold_chars = sum(len(w["text"]) for w in line_words if _is_bold_fontname(w["fontname"]))
                total_chars = sum(len(w["text"]) for w in line_words)
                if total_chars and (bold_chars / total_chars) >= 0.6:
                    kept_lines.append(text)

    condensed = "\n".join(kept_lines)
    return condensed[:max_chars]
