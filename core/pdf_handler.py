"""
core/pdf_handler.py — PDF merge and cleanup utilities.
Same as NestJS mergePdfs() and deleteAllFiles().
"""
import logging
from pathlib import Path
from typing import Optional
from pypdf import PdfWriter, PdfReader

logger = logging.getLogger(__name__)


def merge_pdfs(folder_path: Path, output_filename: str) -> Optional[Path]:
    """
    Merge all PDFs in a folder into one file.
    Same as NestJS mergePdfs().
    """
    try:
        writer    = PdfWriter()
        pdf_files = sorted(
            [f for f in folder_path.iterdir() if f.suffix == ".pdf"],
            key=lambda f: int(
                "".join(filter(str.isdigit, f.stem)) or "0"
            ),
        )

        if not pdf_files:
            logger.warning("[PDFHandler] No PDFs found in: %s", folder_path)
            return None

        for pdf_file in pdf_files:
            try:
                reader = PdfReader(str(pdf_file))
                for page in reader.pages:
                    writer.add_page(page)
                logger.info("[PDFHandler] Merged: %s", pdf_file.name)
            except Exception as e:
                logger.error(
                    "[PDFHandler] Error merging %s: %s", pdf_file.name, e
                )

        output_path = folder_path / output_filename
        with open(output_path, "wb") as f:
            writer.write(f)

        logger.info("[PDFHandler] ✓ Merged PDF saved: %s", output_path)
        return output_path

    except Exception as e:
        logger.error("[PDFHandler] Merge failed: %s", e)
        return None


def delete_all_pdfs(folder_path: Path) -> None:
    """
    Delete all PDFs in a folder.
    Same as NestJS deleteAllFiles().
    """
    try:
        if not folder_path.exists():
            return
        for f in folder_path.iterdir():
            if f.suffix in (".pdf", ".png"):
                f.unlink(missing_ok=True)
                logger.info("[PDFHandler] Deleted: %s", f.name)
    except Exception as e:
        logger.error("[PDFHandler] Cleanup failed: %s", e)


def get_file_size_mb(file_path: Path) -> str:
    """Return file size as formatted string e.g. '1.23 MB'"""
    try:
        size_bytes = file_path.stat().st_size
        size_mb    = round(size_bytes / (1024 * 1024), 2)
        return f"{size_mb} MB"
    except Exception:
        return "0 MB"