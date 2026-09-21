from io import BytesIO
import os
from pathlib import Path

from bidi.algorithm import get_display
from pypdf import PdfReader
import pytest
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

from app.integrations.pdf.generator import PdfGenerator, _register_fonts
from app.integrations.pdf.labels import LABELS
from app.integrations.pdf.text import text_paragraph


def _sample(locale, *, comment_repeats=35):
    phrase = {
        "en": "Completed and checked at position A-201.",
        "ru": "Работа выполнена и проверена на позиции A-201.",
        "he": "העבודה הושלמה ונבדקה במיקום A-201.",
    }[locale]
    return {
        "journal": {
            "id": "qa-locale-20260915", "pdf_locale": locale,
            "title": LABELS[locale]["title"], "project_name": "QA DIMAX / בניין A",
            "project_address": "QA Address 12 / קומה 2", "developer_company": "QA Developer",
            "contact_name": "QA Contact", "status": "ARCHIVED",
            "signed_at": "2026-09-15T08:30:00Z", "signer_name": "QA SIGNER / ישראל כהן",
            "notes": "\n".join(["QA TEST ONLY <position> & notes", phrase * 10, "NOTES-END"]),
        },
        "items": [{
            "unit_label": f"A-2-{index + 200}-FR-{index:03d}",
            "door_type_name": "Fire / אש / Огнеупорная",
            "installed_at": "2026-09-14T13:12:00Z",
        } for index in range(1, 36)],
        "addon_items": [{
            "name": "QA additional work", "quantity": "2.50", "unit": "pcs",
            "done_at": "2026-09-14T13:12:00Z",
            "comment": "COMMENT-START\n" + " ".join([phrase] * comment_repeats) + "\nCOMMENT-END",
        }],
        "signature_payload": {
            "viewport": {"width": 320, "height": 120},
            "strokes": [[{"x": 20, "y": 70}, {"x": 80, "y": 30}, {"x": 200, "y": 70}]],
        },
    }


def test_all_document_languages_have_the_same_complete_label_set():
    assert set(LABELS) == {"en", "ru", "he"}
    for locale in LABELS:
        assert set(LABELS[locale]) == set(LABELS["en"])
        assert all(LABELS[locale].values())


@pytest.mark.parametrize("locale", ["en", "ru", "he"])
def test_long_document_keeps_every_position_comment_notes_and_signature(locale):
    content = PdfGenerator.journal_pdf(**_sample(locale))
    output = os.getenv("DIMAX_JOURNAL_QA_DIR")
    if output:
        folder = Path(output).resolve()
        assert folder.is_dir() and folder.name == "journal-pdf-locales"
        (folder / f"qa-journal-{locale}.pdf").write_bytes(content)
    reader = PdfReader(BytesIO(content))
    pages = [page.extract_text() for page in reader.pages]
    text = "\n".join(pages)
    fragments = []
    for page in reader.pages:
        page.extract_text(visitor_text=lambda text, *_: fragments.append(text))
    assert "QA SIGNER" in "".join(fragments)
    assert "QA DIMAX" in "".join(fragments)
    assert 3 <= len(pages) <= 6
    assert "COMMENT-START" in text and "COMMENT-END" in text
    assert "NOTES-END" in text
    assert "ישראל כהן" in text
    assert "<position> & notes" in text
    assert "14.09.2026 16:12" in text
    assert "15.09.2026 11:30" in text
    assert "15.09.2026 11:30" in pages[-1]
    assert "Asia/Jerusalem" in pages[-1]
    for index in range(1, 36):
        assert text.count(f"A-2-{index + 200}-FR-{index:03d}") == 1
    for number, page in enumerate(pages, start=1):
        assert "JR-QA-LOCAL" in page
        assert str(number) in page
        if locale != "en":
            assert "WORK ACCEPTANCE" not in page
            assert "Door / position" not in page
    if locale == "ru":
        assert "АКТ ВЫПОЛНЕННЫХ РАБОТ" in text
        assert "Приёмка застройщиком" in text
    if locale == "he":
        assert "אישור ביצוע עבודות" in text
        assert "אישור היזם" in text


@pytest.mark.parametrize("locale", ["en", "he"])
def test_oversized_work_comment_splits_inside_table_row(locale):
    sample = _sample(locale, comment_repeats=200)
    sample["items"] = []
    content = PdfGenerator.journal_pdf(**sample)
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(content)).pages)
    assert "COMMENT-START" in text and "COMMENT-END" in text
    assert "NOTES-END" in text
    assert "ישראל כהן" in text


@pytest.mark.parametrize("text", [
    "תחילת פסקה " + "בדיקת דלת A-201 הושלמה באתר. " * 15 + " סוף פסקה",
    "שורה ראשונה <בדיקה> & A-201\n" + "שורה שנייה נבדקה באתר " * 10,
], ids=["wrapped", "explicit-lines"])
def test_bidi_is_applied_after_wrapping_without_mutating_logical_lines(monkeypatch, text):
    regular, _ = _register_fonts()
    paragraph = text_paragraph(text, ParagraphStyle("QA", fontName=regular, fontSize=10, leading=14))
    paragraph.wrap(130, 1000)
    logical = paragraph.blPara
    rendered = []
    monkeypatch.setattr(Paragraph, "drawPara", lambda self, debug=0: rendered.append(self.blPara))
    paragraph.drawPara()
    paragraph.drawPara()
    assert paragraph.blPara is logical
    for visual in rendered:
        if logical.kind == 0:
            before = [" ".join(words) for _, words in logical.lines]
            after = [" ".join(words) for _, words in visual.lines]
        else:
            before = ["".join(word.text for word in line.words) for line in logical.lines]
            after = ["".join(word.text for word in line.words) for line in visual.lines]
        assert len(before) > 1
        assert after == [get_display(line, base_dir="R") for line in before]
