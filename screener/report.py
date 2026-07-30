from __future__ import annotations

import csv
import html
import json
from collections import Counter
from pathlib import Path

from .models import Offer

_REPORT_FIELDS = [
    "run_date",
    "product_name",
    "source",
    "store",
    "price_eur",
    "quantity_total",
    "quantity_unit",
    "unit_price",
    "unit_price_unit",
    "classification",
    "best_of_run",
    "valid_from",
    "valid_to",
    "loyalty_required",
    "confidence",
    "source_url",
    "evidence",
]


def _money(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f} €".replace(".", ",")


def _unit_price(offer: Offer) -> str:
    if offer.unit_price is None:
        return "—"
    suffix = "/L" if offer.unit_price_unit == "l" else "/kg" if offer.unit_price_unit == "kg" else ""
    return f"{offer.unit_price:.2f} €{suffix}".replace(".", ",")


def _quantity(offer: Offer) -> str:
    if offer.quantity_total is None or not offer.quantity_unit:
        return "—"
    return f"{offer.quantity_total:g} {offer.quantity_unit}"


def write_csv(path: Path, offers: list[Offer]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_REPORT_FIELDS)
        writer.writeheader()
        for offer in offers:
            data = offer.to_dict()
            writer.writerow({field: data.get(field, "") for field in _REPORT_FIELDS})


def write_markdown(path: Path, offers: list[Offer], statuses: dict) -> None:
    recommended = [
        offer
        for offer in offers
        if offer.best_of_run and offer.confidence >= 0.68 and offer.classification != "NON CONVENIENTE"
    ]
    review = [offer for offer in offers if offer.confidence < 0.68 or offer.unit_price is None]
    lines = [
        "# Screener offerte alimentari",
        "",
        f"Esecuzione: **{statuses.get('run_date', '')}**",
        "",
        "## Migliori risultati rilevati",
        "",
    ]
    if recommended:
        lines.extend(
            [
                "| Prodotto | Supermercato | Prezzo | Quantità | Prezzo unitario | Giudizio | Validità |",
                "|---|---|---:|---:|---:|---|---|",
            ]
        )
        for offer in recommended:
            validity = " → ".join(filter(None, [offer.valid_from, offer.valid_to])) or "—"
            lines.append(
                f"| {offer.product_name} | {offer.source} | {_money(offer.price_eur)} | "
                f"{_quantity(offer)} | {_unit_price(offer)} | **{offer.classification}** | {validity} |"
            )
    else:
        lines.append("Nessuna offerta con dati sufficientemente affidabili è stata rilevata.")

    lines.extend(["", "## Stato fonti", ""])
    for source_id, status in statuses.get("sources", {}).items():
        lines.append(
            f"- **{source_id}**: {status.get('documents', 0)} documenti, "
            f"{status.get('offers', 0)} risultati, {len(status.get('errors', []))} errori."
        )
    if review:
        lines.extend(
            [
                "",
                "## Risultati da verificare",
                "",
                "Sono stati rilevati elementi incompleti o con associazione prezzo/prodotto poco sicura. "
                "Restano nel CSV ma non vengono consigliati automaticamente.",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_html(path: Path, offers: list[Offer], statuses: dict) -> None:
    rows: list[str] = []
    for offer in offers:
        row_class = "best" if offer.best_of_run else ""
        if offer.classification == "NON CONVENIENTE":
            row_class = "bad"
        elif offer.confidence < 0.68:
            row_class = "review"
        rows.append(
            "<tr class='{cls}'>"
            "<td>{product}</td><td>{source}</td><td>{price}</td><td>{qty}</td>"
            "<td>{unit}</td><td>{classification}</td><td>{confidence:.0%}</td>"
            "<td><a href='{url}' target='_blank' rel='noopener'>fonte</a></td>"
            "</tr>".format(
                cls=row_class,
                product=html.escape(offer.product_name),
                source=html.escape(offer.source),
                price=html.escape(_money(offer.price_eur)),
                qty=html.escape(_quantity(offer)),
                unit=html.escape(_unit_price(offer)),
                classification=html.escape(offer.classification),
                confidence=offer.confidence,
                url=html.escape(offer.source_url, quote=True),
            )
        )
    counts = Counter(offer.classification for offer in offers)
    status_cards = "".join(
        f"<li><strong>{html.escape(source)}</strong>: {info.get('documents', 0)} documenti, "
        f"{info.get('offers', 0)} risultati, {len(info.get('errors', []))} errori</li>"
        for source, info in statuses.get("sources", {}).items()
    )
    document = f"""<!doctype html>
<html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Screener offerte alimentari</title>
<style>
body{{font-family:Arial,sans-serif;margin:24px;color:#17202a;background:#f6f7f9}}
main{{max-width:1250px;margin:auto;background:white;padding:24px;border-radius:14px;box-shadow:0 4px 22px #0001}}
h1{{margin-top:0}} .kpi{{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}}
.kpi div{{background:#eef2f5;padding:12px 16px;border-radius:10px;min-width:130px}}
table{{border-collapse:collapse;width:100%;font-size:14px}} th,td{{padding:9px;border-bottom:1px solid #dde2e6;text-align:left}}
th{{background:#273746;color:white;position:sticky;top:0}} tr.best{{background:#eaf8ef}} tr.bad{{background:#fff0f0}} tr.review{{background:#fff8df}}
a{{color:#155eef}} .note{{color:#566573;font-size:13px}}
</style></head><body><main>
<h1>Screener offerte alimentari</h1>
<p>Esecuzione: <strong>{html.escape(str(statuses.get('run_date', '')))}</strong></p>
<div class="kpi"><div><strong>{len(offers)}</strong><br>risultati</div><div><strong>{counts.get('OTTIMA', 0)}</strong><br>ottime</div><div><strong>{counts.get('BUONA', 0)}</strong><br>buone</div><div><strong>{counts.get('DA VERIFICARE', 0)}</strong><br>da verificare</div></div>
<table><thead><tr><th>Prodotto</th><th>Fonte</th><th>Prezzo</th><th>Quantità</th><th>Prezzo unitario</th><th>Giudizio</th><th>Affidabilità</th><th>Link</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<h2>Stato fonti</h2><ul>{status_cards}</ul>
<p class="note">Il report mostra solo informazioni pubbliche. Prezzi e disponibilità vanno verificati prima dell'acquisto; coupon personali e promozioni riservate all'app possono non essere visibili.</p>
</main></body></html>"""
    path.write_text(document, encoding="utf-8")


def write_status(path: Path, statuses: dict) -> None:
    path.write_text(json.dumps(statuses, ensure_ascii=False, indent=2), encoding="utf-8")


def write_reports(output_dir: Path, offers: list[Offer], statuses: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "offerte_latest.csv", offers)
    write_markdown(output_dir / "offerte_latest.md", offers, statuses)
    write_html(output_dir / "offerte_latest.html", offers, statuses)
    write_status(output_dir / "status.json", statuses)
