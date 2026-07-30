from datetime import date
from pathlib import Path

from screener.config import load_products
from screener.matcher import extract_offers
from screener.models import DocumentBlob

PRODUCTS = load_products(Path("config"))


def _doc(text: str) -> DocumentBlob:
    return DocumentBlob(
        source_id="test",
        store="Negozio test",
        url="https://example.test/offerte",
        kind="html",
        text=text,
    )


def _offer(product_id: str, text: str):
    matches = extract_offers([_doc(text)], PRODUCTS, date(2026, 7, 30))
    return next(item for item in matches if item.product_id == product_id)


def test_santanna_multipack_unit_price():
    offer = _offer(
        "acqua_santanna_naturale_15_2l",
        "Acqua minerale naturale Sant'Anna confezione 6 x 1,5 L € 2,69 dal 28 luglio al 9 agosto",
    )
    assert offer.quantity_total == 9.0
    assert offer.quantity_unit == "l"
    assert offer.unit_price == 0.30


def test_santanna_tea_not_confused_with_water():
    matches = extract_offers(
        [_doc("Tè Sant'Anna limone 1,5 L € 1,19")], PRODUCTS, date(2026, 7, 30)
    )
    ids = {item.product_id for item in matches}
    assert "the_santanna_15l" in ids
    assert "acqua_santanna_naturale_15_2l" not in ids


def test_misura_flavours_are_separate():
    matches = extract_offers(
        [_doc("Cornetti Misura all'albicocca 290 g € 2,49")], PRODUCTS, date(2026, 7, 30)
    )
    ids = {item.product_id for item in matches}
    assert "brioche_misura_albicocca" in ids
    assert "brioche_misura_miele" not in ids


def test_galbusera_price_per_kg():
    offer = _offer(
        "biscotti_integrali_galbusera",
        "Biscotti integrali Galbusera 400 g prezzo € 1,99",
    )
    assert offer.quantity_total == 0.4
    assert offer.quantity_unit == "kg"
    assert offer.unit_price == 4.98


def test_wrong_santanna_size_is_rejected():
    matches = extract_offers(
        [_doc("Acqua Sant'Anna naturale 6 x 0,5 L € 2,20")], PRODUCTS, date(2026, 7, 30)
    )
    assert "acqua_santanna_naturale_15_2l" not in {item.product_id for item in matches}


def test_parmalat_barista():
    offer = _offer("latte_parmalat_barista", "Latte Parmalat Barista 1 L € 1,69")
    assert offer.unit_price == 1.69


def test_price_is_associated_with_the_correct_product():
    text = (
        "Biscotti integrali Galbusera 400 g € 1,99. "
        "Latte Parmalat Barista 1 L € 1,69."
    )
    matches = extract_offers([_doc(text)], PRODUCTS, date(2026, 7, 30))
    by_id = {item.product_id: item for item in matches}
    assert by_id["biscotti_integrali_galbusera"].price_eur == 1.99
    assert by_id["latte_parmalat_barista"].price_eur == 1.69


def test_water_is_not_dropped_when_other_products_contain_te_sequence():
    text = (
        "Acqua minerale naturale Sant'Anna confezione 6 x 1,5 L € 2,69. "
        "Biscotti integrali Galbusera 400 g € 1,99."
    )
    matches = extract_offers([_doc(text)], PRODUCTS, date(2026, 7, 30))
    by_id = {item.product_id: item for item in matches}
    assert by_id["acqua_santanna_naturale_15_2l"].unit_price == 0.30


def test_water_and_tea_can_coexist_in_same_flyer():
    text = (
        "Acqua minerale naturale Sant'Anna 6 x 1,5 L € 2,69. "
        "Tè Sant'Anna limone 1,5 L € 1,19."
    )
    matches = extract_offers([_doc(text)], PRODUCTS, date(2026, 7, 30))
    ids = {item.product_id for item in matches}
    assert "acqua_santanna_naturale_15_2l" in ids
    assert "the_santanna_15l" in ids
