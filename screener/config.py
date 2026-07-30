from __future__ import annotations

from pathlib import Path

import yaml

from .models import ProductDefinition, SourceDefinition


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Configurazione non valida: {path}")
    return data


def load_products(config_dir: Path) -> list[ProductDefinition]:
    raw = _load_yaml(config_dir / "products.yml")
    products: list[ProductDefinition] = []
    for item in raw.get("products", []):
        products.append(
            ProductDefinition(
                id=str(item["id"]),
                name=str(item["name"]),
                all_groups=[list(map(str, group)) for group in item.get("all_groups", [])],
                exclude=list(map(str, item.get("exclude", []))),
                accepted_item_sizes=[float(x) for x in item.get("accepted_item_sizes", [])],
                accepted_size_unit=item.get("accepted_size_unit"),
                compare_unit=item.get("compare_unit"),
                notes=str(item.get("notes", "")),
            )
        )
    if not products:
        raise ValueError("Nessun prodotto configurato in products.yml")
    return products


def load_sources(config_dir: Path) -> list[SourceDefinition]:
    raw = _load_yaml(config_dir / "sources.yml")
    sources: list[SourceDefinition] = []
    for item in raw.get("sources", []):
        sources.append(
            SourceDefinition(
                id=str(item["id"]),
                name=str(item["name"]),
                enabled=bool(item.get("enabled", True)),
                store=str(item.get("store", "")),
                start_urls=list(map(str, item.get("start_urls", []))),
                allowed_domains=list(map(str, item.get("allowed_domains", []))),
                max_pages=int(item.get("max_pages", 10)),
                max_images=int(item.get("max_images", 20)),
                interaction=dict(item.get("interaction", {})),
            )
        )
    return [source for source in sources if source.enabled]
