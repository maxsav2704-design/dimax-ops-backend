"""Plain-text paragraphs: ReportLab wraps logical text; python-bidi draws each line."""
from copy import copy
from html import escape

from bidi.algorithm import get_base_level, get_display
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph


class BidiParagraph(Paragraph):
    def drawPara(self, debug=0):
        logical = self.blPara
        visual = copy(logical)
        base = self.style.bidiBaseDir
        if logical.kind == 0:
            visual.lines = [
                (space, get_display(" ".join(words), base_dir=base).split(" "))
                for space, words in logical.lines
            ]
        else:
            visual.lines = []
            for line in logical.lines:
                rendered = copy(line)
                if line.words:
                    fragment = copy(line.words[0])
                    fragment.text = get_display(
                        "".join(word.text for word in line.words), base_dir=base
                    )
                    rendered.words = [fragment]
                visual.lines.append(rendered)
        # Keep logical lines intact for table/page splitting and repeated wrapping.
        self.blPara = visual
        try:
            super().drawPara(debug)
        finally:
            self.blPara = logical


def text_paragraph(value, style: ParagraphStyle) -> BidiParagraph:
    text = str(value if value is not None else "").strip() or "-"
    paragraph_style = ParagraphStyle(
        style.name + "Plain", parent=style,
        bidiBaseDir="R" if get_base_level(text) else "L",
    )
    return BidiParagraph(escape(text).replace("\n", "<br/>"), paragraph_style)
