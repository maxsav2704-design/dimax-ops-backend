from __future__ import annotations

import os
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    CondPageBreak,
    KeepTogether,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from bidi.algorithm import get_display

from app.integrations.pdf.labels import LABELS
from app.integrations.pdf.text import text_paragraph


BRAND_INK = colors.HexColor("#111318")
BRAND_GOLD = colors.HexColor("#C99A2E")
BRAND_MUTED = colors.HexColor("#5E6572")
BRAND_LINE = colors.HexColor("#D9DDE4")
BRAND_SOFT = colors.HexColor("#F3F5F7")
BRAND_SUCCESS = colors.HexColor("#147A4B")


def _font_candidates() -> list[tuple[str, str]]:
    configured = os.getenv("DIMAX_PDF_FONT_DIR", "").strip()
    candidates: list[tuple[str, str]] = []
    if configured:
        candidates.append(
            (
                str(Path(configured) / "DejaVuSans.ttf"),
                str(Path(configured) / "DejaVuSans-Bold.ttf"),
            )
        )
    candidates.extend(
        [
            (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ),
            (
                r"C:\Windows\Fonts\arial.ttf",
                r"C:\Windows\Fonts\arialbd.ttf",
            ),
        ]
    )
    return candidates


def _register_fonts() -> tuple[str, str]:
    if "DimaxSans" in pdfmetrics.getRegisteredFontNames():
        return "DimaxSans", "DimaxSansBold"
    for regular, bold in _font_candidates():
        if Path(regular).is_file() and Path(bold).is_file():
            pdfmetrics.registerFont(TTFont("DimaxSans", regular))
            pdfmetrics.registerFont(TTFont("DimaxSansBold", bold))
            pdfmetrics.registerFontFamily(
                "DimaxSans", normal="DimaxSans", bold="DimaxSansBold",
                italic="DimaxSans", boldItalic="DimaxSansBold",
            )
            return "DimaxSans", "DimaxSansBold"
    raise RuntimeError("Journal PDF requires Unicode fonts; install DejaVu Sans or set DIMAX_PDF_FONT_DIR")


def _format_timestamp(value: Any) -> str:
    if not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        parsed = parsed.astimezone(ZoneInfo("Asia/Jerusalem"))
        return parsed.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return str(value)


class SignatureFlowable(Flowable):
    def __init__(self, payload: dict | None, *, width: float, height: float = 28 * mm):
        super().__init__()
        self.payload = payload or {}
        self.width = width
        self.height = height

    def draw(self) -> None:
        self.canv.setStrokeColor(BRAND_LINE)
        self.canv.setLineWidth(0.7)
        self.canv.roundRect(0, 0, self.width, self.height, 3 * mm, stroke=1, fill=0)

        strokes = self.payload.get("strokes")
        viewport = self.payload.get("viewport") or {}
        source_width = float(viewport.get("width") or 1)
        source_height = float(viewport.get("height") or 1)
        if not isinstance(strokes, list) or source_width <= 0 or source_height <= 0:
            return

        pad = 4 * mm
        draw_width = max(1, self.width - (pad * 2))
        draw_height = max(1, self.height - (pad * 2))
        self.canv.saveState()
        clip = self.canv.beginPath()
        clip.rect(pad, pad, draw_width, draw_height)
        self.canv.clipPath(clip, stroke=0, fill=0)
        self.canv.setStrokeColor(BRAND_INK)
        self.canv.setLineCap(1)
        self.canv.setLineJoin(1)
        self.canv.setLineWidth(1.4)
        for stroke in strokes:
            if not isinstance(stroke, list) or len(stroke) < 2:
                continue
            path = self.canv.beginPath()
            drew = False
            first_point = True
            for point in stroke:
                if not isinstance(point, dict):
                    continue
                try:
                    x = pad + (float(point["x"]) / source_width) * draw_width
                    y = pad + (1 - (float(point["y"]) / source_height)) * draw_height
                except (KeyError, TypeError, ValueError):
                    continue
                if first_point:
                    path.moveTo(x, y)
                    first_point = False
                else:
                    path.lineTo(x, y)
                drew = True
            if drew:
                self.canv.drawPath(path, stroke=1, fill=0)
        self.canv.restoreState()


def _document_table_style() -> TableStyle:
    return TableStyle(
        [
            ("BOX", (0, 0), (-1, -1), 0.6, BRAND_LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.35, BRAND_LINE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2.5 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2.5 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_INK),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_SOFT]),
        ]
    )


