"""
PDF to Images — Converts PDF pages to compressed JPEG byte arrays for vision model input.

Renders each page at a configurable DPI, compresses to JPEG within a size budget,
and returns the raw bytes ready to be passed as image content blocks to a multimodal model.

Adapted from the BADGERS pdf_to_images_converter Lambda pattern.

Usage:
    from utils.pdf_to_images import pdf_to_page_images

    pages = pdf_to_page_images("contract.pdf", dpi=150)
    # pages = [PageImage(page_number=1, image_bytes=b"...", format="jpeg"), ...]
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

# Disable PIL decompression bomb guard — large contract pages at high DPI
# exceed the default 178MP limit. We trust our own input.
Image.MAX_IMAGE_PIXELS = None

from pdf2image import convert_from_path

logger = logging.getLogger(__name__)


@dataclass
class PageImage:
    """A single rendered PDF page."""

    page_number: int
    image_bytes: bytes
    format: str = "jpeg"


def pdf_to_page_images(
    pdf_path: str | Path,
    dpi: int = 128,
    max_size_mb: float = 3.5,
    first_page: int | None = None,
    last_page: int | None = None,
) -> list[PageImage]:
    """Convert PDF pages to compressed JPEG images.

    Args:
        pdf_path: Path to the PDF file.
        dpi: Render resolution. 128 matches the BADGERS Lambda default.
        max_size_mb: Max JPEG size per page in MB. Quality steps down to fit.
        first_page: Start page (1-indexed, inclusive). None = first page.
        last_page: End page (1-indexed, inclusive). None = last page.

    Returns:
        List of PageImage objects with JPEG bytes for each page.
    """
    kwargs: dict = {"dpi": dpi, "fmt": "jpeg"}
    if first_page is not None:
        kwargs["first_page"] = first_page
    if last_page is not None:
        kwargs["last_page"] = last_page

    pil_images = convert_from_path(str(pdf_path), **kwargs)

    max_size_bytes = int(max_size_mb * 1024 * 1024)
    pages: list[PageImage] = []
    start = first_page or 1

    for i, img in enumerate(pil_images):
        page_num = start + i

        # Ensure RGB for JPEG
        if img.mode != "RGB":
            img = img.convert("RGB")

        # Bedrock Converse API caps image dimensions at 8000px per side
        max_dim = 8000
        w, h = img.size
        if w > max_dim or h > max_dim:
            scale = min(max_dim / w, max_dim / h)
            new_w, new_h = int(w * scale), int(h * scale)
            img = img.resize(
                (new_w, new_h),
                Image.Resampling.LANCZOS,
            )
            logger.info("Page %d: resized %dx%d → %dx%d", page_num, w, h, new_w, new_h)

        # Compress: step quality down, then downscale if still too big.
        quality_levels = [85, 75, 65, 55, 45, 35, 25, 15]
        buf = io.BytesIO()
        size = 0
        fitted = False

        for _attempt in range(10):
            for q in quality_levels:
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=q, optimize=True)
                size = buf.tell()
                if size <= max_size_bytes:
                    quality = q
                    fitted = True
                    break
            if fitted:
                break
            # Downscale by 25% and retry all quality levels
            w, h = img.size
            new_w, new_h = int(w * 0.75), int(h * 0.75)
            logger.info(
                "Page %d: %.1f KB at quality %d, downscaling to %dx%d",
                page_num,
                size / 1024,
                quality_levels[-1],
                new_w,
                new_h,
            )
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        logger.info(
            "Page %d: quality=%d, size=%.1f KB",
            page_num,
            quality_levels[0] if not fitted else quality,
            size / 1024,
        )

        pages.append(
            PageImage(
                page_number=page_num,
                image_bytes=buf.getvalue(),
                format="jpeg",
            )
        )

    return pages
