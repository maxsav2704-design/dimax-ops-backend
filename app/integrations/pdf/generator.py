from __future__ import annotations

from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


class PdfGenerator:
    @staticmethod
    def journal_pdf(*, journal: dict, items: list[dict]) -> bytes:
        """
        Минимально рабочий PDF.
        Потом заменим на шаблон по Lovable (HTML->PDF или нормальная верстка).
        """
        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        w, h = A4

        y = h - 40
        c.setFont("Helvetica-Bold", 14)
        c.drawString(40, y, f"Journal: {journal.get('title') or journal['id']}")
        y -= 20

        c.setFont("Helvetica", 10)
        c.drawString(40, y, f"Project: {journal.get('project_name', '')}")
        y -= 14
        c.drawString(40, y, f"Address: {journal.get('project_address', '')}")
        y -= 14

        if journal.get("signer_name"):
            c.drawString(
                40,
                y,
                f"Signed by: {journal['signer_name']} at {journal.get('signed_at', '')}",
            )
            y -= 18

        c.setFont("Helvetica-Bold", 11)
        c.drawString(40, y, "Installed doors snapshot:")
        y -= 16

        c.setFont("Helvetica", 9)
        for idx, it in enumerate(items[:45], start=1):
            line = (
                f"{idx}. {it['unit_label']} | type={it['door_type_id']} | "
                f"installed_at={it.get('installed_at')}"
            )
            c.drawString(40, y, line[:120])
            y -= 12
            if y < 60:
                c.showPage()
                y = h - 40
                c.setFont("Helvetica", 9)

        c.showPage()
        c.save()
        return buf.getvalue()
