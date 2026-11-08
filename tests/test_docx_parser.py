import docx
from docx.enum.text import WD_COLOR_INDEX

from app.docx_parser import extract_condensed_text


def test_condenses_tags_and_marked_spans_only(tmp_path):
    document = docx.Document()
    document.add_heading("1AC - Advantage 1: Climate", level=1)

    tag = document.add_paragraph()
    tag_run = tag.add_run("Warming causes extinction -- only the plan solves.")
    tag_run.bold = True

    body = document.add_paragraph()
    r1 = body.add_run("Some filler context sentence that should be dropped entirely. ")
    r1.bold = False
    r2 = body.add_run("This part is highlighted and read aloud.")
    r2.font.highlight_color = WD_COLOR_INDEX.YELLOW
    body.add_run(" More filler here that is skipped.")
    r4 = body.add_run("This part is underlined and also read.")
    r4.font.underline = True

    path = tmp_path / "sample.docx"
    document.save(str(path))

    condensed = extract_condensed_text(str(path))

    assert "1AC - Advantage 1: Climate" in condensed
    assert "Warming causes extinction" in condensed
    assert "highlighted and read aloud" in condensed
    assert "underlined and also read" in condensed
    assert "filler context sentence" not in condensed
    assert "More filler here" not in condensed
