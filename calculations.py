"""Пересчёт единиц, себестоимости и цены продажи."""

from __future__ import annotations

import math
from typing import Any

KG_PER_TON = 1000.0
VAT_PERCENT = 20.0
# Транспорт, растаможка и накладные вводятся в валюте КП и переводятся в грн по курсу.
EXTRA_COSTS_IN_FX = True


def ceil_int(value: float) -> float:
    """Округление денежной суммы вверх до целого."""
    amount = float(value or 0)
    if amount == 0:
        return 0.0
    return float(math.ceil(amount - 1e-12))


def ceil_uah_10(value: float) -> float:
    return ceil_int(value)


def ceil_fx_1(value: float) -> float:
    return ceil_int(value)


def convert_position(
    quantity: float,
    input_unit: str,
    purchase_unit: str,
    purchase_price: float,
    piece_weight_kg: float,
) -> dict[str, float]:
    """Переводит ввод в вес, штуки и сумму закупки."""
    qty = max(float(quantity or 0), 0.0)
    weight_kg_piece = max(float(piece_weight_kg or 0), 0.0)

    if input_unit == "Тонна":
        weight_tons = qty
        pieces = (qty * KG_PER_TON / weight_kg_piece) if weight_kg_piece > 0 else 0.0
    else:
        pieces = qty
        weight_tons = (qty * weight_kg_piece / KG_PER_TON) if weight_kg_piece > 0 else 0.0

    if purchase_unit == "Тонна":
        purchase_cost = weight_tons * float(purchase_price)
    else:
        purchase_cost = pieces * float(purchase_price)

    return {
        "weight_tons": weight_tons,
        "pieces": pieces,
        "purchase_cost": purchase_cost,
    }


def allocate_customs(
    weights: list[float],
    customs_value: float,
    mode: str,
) -> list[float]:
    """Затаможка: на весь заказ (пропорционально весу) или за тонну."""
    customs_value = max(float(customs_value or 0), 0.0)
    if not weights:
        return []
    if mode == "За тонну":
        return [w * customs_value for w in weights]

    total_weight = sum(weights)
    if total_weight > 0:
        return [customs_value * (w / total_weight) for w in weights]
    share = customs_value / len(weights)
    return [share for _ in weights]


def line_economics(
    purchase_cost: float,
    customs_cost: float,
    tax_percent: float,
    margin_type: str,
    margin_value: float,
    margin_deduct_percent: float = VAT_PERCENT,
    extra_cost: float = 0.0,
) -> dict[str, float]:
    """Себестоимость, цена продажи и чистая маржа по позиции."""
    purchase_cost = max(float(purchase_cost or 0), 0.0)
    customs_cost = max(float(customs_cost or 0), 0.0)
    extra_cost = max(float(extra_cost or 0), 0.0)
    tax_percent = max(float(tax_percent or 0), 0.0)
    margin_value = float(margin_value or 0)
    deduct = min(max(float(margin_deduct_percent or 0), 0.0), 100.0)

    tax_amount = ceil_int((purchase_cost + customs_cost) * tax_percent / 100.0)
    cost = ceil_int(purchase_cost + customs_cost + tax_amount + extra_cost)

    if margin_type in ("Валюта", "грн"):
        profit = ceil_int(margin_value)
        selling = ceil_int(cost + profit)
    else:
        profit = ceil_int(cost * margin_value / 100.0)
        selling = ceil_int(cost + profit)

    profit_net = ceil_int(profit * (1.0 - deduct / 100.0))
    return {
        "tax_amount": tax_amount,
        "cost": cost,
        "selling": selling,
        "profit": profit,
        "profit_net": profit_net,
    }


def selling_unit_price(selling_total: float, quantity: float) -> float:
    qty = float(quantity or 0)
    if qty <= 0:
        return 0.0
    return selling_total / qty


def uah_to_fx(amount_uah: float, uah_per_unit: float) -> float:
    """Гривна → валюта КП. Курс: сколько грн за 1 единицу валюты."""
    rate = float(uah_per_unit or 0)
    if rate <= 0:
        return 0.0
    return float(amount_uah or 0) / rate


