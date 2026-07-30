from __future__ import annotations

import io
import re
from pathlib import Path
from urllib.parse import urlparse

import fitz
import pytesseract
import requests
from PIL import Image

from .models import AssetRef, DocumentBlob

_MAX_DOWNLOAD_BYTES = 20_000_000


def _safe_filename(url: str, suffix: str) -> str:
    path_name = Path(urlparse(url).path).name or "asset"
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "_", path_name).strip("_")[:100] or "asset"
    if not stem.lower().endswith(suffix):
        stem += suffix
    return stem


def _download(url: str, timeout: int = 40) -> tuple[bytes, str]:
    response = requests.get(
        url,
        timeout=timeout,
        allow_redirects=True,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
            ),
            "Accept-Language": "it-IT,it;q=0.9,en;q=0.7",
        },
        stream=True,
    )
    response.raise_for_status()
    content_length = int(response.headers.get("content-length", "0") or 0)
    if content_length > _MAX_DOWNLOAD_BYTES:
        raise ValueError(f"File troppo grande ({content_length} byte)")
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_content(chunk_size=262_144):
        if not chunk:
            continue
        size += len(chunk)
        if size > _MAX_DOWNLOAD_BYTES:
            raise ValueError("File oltre il limite di download")
        chunks.append(chunk)
    return b"".join(chunks), response.headers.get("content-type", "")


def _ocr_image(image: Image.Image) -> str:
    if image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")
    # Ridimensionamento limitato: sufficiente per il testo dei volantini senza esplodere i tempi CI.
    max_side = max(image.size)
    if max_side < 1600:
        scale = 1600 / max_side
        image = image.resize((int(image.width * scale), int(image.height * scale)))
    return pytesseract.image_to_string(image, lang="ita+eng", config="--psm 6")


def extract_pdf(asset: AssetRef, raw_dir: Path, max_pages: int = 30) -> DocumentBlob:
    payload, _ = _download(asset.url)
    filename = _safe_filename(asset.url, ".pdf")
    (raw_dir / filename).write_bytes(payload)
    document = fitz.open(stream=payload, filetype="pdf")
    pages: list[str] = []
    for page_index in range(min(len(document), max_pages)):
        page = document.load_page(page_index)
        text = page.get_text("text", sort=True).strip()
        if len(text) < 80:
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
            image = Image.open(io.BytesIO(pix.tobytes("png")))
            text = _ocr_image(image).strip()
        pages.append(f"\n--- PAGINA {page_index + 1} ---\n{text}")
    return DocumentBlob(
        source_id=asset.source_id,
        store=asset.store,
        url=asset.url,
        kind="pdf",
        text="\n".join(pages),
        title=filename,
    )


def extract_image(asset: AssetRef, raw_dir: Path) -> DocumentBlob:
    payload, content_type = _download(asset.url)
    suffix = ".png"
    if "jpeg" in content_type or asset.url.lower().split("?", 1)[0].endswith((".jpg", ".jpeg")):
        suffix = ".jpg"
    elif "webp" in content_type or asset.url.lower().split("?", 1)[0].endswith(".webp"):
        suffix = ".webp"
    filename = _safe_filename(asset.url, suffix)
    (raw_dir / filename).write_bytes(payload)
    image = Image.open(io.BytesIO(payload))
    text = _ocr_image(image).strip()
    return DocumentBlob(
        source_id=asset.source_id,
        store=asset.store,
        url=asset.url,
        kind="image_ocr",
        text=text,
        title=filename,
    )


def extract_assets(
    assets: list[AssetRef],
    raw_dir: Path,
    max_assets: int = 35,
) -> tuple[list[DocumentBlob], list[str]]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    documents: list[DocumentBlob] = []
    errors: list[str] = []
    # PDF prima delle immagini: in genere contiene più pagine e testo più completo.
    ordered = sorted(assets, key=lambda item: 0 if item.kind == "pdf" else 1)
    for asset in ordered[:max_assets]:
        try:
            if asset.kind == "pdf":
                documents.append(extract_pdf(asset, raw_dir))
            elif asset.kind == "image":
                documents.append(extract_image(asset, raw_dir))
        except Exception as exc:
            errors.append(f"Asset {asset.url}: {type(exc).__name__}: {exc}")
    return documents, errors
