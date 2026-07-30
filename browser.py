from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

from .models import AssetRef, CollectionResult, DocumentBlob, SourceDefinition

_LINK_KEYWORDS = (
    "offert",
    "promoz",
    "volantin",
    "catalog",
    "sconto",
    "super-fresche",
    "colazione",
    "bevande",
    "acqua",
    "latticini",
)
_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".avif")


def _safe_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "_", value)
    return value.strip("_")[:120] or "document"


def _host_allowed(url: str, allowed_domains: Iterable[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == domain.lower() or host.endswith("." + domain.lower()) for domain in allowed_domains)


def _asset_kind(url: str, content_type: str = "") -> str | None:
    clean = url.lower().split("?", 1)[0]
    content_type = content_type.lower()
    if clean.endswith(".pdf") or "application/pdf" in content_type:
        return "pdf"
    if clean.endswith(_IMAGE_EXTENSIONS) or content_type.startswith("image/"):
        return "image"
    return None


def _click_first_text(page: Page, candidates: list[str]) -> bool:
    for text in candidates:
        patterns = [
            page.get_by_role("button", name=re.compile(re.escape(text), re.I)),
            page.get_by_role("link", name=re.compile(re.escape(text), re.I)),
            page.get_by_text(re.compile(rf"^\s*{re.escape(text)}\s*$", re.I)),
        ]
        for locator in patterns:
            try:
                if locator.count() and locator.first.is_visible(timeout=800):
                    locator.first.click(timeout=2500)
                    page.wait_for_timeout(900)
                    return True
            except Exception:
                continue
    return False


def _accept_cookies(page: Page) -> None:
    _click_first_text(
        page,
        [
            "Accetta tutti",
            "Accetta tutto",
            "Accetta",
            "Consenti tutti",
            "Ho capito",
            "Continua senza accettare",
        ],
    )


def _select_visible_option(page: Page, wanted: str) -> bool:
    selects = page.locator("select")
    for idx in range(selects.count()):
        select = selects.nth(idx)
        try:
            options = select.locator("option").all_inner_texts()
        except Exception:
            continue
        best = next((option for option in options if option.strip().casefold() == wanted.casefold()), None)
        if best is None:
            best = next((option for option in options if wanted.casefold() in option.casefold()), None)
        if not best:
            continue
        try:
            select.select_option(label=best)
            page.wait_for_timeout(1300)
            return True
        except Exception:
            continue
    return False


def _fill_store_search(page: Page, query: str) -> bool:
    inputs = page.locator("input")
    preferred: list[int] = []
    fallback: list[int] = []
    for idx in range(inputs.count()):
        locator = inputs.nth(idx)
        try:
            input_type = (locator.get_attribute("type") or "text").lower()
            placeholder = (locator.get_attribute("placeholder") or "").casefold()
            if input_type not in {"text", "search", ""} or not locator.is_visible(timeout=400):
                continue
            if any(token in placeholder for token in ("cap", "citt", "localit", "negoz", "indirizzo", "cerca")):
                preferred.append(idx)
            else:
                fallback.append(idx)
        except Exception:
            continue
    for idx in preferred + fallback:
        locator = inputs.nth(idx)
        try:
            locator.fill(query, timeout=2000)
            page.wait_for_timeout(1600)
            return True
        except Exception:
            continue
    return False


def _perform_interaction(page: Page, interaction: dict) -> None:
    interaction_type = str(interaction.get("type", "")).lower()
    if interaction_type == "selects":
        for wanted in interaction.get("selections", []):
            _select_visible_option(page, str(wanted))
        _click_first_text(page, [str(x) for x in interaction.get("click_texts", [])])
    elif interaction_type == "search":
        query = str(interaction.get("query", "")).strip()
        if query:
            _fill_store_search(page, query)
            _click_first_text(page, [str(x) for x in interaction.get("suggestion_texts", [])])
            _click_first_text(page, [str(x) for x in interaction.get("click_texts", [])])
            try:
                page.keyboard.press("Enter")
                page.wait_for_timeout(1200)
            except Exception:
                pass
    elif interaction_type == "click":
        _click_first_text(page, [str(x) for x in interaction.get("click_texts", [])])


def _extract_page_payload(page: Page) -> tuple[str, str, list[str], list[str]]:
    title = page.title()
    try:
        body = page.locator("body").inner_text(timeout=8000)
    except Exception:
        body = ""
    links = page.eval_on_selector_all(
        "a[href]",
        "els => els.map(e => ({href: e.href, text: (e.innerText || e.textContent || '').trim()}))",
    )
    image_rows = page.eval_on_selector_all(
        "img",
        "els => els.map(e => ({src: e.currentSrc || e.src || '', w: e.naturalWidth || 0, h: e.naturalHeight || 0, alt: e.alt || ''}))",
    )
    candidate_links: list[str] = []
    image_urls: list[str] = []
    for row in links:
        href = str(row.get("href", ""))
        text = str(row.get("text", "")).casefold()
        combined = f"{href.casefold()} {text}"
        if any(keyword in combined for keyword in _LINK_KEYWORDS) or href.lower().split("?", 1)[0].endswith(".pdf"):
            candidate_links.append(href)
    for row in image_rows:
        src = str(row.get("src", ""))
        width = int(row.get("w", 0) or 0)
        height = int(row.get("h", 0) or 0)
        if src and width >= 450 and height >= 300:
            image_urls.append(src)
    return title, body, candidate_links, image_urls


def collect_source(
    browser: Browser,
    source: SourceDefinition,
    raw_dir: Path,
    timeout_ms: int = 45_000,
) -> CollectionResult:
    result = CollectionResult(source_id=source.id, store=source.store)
    source_raw = raw_dir / source.id
    source_raw.mkdir(parents=True, exist_ok=True)

    context: BrowserContext = browser.new_context(
        locale="it-IT",
        timezone_id="Europe/Rome",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
        ),
        viewport={"width": 1440, "height": 1000},
    )
    context.set_default_timeout(timeout_ms)
    page = context.new_page()
    network_docs: list[DocumentBlob] = []
    network_assets: set[tuple[str, str]] = set()

    def on_response(response) -> None:
        try:
            content_type = response.headers.get("content-type", "")
            asset_kind = _asset_kind(response.url, content_type)
            if asset_kind and _host_allowed(response.url, source.allowed_domains):
                network_assets.add((response.url, asset_kind))
            if "json" not in content_type.lower() or not _host_allowed(response.url, source.allowed_domains):
                return
            body = response.body()
            if not body or len(body) > 3_000_000:
                return
            decoded = body.decode("utf-8", errors="replace")
            try:
                decoded = json.dumps(json.loads(decoded), ensure_ascii=False)
            except json.JSONDecodeError:
                pass
            network_docs.append(
                DocumentBlob(
                    source_id=source.id,
                    store=source.store,
                    url=response.url,
                    kind="json",
                    text=decoded,
                    title="Risposta JSON",
                )
            )
        except Exception:
            return

    page.on("response", on_response)
    queue = list(source.start_urls)
    visited: set[str] = set()
    queued: set[str] = set(queue)
    image_assets: set[str] = set()

    while queue and len(visited) < source.max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        if not _host_allowed(url, source.allowed_domains):
            continue
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(1800)
            _accept_cookies(page)
            if len(visited) == 0:
                _perform_interaction(page, source.interaction)
                page.wait_for_timeout(1800)
            title, body, candidate_links, images = _extract_page_payload(page)
            final_url = page.url
            visited.add(final_url)
            result.visited_urls.append(final_url)
            result.documents.append(
                DocumentBlob(
                    source_id=source.id,
                    store=source.store,
                    url=final_url,
                    kind="html",
                    text=body,
                    title=title,
                )
            )
            snapshot = source_raw / f"{len(visited):02d}_{_safe_name(title or final_url)}.txt"
            snapshot.write_text(f"URL: {final_url}\nTITLE: {title}\n\n{body}", encoding="utf-8")

            for href in candidate_links:
                absolute = urljoin(final_url, href)
                kind = _asset_kind(absolute)
                if kind:
                    network_assets.add((absolute, kind))
                elif (
                    absolute not in visited
                    and absolute not in queued
                    and _host_allowed(absolute, source.allowed_domains)
                ):
                    queue.append(absolute)
                    queued.add(absolute)
            for image_url in images:
                if _host_allowed(image_url, source.allowed_domains):
                    image_assets.add(image_url)
        except PlaywrightTimeoutError as exc:
            result.errors.append(f"Timeout su {url}: {exc}")
        except Exception as exc:
            result.errors.append(f"Errore su {url}: {type(exc).__name__}: {exc}")

    result.documents.extend(network_docs)
    for url, kind in sorted(network_assets):
        result.assets.append(AssetRef(source.id, source.store, url, kind))
    for url in sorted(image_assets)[: source.max_images]:
        result.assets.append(AssetRef(source.id, source.store, url, "image"))

    # Rimuove duplicati mantenendo il primo elemento.
    unique_assets: dict[tuple[str, str], AssetRef] = {}
    for asset in result.assets:
        unique_assets.setdefault((asset.url, asset.kind), asset)
    result.assets = list(unique_assets.values())

    try:
        context.close()
    except Exception:
        pass
    return result