def fx_to_uah(amount_fx: float, uah_per_unit: float) -> float:
    """Валюта КП → гривна. Курс: сколько грн за 1 единицу валюты."""
    return float(amount_fx or 0) * max(float(uah_per_unit or 0), 0.0)


def apply_fx(line: dict[str, Any], uah_per_unit: float) -> dict[str, Any]:
    return {
        **line,
        "selling_fx": ceil_fx_1(uah_to_fx(line["selling"], uah_per_unit)),
        "unit_selling_fx": ceil_fx_1(uah_to_fx(line["unit_selling"], uah_per_unit)),
        "profit_fx": ceil_fx_1(uah_to_fx(line["profit"], uah_per_unit)),
        "profit_net_fx": ceil_fx_1(uah_to_fx(line.get("profit_net", 0.0), uah_per_unit)),
        "cost_fx": ceil_fx_1(uah_to_fx(line["cost"], uah_per_unit)),
    }


def recompute_order(
    items: list[dict[str, Any]],
    tax_percent: float,
    customs_value: float,
    customs_mode: str,
    uah_per_unit: float = 0.0,
    margin_deduct_percent: float = VAT_PERCENT,
    transport_cost: float = 0.0,
    transport_tons: float = 0.0,
    clearance_cost: float = 0.0,
    clearance_percent: float = 0.0,
    overhead_cost: float = 0.0,
) -> list[dict[str, Any]]:
    conversions = [
        convert_position(
            item["quantity"],
            item["input_unit"],
            item["purchase_unit"],
            item["purchase_price"],
            item["piece_weight_kg"],
        )
        for item in items
    ]
    weights = [c["weight_tons"] for c in conversions]
    customs = allocate_customs(weights, customs_value, customs_mode)
    total_weight = sum(weights)
    tons = max(float(transport_tons or 0), 0.0)
    transport_uah = fx_to_uah(transport_cost, uah_per_unit)
    overhead_uah = fx_to_uah(overhead_cost, uah_per_unit)
    # Ставка за N тонн транспорта: вес заказа / N. 30 т при ставке за 20 т = ×1.5.
    scale = (total_weight / tons) if tons > 0 else 0.0
    transports = allocate_customs(weights, transport_uah * scale, "На весь заказ")
    overheads = allocate_customs(weights, overhead_uah, "На весь заказ")
    zeros = [0.0 for _ in weights]

    def compose(clearances: list[float]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item, conv, customs_cost, transport, clearance, overhead in zip(
            items, conversions, customs, transports, clearances, overheads
        ):
            purchase_cost = ceil_int(conv["purchase_cost"])
            customs_cost = ceil_int(customs_cost)
            transport = ceil_int(transport)
            clearance = ceil_int(clearance)
            overhead = ceil_int(overhead)
            extra_cost = transport + clearance + overhead
            eco = line_economics(
                purchase_cost,
                customs_cost,
                tax_percent,
                item.get("margin_type", "%"),
                item.get("margin_value", 0),
                margin_deduct_percent,
                extra_cost,
            )
            unit_price = selling_unit_price(eco["selling"], item["quantity"])
            result.append(
                apply_fx(
                    {
                        **item,
                        **conv,
                        "purchase_cost": purchase_cost,
                        "customs_cost": customs_cost,
                        "transport_cost": transport,
                        "clearance_cost": clearance,
                        "overhead_cost": overhead,
                        **eco,
                        "unit_selling": unit_price,
                    },
                    uah_per_unit,
                )
            )
        return result

    lines = compose(zeros)
    percent = min(max(float(clearance_percent or 0), 0.0), 100.0)
    if percent <= 0:
        return lines
    selling_uah = sum(float(line.get("selling") or 0) for line in lines)
    clearance_uah = ceil_int(selling_uah * percent / 100.0)
    return compose(allocate_customs(weights, clearance_uah, "На весь заказ"))


def with_exchange_rate(lines: list[dict[str, Any]], uah_per_unit: float) -> list[dict[str, Any]]:
    return [apply_fx(line, uah_per_unit) for line in lines]


def shipment_lines(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Сумма отгрузки по ценам закупки из базы, без наценки и налога."""
    result: list[dict[str, Any]] = []
    for item in items:
        conv = convert_position(
            item["quantity"],
            item["input_unit"],
            item["purchase_unit"],
            item["purchase_price"],
            item["piece_weight_kg"],
        )
        line_total = ceil_int(conv["purchase_cost"])
        unit_price = (
            line_total / float(item["quantity"])
            if float(item.get("quantity") or 0) > 0
            else 0.0
        )
        result.append(
            {
                **item,
                **conv,
                "purchase_cost": line_total,
                "line_total": line_total,
                "unit_price": unit_price,
            }
        )
    return result


def shipment_totals(lines: list[dict[str, Any]]) -> dict[str, float]:
    return {
        "weight_tons": sum(line["weight_tons"] for line in lines),
        "purchase_cost": sum(line["purchase_cost"] for line in lines),
        "line_total": sum(line["line_total"] for line in lines),
    }


def settle_incoming(
    amount_fx: float,
    uah_per_unit: float,
    customs_percent: float,
    bank_type: str,
    bank_value: float,
    remainder_percent: float,
    shipment_uah: float = 0.0,
) -> dict[str, float]:
    """Поступление → затаможка и банк → минус отгрузка → процент от итоговой."""
    incoming_uah = ceil_int(fx_to_uah(amount_fx, uah_per_unit))
    customs_percent = max(float(customs_percent or 0), 0.0)
    remainder_percent = max(float(remainder_percent or 0), 0.0)
    shipment_uah = ceil_int(max(float(shipment_uah or 0), 0.0))
    bank_value = float(bank_value or 0)
    customs_amount = ceil_int(incoming_uah * customs_percent / 100.0)
    if bank_type == "%":
        bank_amount = ceil_int(incoming_uah * max(bank_value, 0.0) / 100.0)
    else:
        bank_amount = ceil_int(max(bank_value, 0.0))
    remainder = ceil_int(incoming_uah - customs_amount - bank_amount)
    after_shipment = ceil_int(remainder - shipment_uah)
    hold_amount = ceil_int(after_shipment * remainder_percent / 100.0)
    final_uah = ceil_int(after_shipment - hold_amount)
    return {
        "amount_fx": float(amount_fx or 0),
        "uah_per_unit": max(float(uah_per_unit or 0), 0.0),
        "incoming_uah": incoming_uah,
        "customs_percent": customs_percent,
        "customs_amount": customs_amount,
        "bank_type": bank_type,
        "bank_value": bank_value,
        "bank_amount": bank_amount,
        "remainder": remainder,
        "shipment_uah": shipment_uah,
        "after_shipment": after_shipment,
        "remainder_percent": remainder_percent,
        "hold_amount": hold_amount,
        "final_uah": final_uah,
    }


def order_totals(lines: list[dict[str, Any]]) -> dict[str, float]:
    return {
        "weight_tons": sum(line["weight_tons"] for line in lines),
        "purchase_cost": sum(line["purchase_cost"] for line in lines),
        "customs_cost": sum(line["customs_cost"] for line in lines),
        "transport_cost": sum(line.get("transport_cost", 0.0) for line in lines),
        "clearance_cost": sum(line.get("clearance_cost", 0.0) for line in lines),
        "overhead_cost": sum(line.get("overhead_cost", 0.0) for line in lines),
        "tax_amount": sum(line["tax_amount"] for line in lines),
        "cost": sum(line["cost"] for line in lines),
        "selling": sum(line["selling"] for line in lines),
        "profit": sum(line["profit"] for line in lines),
        "profit_net": sum(line.get("profit_net", 0.0) for line in lines),
        "cost_fx": sum(line.get("cost_fx", 0.0) for line in lines),
        "selling_fx": sum(line.get("selling_fx", 0.0) for line in lines),
        "profit_fx": sum(line.get("profit_fx", 0.0) for line in lines),
        "profit_net_fx": sum(line.get("profit_net_fx", 0.0) for line in lines),
    }
