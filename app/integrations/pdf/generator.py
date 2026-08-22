from __future__ import annotations

import os
from datetime import datetime
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

try:
    from bidi.algorithm import get_display
except ImportError:  # pragma: no cover - compatibility fallback
    get_display = None


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
            return "DimaxSans", "DimaxSansBold"
    return "Helvetica", "Helvetica-Bold"


def _display_text(value: Any) -> str:
    text = str(value or "").strip()
    if get_display is not None and any("\u0590" <= char <= "\u05FF" for char in text):
        text = get_display(text)
    return escape(text)


def _format_timestamp(value: Any) -> str:
    if not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
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
        regular_font, bold_font = _register_fonts()
        buffer = BytesIO()
        document = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=16 * mm,
            rightMargin=16 * mm,
            topMargin=17 * mm,
            bottomMargin=16 * mm,
            title=str(journal.get("title") or "DIMAX work acceptance"),
            author="DIMAX Operations Suite",
        )
        styles = getSampleStyleSheet()
        body = ParagraphStyle(
            "DimaxBody",
            parent=styles["BodyText"],
            fontName=regular_font,
            fontSize=8.5,
            leading=12,
            textColor=BRAND_INK,
            alignment=TA_LEFT,
        )
        muted = ParagraphStyle(
            "DimaxMuted",
            parent=body,
            fontSize=7.5,
            leading=10,
            textColor=BRAND_MUTED,
        )
        title_style = ParagraphStyle(
            "DimaxTitle",
            parent=body,
            fontName=bold_font,
            fontSize=18,
            leading=22,
        )
        section_style = ParagraphStyle(
            "DimaxSection",
            parent=body,
            fontName=bold_font,
            fontSize=9.5,
            leading=13,
            textColor=BRAND_INK,
            spaceBefore=4 * mm,
            spaceAfter=2 * mm,
        )
        table_header = ParagraphStyle(
            "DimaxTableHeader",
            parent=body,
            fontName=bold_font,
            fontSize=7.5,
            leading=9,
            textColor=colors.white,
        )

        story: list[Any] = []
        document_number = f"JR-{str(journal.get('id', ''))[:8].upper()}"
        header = Table(
            [
                [
                    Paragraph("<b>DIMAX</b><br/><font size='7'>OPERATIONS SUITE</font>", title_style),
                    Paragraph(
                        f"<font color='#5E6572'>WORK ACCEPTANCE</font><br/><b>{document_number}</b>",
                        body,
                    ),
                ]
            ],
            colWidths=[120 * mm, 42 * mm],
        )
        header.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                    ("LINEBELOW", (0, 0), (-1, -1), 1.2, BRAND_GOLD),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
                ]
            )
        )
        story.extend([header, Spacer(1, 6 * mm)])
        story.append(Paragraph(_display_text(journal.get("title") or "Completed installation works"), title_style))
        story.append(Spacer(1, 3 * mm))

        project_rows = [
            [Paragraph("Project", muted), Paragraph(_display_text(journal.get("project_name")) or "-", body)],
            [Paragraph("Address", muted), Paragraph(_display_text(journal.get("project_address")) or "-", body)],
            [Paragraph("Developer", muted), Paragraph(_display_text(journal.get("developer_company")) or "-", body)],
            [Paragraph("Contact", muted), Paragraph(_display_text(journal.get("contact_name")) or "-", body)],
        ]
        project_table = Table(project_rows, colWidths=[30 * mm, 132 * mm])
        project_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), BRAND_SOFT),
                    ("BOX", (0, 0), (-1, -1), 0.6, BRAND_LINE),
                    ("INNERGRID", (0, 0), (-1, -1), 0.35, BRAND_LINE),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
                    ("TOPPADDING", (0, 0), (-1, -1), 2.2 * mm),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2 * mm),
                ]
            )
        )
        story.append(project_table)

        addon_items = addon_items or []
        summary = Table(
            [
                [
                    Paragraph(f"<b>{len(items)}</b><br/><font color='#5E6572'>Installed doors</font>", body),
                    Paragraph(f"<b>{len(addon_items)}</b><br/><font color='#5E6572'>Additional works</font>", body),
                    Paragraph(
                        f"<b>{_display_text(journal.get('status') or 'DRAFT')}</b><br/><font color='#5E6572'>Document status</font>",
                        body,
                    ),
                ]
            ],
            colWidths=[54 * mm, 54 * mm, 54 * mm],
        )
        summary.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, BRAND_LINE),
                    ("INNERGRID", (0, 0), (-1, -1), 0.35, BRAND_LINE),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                    ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
                ]
            )
        )
        story.extend([Spacer(1, 4 * mm), summary])

        story.append(Paragraph("Completed door installation", section_style))
        door_rows: list[list[Any]] = [
            [
                Paragraph("#", table_header),
                Paragraph("Door / position", table_header),
                Paragraph("Type", table_header),
                Paragraph("Completed", table_header),
            ]
        ]
        for index, item in enumerate(items, start=1):
            door_rows.append(
                [
                    Paragraph(str(index), body),
                    Paragraph(_display_text(item.get("unit_label")) or "-", body),
                    Paragraph(_display_text(item.get("door_type_name")) or "-", body),
                    Paragraph(_display_text(_format_timestamp(item.get("installed_at"))), body),
                ]
            )
        empty_door_snapshot = len(door_rows) == 1
        if empty_door_snapshot:
            door_rows.append(["", Paragraph("No completed doors in this snapshot.", muted), "", ""])
        door_table = Table(door_rows, colWidths=[10 * mm, 54 * mm, 59 * mm, 39 * mm], repeatRows=1)
        door_style = _document_table_style()
        if empty_door_snapshot:
            door_style.add("SPAN", (1, 1), (-1, 1))
        door_table.setStyle(door_style)
        story.append(door_table)

        if addon_items:
            story.append(Paragraph("Completed additional works", section_style))
            addon_rows: list[list[Any]] = [
                [
                    Paragraph("Work", table_header),
                    Paragraph("Quantity", table_header),
                    Paragraph("Completed", table_header),
                    Paragraph("Comment", table_header),
                ]
            ]
            for item in addon_items:
                addon_rows.append(
                    [
                        Paragraph(_display_text(item.get("name")), body),
                        Paragraph(f"{_display_text(item.get('quantity'))} {_display_text(item.get('unit'))}", body),
                        Paragraph(_display_text(_format_timestamp(item.get("done_at"))), body),
                        Paragraph(_display_text(item.get("comment")) or "-", body),
                    ]
                )
            addon_table = Table(addon_rows, colWidths=[50 * mm, 30 * mm, 38 * mm, 44 * mm], repeatRows=1)
            addon_table.setStyle(_document_table_style())
            story.append(addon_table)

        if journal.get("signed_at"):
            signature_block = KeepTogether(
                [
                    Paragraph("Developer acceptance", section_style),
                    Table(
                        [
                            [
                                Paragraph("Signed by", muted),
                                Paragraph(_display_text(journal.get("signer_name")) or "-", body),
                                Paragraph("Signed at", muted),
                                Paragraph(_display_text(_format_timestamp(journal.get("signed_at"))), body),
                            ]
                        ],
                        colWidths=[24 * mm, 57 * mm, 24 * mm, 57 * mm],
                        style=TableStyle(
                            [
                                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EAF5EF")),
                                ("BOX", (0, 0), (-1, -1), 0.7, BRAND_SUCCESS),
                                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
                                ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
                            ]
                        ),
                    ),
                    Spacer(1, 3 * mm),
                    SignatureFlowable(signature_payload, width=162 * mm),
                ]
            )
            story.append(signature_block)

        story.extend(
            [
                Spacer(1, 5 * mm),
                Paragraph(
                    "This document records the completed installation work captured in DIMAX Operations Suite. "
                    "The signed PDF is distributed to the developer and DIMAX administration.",
                    muted,
                ),
            ]
        )

        def draw_page(canvas, doc) -> None:
            canvas.saveState()
            canvas.setStrokeColor(BRAND_GOLD)
            canvas.setLineWidth(0.8)
            canvas.line(16 * mm, 10 * mm, A4[0] - 16 * mm, 10 * mm)
            canvas.setFont(regular_font, 7)
            canvas.setFillColor(BRAND_MUTED)
            canvas.drawString(16 * mm, 6 * mm, "DIMAX Operations Suite")
            canvas.drawRightString(A4[0] - 16 * mm, 6 * mm, f"Page {doc.page}")
            canvas.restoreState()

        document.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
        return buffer.getvalue()
