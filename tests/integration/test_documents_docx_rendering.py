from __future__ import annotations

import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO

from app.modules.documents.application.service import (
    extract_placeholders,
    render_template_bytes,
)


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WORD_TEXT_TAG = f"{{{WORD_NS}}}t"


def _docx_with_document_xml(document_xml: str) -> bytes:
    out = BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/word/document.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                "</Types>"
            ),
        )
        zf.writestr(
            "_rels/.rels",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                'Target="word/document.xml"/>'
                "</Relationships>"
            ),
        )
        zf.writestr("word/document.xml", document_xml)
    return out.getvalue()


def _document_text(docx_bytes: bytes) -> str:
    with zipfile.ZipFile(BytesIO(docx_bytes)) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    return "".join(node.text or "" for node in root.iter(WORD_TEXT_TAG))


def test_docx_placeholders_can_span_word_runs() -> None:
    template = _docx_with_document_xml(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="{WORD_NS}">
  <w:body>
    <w:p>
      <w:r><w:t>Object: {{{{project.</w:t></w:r>
      <w:r><w:t>name}}}}</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t>Address: {{{{project.address}}}}</w:t></w:r>
    </w:p>
  </w:body>
</w:document>"""
    )

    assert extract_placeholders(filename="handover.docx", content=template) == [
        "project.address",
        "project.name",
    ]

    rendered, mime = render_template_bytes(
        filename="handover.docx",
        content=template,
        values={
            "project.name": "Ashdod & Tower",
            "project.address": "A < B",
        },
    )

    assert mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    text = _document_text(rendered)
    assert "Object: Ashdod & Tower" in text
    assert "Address: A < B" in text
    assert "{{project." not in text
