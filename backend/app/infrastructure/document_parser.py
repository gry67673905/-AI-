from __future__ import annotations

import io

from docx import Document
from pypdf import PdfReader


class LocalKnowledgeParser:
    def extract(self, extension: str, content: bytes) -> str:
        if extension in {".txt", ".md", ".markdown"}:
            return content.decode("utf-8")
        if extension == ".pdf":
            return "\n".join(
                page.extract_text() or ""
                for page in PdfReader(io.BytesIO(content)).pages
            )
        document = Document(io.BytesIO(content))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
