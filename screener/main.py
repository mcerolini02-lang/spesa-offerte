from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

from .assets import extract_assets
from .browser import collect_source
from .config import load_products, load_sources
from .history import append_history, load_history
from .matcher import classify_offers, extract_offers
from .report import write_reports


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Screener automatico delle offerte alimentari")
    parser.add_argument("--config", type=Path, default=Path("config"), help="Cartella configurazioni YAML")
    parser.add_argument("--output", type=Path, default=Path("reports"), help="Cartella report")
    parser.add_argument("--history", type=Path, default=Path("data/history.csv"), help="CSV storico")
    parser.add_argument("--raw-dir", type=Path, default=Path("tmp/raw"), help="Cartella diagnostica")
    parser.add_argument("--source", action="append", help="Esegue solo la fonte indicata; ripetibile")
    parser.add_argument(
        "--max-assets-per-source",
        type=int,
        default=int(os.getenv("MAX_ASSETS_PER_SOURCE", "12")),
        help="Numero massimo di PDF/immagini analizzati per fonte",
    )
    parser.add_argument("--strict", action="store_true", help="Restituisce errore se nessuna offerta è rilevata")
    return parser.parse_args()


def run(args: argparse.Namespace) -> int:
    run_date = date.today()
    products = load_products(args.config)
    sources = load_sources(args.config)
    if args.source:
        requested = set(args.source)
        sources = [source for source in sources if source.id in requested]
    if not sources:
        raise SystemExit("Nessuna fonte abilitata o corrispondente al filtro --source")

    args.raw_dir.mkdir(parents=True, exist_ok=True)
    statuses: dict = {"run_date": run_date.isoformat(), "sources": {}}
    all_offers = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for source in sources:
                source_status = {
                    "store": source.store,
                    "documents": 0,
                    "assets": 0,
                    "offers": 0,
                    "visited_urls": [],
                    "errors": [],
                }
                statuses["sources"][source.id] = source_status
                try:
                    collected = collect_source(browser, source, args.raw_dir)
                    documents = collected.documents[:]
                    source_status["visited_urls"] = collected.visited_urls
                    source_status["assets"] = len(collected.assets)
                    source_status["errors"].extend(collected.errors)

                    asset_docs, asset_errors = extract_assets(
                        collected.assets,
                        args.raw_dir / source.id / "assets",
                        max_assets=max(0, args.max_assets_per_source),
                    )
                    documents.extend(asset_docs)
                    source_status["errors"].extend(asset_errors)
                    source_status["documents"] = len(documents)

                    offers = extract_offers(documents, products, run_date)
                    source_status["offers"] = len(offers)
                    all_offers.extend(offers)
                except Exception as exc:
                    source_status["errors"].append(f"Errore fonte: {type(exc).__name__}: {exc}")
        finally:
            browser.close()

    history = load_history(args.history)
    classified = classify_offers(all_offers, history, run_date)
    write_reports(args.output, classified, statuses)
    append_history(args.history, classified)

    print(f"Fonti elaborate: {len(sources)}")
    print(f"Risultati rilevati: {len(classified)}")
    print(f"Report: {args.output / 'offerte_latest.html'}")
    if args.strict and not classified:
        return 2
    return 0


def main() -> None:
    raise SystemExit(run(parse_args()))


if __name__ == "__main__":
    main()
