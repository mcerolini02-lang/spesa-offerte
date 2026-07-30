from __future__ import annotations

import math
import re
import statistics
import unicodedata
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Iterable

from dateutil.relativedelta import relativedelta

from .models import DocumentBlob, Offer, ProductDefinition

_PRICE_PATTERNS = [
    re.compile(r"€\s*(\d{1,3}(?:[.,]\d{1,2})?)"),
    re.compile(r"(?<![\d.,])(\d{1,3}[.,]\d{2})\s*€"),
    re.compile(r"(?<![\d.,])(\d{1,3}[.,]\d{2})(?!\s*%)"),
]
_UNIT_PRICE_PATTERN = re.compile(
    r"(?<!\d)(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:€|euro)?\s*(?:/|al|per)\s*"
    r"(l|lt|litro|litri|kg|chilo|chilogrammo)",
    re.I,
)
_QUANTITY_PATTERN = re.compile(
    r"(?:(\d{1,2})\s*[x×]\s*)?(\d+(?:[.,]\d+)?)\s*(ml|cl|l|lt|litri?|g|gr|kg)\b",
    re.I,
)

_MONTHS = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}


def normalize_text(value: str) -> str:
    value = value.replace("’", "'").replace("`", "'").replace("×", "x")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold()
    value = re.sub(r"[^a-z0-9€%.,/'\s-]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _decimal(raw: str) -> float:
    return float(raw.replace(".", "").replace(",", ".")) if "," in raw else float(raw)


def _round_price(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _term_matches(normalized: str, term: str) -> list[re.Match[str]]:
    """Return whole-term matches, avoiding false positives such as "tè" inside "integrali"."""
    needle = normalize_text(term)
    if not needle:
        return []
    pattern = re.compile(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])")
    return list(pattern.finditer(normalized))


def _has_required_groups(normalized: str, product: ProductDefinition) -> bool:
    return all(any(_term_matches(normalized, alias) for alias in group) for group in product.all_groups)


def _matches_product(normalized: str, product: ProductDefinition) -> bool:
    if not _has_required_groups(normalized, product):
        return False
    if any(_term_matches(normalized, term) for term in product.exclude):
        return False
    return True


def _find_product_positions(normalized: str, product: ProductDefinition) -> list[int]:
    anchors: list[str] = []
    if product.all_groups:
        anchors = [normalize_text(alias) for alias in product.all_groups[0]]
    positions: list[int] = []
    for anchor in anchors:
        for match in _term_matches(normalized, anchor):
            positions.append(match.start())
    return sorted(set(positions))


def _nearest_price(window: str, anchor_offset: int) -> tuple[float | None, int | None]:
    candidates: list[tuple[int, float]] = []
    for pattern in _PRICE_PATTERNS:
        for match in pattern.finditer(window):
            try:
                price = _decimal(match.group(1))
            except ValueError:
                continue
            if price <= 0 or price > 150:
                continue
            # Evita di interpretare quantità come prezzi quando non compare il simbolo euro.
            if "€" not in match.group(0) and pattern is _PRICE_PATTERNS[-1]:
                nearby = window[max(0, match.start() - 10) : min(len(window), match.end() + 10)]
                if re.search(r"\b(?:ml|cl|lt?|kg|gr?|%)\b", nearby):
                    continue
            distance = abs(match.start() - anchor_offset) + (12 if match.start() < anchor_offset else 0)
            candidates.append((distance, price))
    if not candidates:
        return None, None
    distance, price = min(candidates, key=lambda item: item[0])
    return _round_price(price), distance


def _nearest_quantity(window: str, anchor_offset: int) -> tuple[float | None, str | None, float | None, str | None]:
    candidates: list[tuple[int, float, str, float, str]] = []
    for match in _QUANTITY_PATTERN.finditer(window):
        count = int(match.group(1) or 1)
        amount = _decimal(match.group(2))
        raw_unit = match.group(3).lower()
        if raw_unit in {"l", "lt", "litro", "litri"}:
            item_base = amount
            base_unit = "l"
        elif raw_unit == "ml":
            item_base = amount / 1000
            base_unit = "l"
        elif raw_unit == "cl":
            item_base = amount / 100
            base_unit = "l"
        elif raw_unit == "kg":
            item_base = amount
            base_unit = "kg"
        else:
            item_base = amount / 1000
            base_unit = "kg"
        total = item_base * count
        distance = abs(match.start() - anchor_offset) + (12 if match.start() < anchor_offset else 0)
        candidates.append((distance, total, base_unit, item_base, base_unit))
    if not candidates:
        return None, None, None, None
    _, total, base_unit, item_size, item_unit = min(candidates, key=lambda item: item[0])
    return round(total, 4), base_unit, round(item_size, 4), item_unit


def _explicit_unit_price(window: str, preferred_unit: str | None) -> tuple[float | None, str | None]:
    matches: list[tuple[float, str]] = []
    for match in _UNIT_PRICE_PATTERN.finditer(window):
        value = _decimal(match.group(1))
        unit = match.group(2).lower()
        normalized_unit = "kg" if unit in {"kg", "chilo", "chilogrammo"} else "l"
        if 0 < value < 200:
            matches.append((value, normalized_unit))
    if preferred_unit:
        for value, unit in matches:
            if unit == preferred_unit:
                return _round_price(value), unit
    if matches:
        value, unit = matches[0]
        return _round_price(value), unit
    return None, None


def _valid_size(product: ProductDefinition, item_size: float | None, item_unit: str | None) -> bool:
    if not product.accepted_item_sizes:
        return True
    if item_size is None or item_unit is None:
        return True
    if item_unit != product.accepted_size_unit:
        return False
    return any(math.isclose(item_size, expected, rel_tol=0.0, abs_tol=0.06) for expected in product.accepted_item_sizes)


def _parse_date(day: int, month_name: str, year: int | None, today: date) -> date:
    month = _MONTHS[month_name]
    if year is None:
        year = today.year
        candidate = date(year, month, day)
        if candidate < today - timedelta(days=180):
            candidate = date(year + 1, month, day)
        return candidate
    return date(year, month, day)


def extract_validity(text: str, today: date) -> tuple[str | None, str | None]:
    normalized = normalize_text(text)
    month_names = "|".join(_MONTHS)
    pattern_full = re.compile(
        rf"(?:dal|dall'|da)\s*(\d{{1,2}})\s*({month_names})\s*"
        rf"(?:al|all'|a)\s*(\d{{1,2}})\s*({month_names})(?:\s*(20\d{{2}}))?"
    )
    match = pattern_full.search(normalized)
    if match:
        year = int(match.group(5)) if match.group(5) else today.year
        start_date = date(year, _MONTHS[match.group(2)], int(match.group(1)))
        end_date = date(year, _MONTHS[match.group(4)], int(match.group(3)))
        if end_date < start_date:
            end_date = date(year + 1, end_date.month, end_date.day)
        return start_date.isoformat(), end_date.isoformat()

    pattern = re.compile(
        rf"(?:dal|dall'|dallo|da)\s*(\d{{1,2}})\s*"
        rf"(?:al|all'|allo|a)\s*(\d{{1,2}})\s*({month_names})(?:\s*(20\d{{2}}))?"
    )
    match = pattern.search(normalized)
    if match:
        start_day = int(match.group(1))
        end_day = int(match.group(2))
        end_month = match.group(3)
        year = int(match.group(4)) if match.group(4) else None
        end_date = _parse_date(end_day, end_month, year, today)
        start_month = end_date.month
        start_year = end_date.year
        if start_day > end_day:
            previous = end_date - relativedelta(months=1)
            start_month, start_year = previous.month, previous.year
        start_date = date(start_year, start_month, start_day)
        return start_date.isoformat(), end_date.isoformat()
    return None, None

def _loyalty_required(text: str) -> bool:
    normalized = normalize_text(text)
    return any(
        token in normalized
        for token in ("fidaty", "lidl plus", "blucard", "cartamica", "carta fedelta", "con carta")
    )


def _local_segment(text: str, start: int, max_radius: int = 260) -> tuple[str, int]:
    left_floor = max(0, start - max_radius)
    right_ceiling = min(len(text), start + max_radius)
    left_candidates = [text.rfind(separator, left_floor, start) for separator in ("\n", ";", ".", "|")]
    left = max([candidate for candidate in left_candidates if candidate >= 0], default=left_floor)
    if left < start and left < len(text) and text[left] in "\n;.|":
        left += 1
    right_candidates = [text.find(separator, start, right_ceiling) for separator in ("\n", ";", ".", "|")]
    valid_right = [candidate for candidate in right_candidates if candidate >= 0]
    right = min(valid_right, default=right_ceiling)
    segment = text[left:right].strip()
    if len(segment) < 18:
        segment = text[left_floor:right_ceiling]
        left = left_floor
    return segment, start - left


def _evidence_window(text: str, start: int, radius: int = 420) -> tuple[str, int]:
    left = max(0, start - radius)
    right = min(len(text), start + radius)
    window = text[left:right]
    return window, start - left


def extract_offers(
    documents: Iterable[DocumentBlob],
    products: list[ProductDefinition],
    run_date: date,
) -> list[Offer]:
    offers: list[Offer] = []
    seen: set[tuple[str, str, float | None, str]] = set()

    for document in documents:
        if not document.text.strip():
            continue
        normalized = normalize_text(document.text)
        valid_from, valid_to = extract_validity(document.text[:6000], run_date)
        for product in products:
            # Fast pre-filter: exclusions are evaluated only in the local offer segment,
            # because a flyer can legitimately contain both water and tea products.
            if not _has_required_groups(normalized, product):
                continue
            positions = _find_product_positions(normalized, product) or [0]
            for position in positions[:12]:
                window, anchor = _evidence_window(normalized, position)
                local, local_anchor = _local_segment(normalized, position)
                if _matches_product(local, product):
                    parsing_text, parsing_anchor = local, local_anchor
                elif _matches_product(window, product):
                    parsing_text, parsing_anchor = window, anchor
                else:
                    continue
                price, price_distance = _nearest_price(parsing_text, parsing_anchor)
                quantity, quantity_unit, item_size, item_unit = _nearest_quantity(parsing_text, parsing_anchor)
                if not _valid_size(product, item_size, item_unit):
                    continue
                explicit_unit, explicit_unit_name = _explicit_unit_price(parsing_text, product.compare_unit)
                unit_price: float | None = None
                unit_name: str | None = None
                if explicit_unit is not None:
                    unit_price, unit_name = explicit_unit, explicit_unit_name
                elif price is not None and quantity and quantity_unit == product.compare_unit:
                    unit_price = _round_price(price / quantity)
                    unit_name = quantity_unit

                confidence = 0.42
                if price is not None:
                    confidence += 0.22
                if quantity is not None:
                    confidence += 0.18
                if unit_price is not None:
                    confidence += 0.10
                if document.kind in {"json", "html", "pdf"}:
                    confidence += 0.05
                if price_distance is not None and price_distance > 260:
                    confidence -= 0.08
                if document.kind == "image_ocr":
                    confidence -= 0.04
                confidence = round(max(0.0, min(confidence, 0.99)), 2)

                evidence = re.sub(r"\s+", " ", window).strip()[:850]
                key = (document.source_id, product.id, price, evidence[:150])
                if key in seen:
                    continue
                seen.add(key)
                offers.append(
                    Offer(
                        run_date=run_date.isoformat(),
                        source=document.source_id,
                        store=document.store,
                        product_id=product.id,
                        product_name=product.name,
                        price_eur=price,
                        quantity_total=quantity,
                        quantity_unit=quantity_unit,
                        unit_price=unit_price,
                        unit_price_unit=unit_name,
                        valid_from=valid_from,
                        valid_to=valid_to,
                        loyalty_required=_loyalty_required(window),
                        confidence=confidence,
                        source_url=document.url,
                        evidence=evidence,
                    )
                )
    return _deduplicate_offers(offers)


def _deduplicate_offers(offers: list[Offer]) -> list[Offer]:
    grouped: dict[tuple[str, str, float | None, float | None], list[Offer]] = defaultdict(list)
    for offer in offers:
        grouped[(offer.source, offer.product_id, offer.price_eur, offer.unit_price)].append(offer)
    deduped: list[Offer] = []
    for candidates in grouped.values():
        deduped.append(max(candidates, key=lambda item: (item.confidence, len(item.evidence))))
    return sorted(deduped, key=lambda item: (item.product_name, item.unit_price or 9999, item.source))


def classify_offers(offers: list[Offer], history: list[dict[str, str]], today: date) -> list[Offer]:
    history_by_product: dict[str, list[float]] = defaultdict(list)
    cutoff = today - timedelta(days=90)
    for row in history:
        try:
            row_date = datetime.fromisoformat(row.get("run_date", "")).date()
            price = float(row.get("unit_price", ""))
        except (ValueError, TypeError):
            continue
        if row_date >= cutoff and price > 0:
            history_by_product[row.get("product_id", "")].append(price)

    best_current: dict[str, float] = {}
    for offer in offers:
        if offer.unit_price is None or offer.confidence < 0.68:
            continue
        current = best_current.get(offer.product_id)
        if current is None or offer.unit_price < current:
            best_current[offer.product_id] = offer.unit_price

    classified: list[Offer] = []
    for offer in offers:
        label = "DA VERIFICARE"
        if offer.confidence >= 0.68 and offer.unit_price is not None:
            past = history_by_product.get(offer.product_id, [])
            if not past:
                label = "MIGLIORE DI OGGI" if best_current.get(offer.product_id) == offer.unit_price else "DA VALUTARE"
            else:
                median = statistics.median(past)
                historical_min = min(past)
                if offer.unit_price <= historical_min * 1.01:
                    label = "OTTIMA"
                elif offer.unit_price <= median * 0.90:
                    label = "BUONA"
                elif offer.unit_price <= median * 1.05:
                    label = "NORMALE"
                else:
                    label = "NON CONVENIENTE"
        classified.append(
            replace(
                offer,
                classification=label,
                best_of_run=(offer.unit_price is not None and best_current.get(offer.product_id) == offer.unit_price),
            )
        )
    return classified
