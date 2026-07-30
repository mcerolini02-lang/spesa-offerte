from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ProductDefinition:
    id: str
    name: str
    all_groups: list[list[str]]
    exclude: list[str] = field(default_factory=list)
    accepted_item_sizes: list[float] = field(default_factory=list)
    accepted_size_unit: str | None = None
    compare_unit: str | None = None
    notes: str = ""


@dataclass(slots=True)
class SourceDefinition:
    id: str
    name: str
    enabled: bool
    store: str
    start_urls: list[str]
    allowed_domains: list[str]
    max_pages: int = 10
    max_images: int = 20
    interaction: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DocumentBlob:
    source_id: str
    store: str
    url: str
    kind: str
    text: str
    title: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Offer:
    run_date: str
    source: str
    store: str
    product_id: str
    product_name: str
    price_eur: float | None
    quantity_total: float | None
    quantity_unit: str | None
    unit_price: float | None
    unit_price_unit: str | None
    valid_from: str | None
    valid_to: str | None
    loyalty_required: bool
    confidence: float
    source_url: str
    evidence: str
    classification: str = "DA VERIFICARE"
    best_of_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class AssetRef:
    source_id: str
    store: str
    url: str
    kind: str


@dataclass(slots=True)
class CollectionResult:
    source_id: str
    store: str
    documents: list[DocumentBlob] = field(default_factory=list)
    assets: list[AssetRef] = field(default_factory=list)
    visited_urls: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
