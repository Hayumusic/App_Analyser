from __future__ import annotations

from typing import Dict, Iterable

try:
    from PyPDF2 import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None


def extract_pdf_texts(uploaded_files) -> Dict[str, str]:
    texts = {}
    if not uploaded_files:
        return texts
    if PdfReader is None:
        raise RuntimeError("PyPDF2 is not installed. Install requirements.txt and try again.")
    for uploaded_file in uploaded_files:
        try:
            reader = PdfReader(uploaded_file)
            pages = []
            for page in reader.pages:
                pages.append(page.extract_text() or "")
            texts[getattr(uploaded_file, "name", "uploaded.pdf")] = "\n".join(pages)
        except Exception as exc:
            texts[getattr(uploaded_file, "name", "uploaded.pdf")] = f"PDF_EXTRACTION_ERROR: {exc}"
    return texts
