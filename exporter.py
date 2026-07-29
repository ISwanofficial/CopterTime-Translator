from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _export_with_word(docx_path: Path, pdf_path: Path) -> bool:
    try:
        import win32com.client
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        document = None
        try:
            document = word.Documents.Open(str(docx_path.resolve()))
            document.SaveAs(str(pdf_path.resolve()), FileFormat=17)
        finally:
            if document is not None:
                document.Close(False)
            word.Quit()
        return pdf_path.exists()
    except Exception:
        return False


def _find_soffice() -> str | None:
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    for path in [
        Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
        Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
    ]:
        if path.exists():
            return str(path)
    return None


def _export_with_libreoffice(docx_path: Path, pdf_path: Path) -> bool:
    soffice = _find_soffice()
    if not soffice:
        return False
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(docx_path.parent), str(docx_path)],
            check=True, capture_output=True, text=True, timeout=180,
        )
        return pdf_path.exists()
    except Exception:
        return False


def export_docx_to_pdf(docx_path: Path) -> Path | None:
    pdf_path = docx_path.with_suffix(".pdf")
    if _export_with_word(docx_path, pdf_path):
        return pdf_path
    if _export_with_libreoffice(docx_path, pdf_path):
        return pdf_path
    return None