class PdfGenerator:
    @staticmethod
    def journal_pdf(
        *,
        journal: dict,
        items: list[dict],
        addon_items: list[dict] | None = None,
        signature_payload: dict | None = None,
    ) -> bytes:
        locale = journal.get("pdf_locale", "en")
        labels = LABELS[locale]
        rtl = locale == "he"
        regular_font, bold_font = _register_fonts()
        buffer = BytesIO()
        document = SimpleDocTemplate(
            buffer, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
            topMargin=17 * mm, bottomMargin=17 * mm,
            title=str(journal.get("title") or labels["title"]),
            author="DIMAX Operations Suite",
        )
        # SimpleDocTemplate's frame reserves 6 pt of padding on each side.
        width = document.width - 12
        body = ParagraphStyle(
            "DimaxBody", fontName=regular_font, fontSize=8.5, leading=12,
            textColor=BRAND_INK, alignment=TA_RIGHT if rtl else TA_LEFT,
            spaceShrinkage=0,
        )
        muted = ParagraphStyle(
            "DimaxMuted", parent=body, fontSize=7.5, leading=10, textColor=BRAND_MUTED,
        )
        title_style = ParagraphStyle(
            "DimaxTitle", parent=body, fontName=bold_font, fontSize=17, leading=22,
        )
        section = ParagraphStyle(
            "DimaxSection", parent=body, fontName=bold_font, fontSize=10, leading=14,
            spaceBefore=4 * mm, spaceAfter=2 * mm,
        )
        table_header = ParagraphStyle(
            "DimaxTableHeader", parent=body, fontName=bold_font,
            fontSize=8, leading=11, textColor=colors.white,
        )
        metric = ParagraphStyle("DimaxMetric", parent=body, fontName=bold_font, fontSize=12, leading=17)

        def p(value, style=body):
            return text_paragraph(value, style)

        def table(rows, widths, *, heading=False, style=None):
            total = sum(widths)
            widths = [width * column / total for column in widths]
            if rtl:
                rows = [list(reversed(row)) for row in rows]
                widths = list(reversed(widths))
            result = Table(
                rows, colWidths=widths, repeatRows=1 if heading else 0,
                splitByRow=1, splitInRow=1, hAlign="RIGHT" if rtl else "LEFT",
            )
            result.setStyle(style if style is not None else _document_table_style())
            return result

        plain_table_style = TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.6, BRAND_LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.35, BRAND_LINE),
            ("BACKGROUND", (0, 0), (-1, -1), BRAND_SOFT),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ])
        document_number = f"JR-{str(journal.get('id', ''))[:8].upper()}"
        header = table(
            [[[p("DIMAX", title_style), p("OPERATIONS SUITE", muted)],
              [p(labels["acceptance"], muted), p(document_number, metric)]]],
            [width * 0.55, width * 0.45],
            style=TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 1.2, BRAND_GOLD),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
            ]),
        )
        story: list[Any] = [
            header, Spacer(1, 5 * mm),
            p(journal.get("title") or labels["title"], title_style), Spacer(1, 3 * mm),
        ]
        metadata = [
            [p(labels[label], muted), p(journal.get(key))]
            for label, key in (
                ("project", "project_name"), ("address", "project_address"),
                ("developer", "developer_company"), ("contact", "contact_name"),
            )
        ]
        story.append(table(metadata, [width * 0.2, width * 0.8], style=plain_table_style))
        addon_items = addon_items or []
        status_key = "signed" if journal.get("signed_at") else journal.get("status", "DRAFT")
        summary = [
            [p(len(items), metric), p(labels["doors"], muted)],
            [p(len(addon_items), metric), p(labels["addons"], muted)],
            [p(labels[status_key], metric), p(labels["status"], muted)],
        ]
        story.extend([
            Spacer(1, 4 * mm),
            table([summary], [width / 3] * 3, style=plain_table_style),
            CondPageBreak(35 * mm),
            p(labels["installation"], section),
        ])
        door_rows = [[p(label, table_header) for label in
                      ("#", labels["position"], labels["type"], labels["completed"])]]
        for index, item in enumerate(items, start=1):
            door_rows.append([
                p(index), p(item.get("unit_label")), p(item.get("door_type_name")),
                p(_format_timestamp(item.get("installed_at"))),
            ])
        if items:
            story.append(table(door_rows, [10 * mm, 58 * mm, 68 * mm, 42 * mm], heading=True))
        else:
            story.append(p(labels["empty"], muted))

        if addon_items:
            story.append(CondPageBreak(35 * mm))
            story.append(p(labels["additional"], section))
            addon_rows = [[p(labels[key], table_header) for key in ("work", "quantity", "completed", "comment")]]
            units = {
                "ru": {"pcs": "шт.", "unit": "ед.", "hours": "ч.", "m2": "м²"},
                "he": {"pcs": "יח׳", "unit": "יח׳", "hours": "שעות", "m2": "מ״ר"},
            }.get(locale, {})
            for item in addon_items:
                unit = units.get(item.get("unit"), item.get("unit") or "")
                addon_rows.append([
                    p(item.get("name")), p(f"{item.get('quantity', '')} {unit}"),
                    p(_format_timestamp(item.get("done_at"))), p(item.get("comment")),
                ])
            story.append(table(addon_rows, [46 * mm, 27 * mm, 42 * mm, 63 * mm], heading=True))

        if journal.get("notes"):
            story.extend([CondPageBreak(25 * mm), p(labels["notes"], section), p(journal["notes"])])

        if journal.get("signed_at"):
            signature_details = table(
                [[p(labels["signer"], muted), p(journal.get("signer_name"))],
                 [p(labels["signed_at"], muted), p(_format_timestamp(journal["signed_at"]))]],
                [width * 0.2, width * 0.8], style=plain_table_style,
            )
            story.append(KeepTogether([
                p(labels["approval"], section), signature_details, Spacer(1, 3 * mm),
                SignatureFlowable(signature_payload, width=width),
                Spacer(1, 5 * mm), p(labels["footer"], muted),
            ]))
        else:
            story.extend([Spacer(1, 5 * mm), p(labels["footer"], muted)])

        def draw_page(canvas, doc) -> None:
            canvas.saveState()
            canvas.setStrokeColor(BRAND_GOLD)
            canvas.setLineWidth(0.8)
            canvas.line(16 * mm, 11 * mm, A4[0] - 16 * mm, 11 * mm)
            canvas.setFont(regular_font, 7)
            canvas.setFillColor(BRAND_MUTED)
            canvas.drawString(16 * mm, 7 * mm, f"DIMAX | {document_number}")
            page_label = get_display(f"{labels['page']} {doc.page}")
            canvas.drawRightString(A4[0] - 16 * mm, 7 * mm, page_label)
            canvas.restoreState()

        document.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
        return buffer.getvalue()
