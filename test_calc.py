import tempfile
from pathlib import Path

import db as dbmod
from calculations import (
    ceil_fx_1,
    ceil_int,
    convert_position,
    fx_to_uah,
    line_economics,
    recompute_order,
    order_totals,
    settle_incoming,
    shipment_lines,
    shipment_totals,
    uah_to_fx,
)
from db import get_saved_order, init_db, save_order
from pdf_export import build_quote_pdf, build_settlement_pdf, money, weight_fmt


def test_ton_to_pieces():
    r = convert_position(2, "Штука", "Тонна", 62000, 812.5)
    assert abs(r["weight_tons"] - 1.625) < 1e-9
    assert abs(r["purchase_cost"] - 100750) < 1e-6


def test_piece_to_tons():
    r = convert_position(0.265, "Тонна", "Штука", 3200, 265)
    assert abs(r["pieces"] - 1.0) < 1e-9
    assert abs(r["purchase_cost"] - 3200) < 1e-6


def test_ceil_int():
    assert ceil_int(0) == 0
    assert ceil_int(10) == 10
    assert ceil_int(1) == 1
    assert ceil_int(1.01) == 2
    assert ceil_int(100750) == 100750


def test_ceil_fx_1():
    assert ceil_fx_1(0) == 0
    assert ceil_fx_1(2) == 2
    assert ceil_fx_1(2.01) == 3
    assert ceil_fx_1(2090.91) == 2091


def test_money_uah_no_decimals():
    assert money(80000, "UAH") == "80 000 грн"
    assert money(2091, "USD") == "2 091 USD"


def test_margin_currency():
    eco = line_economics(1000, 100, 10, "Валюта", 250)
    # tax = 110; cost = 1210; selling = 1460 — уже кратно 10
    assert abs(eco["cost"] - 1210) < 1e-6
    assert abs(eco["selling"] - 1460) < 1e-6
    assert abs(eco["profit"] - 250) < 1e-6
    eco2 = line_economics(1001, 0, 0, "%", 0)
    assert abs(eco2["cost"] - 1001) < 1e-6
    assert abs(eco2["selling"] - 1001) < 1e-6


def test_uah_to_fx():
    assert abs(uah_to_fx(4150, 41.5) - 100) < 1e-9
    assert uah_to_fx(100, 0) == 0


def test_order_and_pdf():
    items = [
        {
            "name": "Рельс Р65",
            "condition": "Новое",
            "quantity": 2,
            "input_unit": "Штука",
            "purchase_unit": "Тонна",
            "purchase_price": 62000,
            "piece_weight_kg": 812.5,
            "margin_type": "%",
            "margin_value": 20,
        }
    ]
    lines = recompute_order(
        items,
        tax_percent=0,
        customs_value=1000,
        customs_mode="На весь заказ",
        uah_per_unit=41.5,
    )
    totals = order_totals(lines)
    assert totals["selling_fx"] > 0
    assert totals["selling_fx"] == ceil_fx_1(totals["selling"] / 41.5)
    pdf = build_quote_pdf(
        lines, totals, client_name="Тест", note="Проверка", quote_currency="USD"
    )
    assert pdf.startswith(b"%PDF")
    assert b"62000" not in pdf
    assert "закуп" not in pdf.decode("latin-1", errors="ignore").lower()
    assert abs(totals["weight_tons"] - 1.625) < 1e-9
    assert weight_fmt(totals["weight_tons"]) == "1.625 т"


def test_save_and_reload_order():
    original = dbmod.DB_PATH
    dbmod.DB_PATH = Path(tempfile.mkdtemp()) / "test_vsp.db"
    try:
        init_db()
        items = [
            {
                "uid": 1,
                "name": "Рельс Р65",
                "condition": "Новое",
                "quantity": 2,
                "input_unit": "Штука",
                "purchase_unit": "Тонна",
                "purchase_price": 62000,
                "piece_weight_kg": 812.5,
                "margin_type": "%",
                "margin_value": 20,
            }
        ]
        lines = recompute_order(items, 0, 0, "На весь заказ", 41.5)
        totals = order_totals(lines)
        order_id = save_order(
            comment="Проверка сохранения",
            items=items,
            totals=totals,
            tax_percent=0,
            customs_mode="На весь заказ",
            customs_value=0,
            quote_currency="USD",
            uah_per_unit=41.5,
            client_name="Тест",
        )
        loaded = get_saved_order(order_id)
        assert loaded is not None
        assert loaded["comment"] == "Проверка сохранения"
        assert loaded["items"][0]["name"] == "Рельс Р65"
        assert abs(loaded["weight_tons"] - totals["weight_tons"]) < 1e-9
    finally:
        dbmod.DB_PATH = original


def test_settle_incoming():
    assert abs(fx_to_uah(100, 41.5) - 4150) < 1e-9
    s = settle_incoming(
        amount_fx=1000,
        uah_per_unit=40,
        customs_percent=10,
        bank_type="грн",
        bank_value=500,
        remainder_percent=20,
        shipment_uah=10000,
    )
    # incoming 40000; customs 4000; bank 500; after fees 35500;
    # minus shipment 10000 → 25500; 20% = 5100; final 20400
    assert abs(s["incoming_uah"] - 40000) < 1e-6
    assert abs(s["customs_amount"] - 4000) < 1e-6
    assert abs(s["bank_amount"] - 500) < 1e-6
    assert abs(s["remainder"] - 35500) < 1e-6
    assert abs(s["after_shipment"] - 25500) < 1e-6
    assert abs(s["hold_amount"] - 5100) < 1e-6
    assert abs(s["final_uah"] - 20400) < 1e-6
    s2 = settle_incoming(1000, 40, 10, "%", 2, 0)
    assert abs(s2["bank_amount"] - 800) < 1e-6
    assert abs(s2["remainder"] - 35200) < 1e-6
    assert abs(s2["after_shipment"] - 35200) < 1e-6
    s3 = settle_incoming(100, 41.5, 0, "грн", 0, 0)
    # 4150 грн → 4150 уже кратно 10; 100 * 41.51 would round
    assert s3["incoming_uah"] == 4150
    s4 = settle_incoming(100, 41.51, 0, "грн", 0, 0)
    assert s4["incoming_uah"] == 4151


def test_shipment_and_settlement_pdf():
    items = [
        {
            "name": "Рельс Р65",
            "condition": "Новое",
            "quantity": 2,
            "input_unit": "Штука",
            "purchase_unit": "Тонна",
            "purchase_price": 62000,
            "piece_weight_kg": 812.5,
        }
    ]
    lines = shipment_lines(items)
    totals = shipment_totals(lines)
    assert abs(totals["line_total"] - 100750) < 1e-6
    settlement = settle_incoming(2000, 41.5, 5, "грн", 100, 10, totals["line_total"])
    pdf = build_settlement_pdf(lines, totals, settlement, quote_currency="USD")
    assert pdf.startswith(b"%PDF")


if __name__ == "__main__":
    test_ton_to_pieces()
    test_piece_to_tons()
    test_ceil_int()
    test_ceil_fx_1()
    test_money_uah_no_decimals()
    test_margin_currency()
    test_uah_to_fx()
    test_order_and_pdf()
    test_save_and_reload_order()
    test_settle_incoming()
    test_shipment_and_settlement_pdf()
    print("ok")
