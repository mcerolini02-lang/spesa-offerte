from __future__ import annotations

import csv
from pathlib import Path

from .models import Offer

_HISTORY_FIELDS = [
    "run_date",
    "source",
    "store",
    "product_id",
    "product_name",
    "price_eur",
    "quantity_total",
    "quantity_unit",
    "unit_price",
    "unit_price_unit",
    "valid_from",
    "valid_to",
    "loyalty_required",
    "confidence",
    "source_url",
    "evidence",
    "classification",
]


def load_history(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def append_history(path: Path, offers: list[Offer]) -> None:
    existing = load_history(path)
    keys = {
        (
            row.get("run_date", ""),
            row.get("source", ""),
            row.get("product_id", ""),
            row.get("price_eur", ""),
            row.get("unit_price", ""),
            row.get("source_url", ""),
        )
        for row in existing
    }
    rows = existing[:]
    for offer in offers:
        data = offer.to_dict()
        row = {field: "" if data.get(field) is None else str(data.get(field)) for field in _HISTORY_FIELDS}
        key = (
            row["run_date"],
            row["source"],
            row["product_id"],
            row["price_eur"],
            row["unit_price"],
            row["source_url"],
        )
        if key not in keys:
            rows.append(row)
            keys.add(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_HISTORY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
