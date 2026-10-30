"""Коммерческое предложение в PDF без внутренней себестоимости."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

NAVY = colors.HexColor("#1e4d7b")
NAVY_DARK = colors.HexColor("#16385a")
ROW_ALT = colors.HexColor("#eef3f8")
LINE = colors.HexColor("#c5d0dc")
TEXT = colors.HexColor("#1c2430")
MUTED = colors.HexColor("#5b6775")


def _register_fonts() -> tuple[str, str]:
    registered = set(pdfmetrics.getRegisteredFontNames())
    if "VspSans" in registered and "VspSans-Bold" in registered:
        return "VspSans", "VspSans-Bold"

    windows = Path(r"C:\Windows\Fonts")
    candidates = [
        (windows / "arial.ttf", windows / "arialbd.ttf"),
        (windows / "Arial.ttf", windows / "Arialbd.ttf"),
        (windows / "segoeui.ttf", windows / "segoeuib.ttf"),
        (windows / "tahoma.ttf", windows / "tahomabd.ttf"),
    ]
    for regular, bold in candidates:
        if regular.exists() and bold.exists():
            pdfmetrics.registerFont(TTFont("VspSans", str(regular)))
            pdfmetrics.registerFont(TTFont("VspSans-Bold", str(bold)))
            return "VspSans", "VspSans-Bold"
    return "Helvetica", "Helvetica-Bold"


CURRENCY_LABELS = {
    "UAH": "грн",
    "USD": "USD",
    "EUR": "EUR",
    "PLN": "PLN",
    "RUB": "₽",
}


def money(value: float, currency: str = "UAH") -> str:
    amount = int(round(float(value or 0)))
    formatted = f"{amount:,}".replace(",", " ")
    label = CURRENCY_LABELS.get(currency, currency)
    return f"{formatted} {label}"


def qty_fmt(value: float) -> str:
    amount = float(value or 0)
    if abs(amount - round(amount)) < 1e-9:
        return str(int(round(amount)))
    return f"{amount:.3f}".rstrip("0").rstrip(".")


def weight_fmt(tons: float) -> str:
    return f"{qty_fmt(tons)} т"


def pct_fmt(value: float) -> str:
    text = f"{float(value or 0):.2f}".rstrip("0").rstrip(".")
    return text if text else "0"


def build_quote_pdf(
    lines: list[dict[str, Any]],
    totals: dict[str, float],
    client_name: str = "",
    note: str = "",
    quote_currency: str = "USD",
) -> bytes:
    regular, bold = _register_fonts()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="Коммерческое предложение",
        author="Калькулятор ВСП",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "VspTitle",
        parent=styles["Title"],
        fontName=bold,
        fontSize=16,
        textColor=NAVY_DARK,
        alignment=TA_LEFT,
        spaceAfter=2 * mm,
        leading=20,
    )
    subtitle = ParagraphStyle(
        "VspSub",
        parent=styles["Normal"],
        fontName=regular,
        fontSize=9,
        textColor=MUTED,
        alignment=TA_LEFT,
        leading=13,
    )
    cell = ParagraphStyle(
        "VspCell",
        parent=styles["Normal"],
        fontName=regular,
        fontSize=8.5,
        textColor=TEXT,
        leading=11,
        alignment=TA_LEFT,
    )
    cell_right = ParagraphStyle("VspCellR", parent=cell, alignment=TA_RIGHT)
    cell_center = ParagraphStyle("VspCellC", parent=cell, alignment=TA_CENTER)
    head = ParagraphStyle(
        "VspHead",
        parent=cell,
        fontName=bold,
        textColor=colors.white,
        alignment=TA_CENTER,
        fontSize=8,
        leading=11,
    )
    footer = ParagraphStyle(
        "VspFoot",
        parent=subtitle,
        fontSize=8,
        alignment=TA_LEFT,
        spaceBefore=4 * mm,
    )

    story: list[Any] = []
    today = datetime.now().strftime("%d.%m.%Y")
    story.append(Paragraph("Коммерческое предложение", title_style))
    meta = f"Дата: {today}"
    if client_name.strip():
        meta += f"&nbsp;&nbsp;|&nbsp;&nbsp;Заказчик: {client_name.strip()}"
    story.append(Paragraph(meta, subtitle))
    story.append(
        Paragraph(
            f"Материалы верхнего строения пути (ВСП). "
            f"Цены указаны в {quote_currency} за предложенное количество.",
            subtitle,
        )
    )
    story.append(Spacer(1, 6 * mm))

    header = [
        Paragraph("Название", head),
        Paragraph("Состояние", head),
        Paragraph("Кол-во", head),
        Paragraph("Ед. изм.", head),
        Paragraph("Вес", head),
        Paragraph("Цена продажи", head),
        Paragraph("Итого", head),
    ]
    data: list[list[Any]] = [header]
    for line in lines:
        data.append(
            [
                Paragraph(str(line["name"]), cell),
                Paragraph(str(line["condition"]), cell_center),
                Paragraph(qty_fmt(line["quantity"]), cell_right),
                Paragraph(str(line["input_unit"]), cell_center),
                Paragraph(weight_fmt(line["weight_tons"]), cell_right),
                Paragraph(money(line["unit_selling_fx"], quote_currency), cell_right),
                Paragraph(money(line["selling_fx"], quote_currency), cell_right),
            ]
        )

    tot_left = ParagraphStyle("TotL", parent=cell, fontName=bold)
    tot_right = ParagraphStyle("TotR", parent=cell_right, fontName=bold)
    data.append(
        [
            Paragraph("Итого по предложению", tot_left),
            "",
            "",
            "",
            Paragraph(weight_fmt(totals["weight_tons"]), tot_right),
            "",
            Paragraph(money(totals["selling_fx"], quote_currency), tot_right),
        ]
    )

    table = Table(
        data,
        colWidths=[48 * mm, 20 * mm, 18 * mm, 18 * mm, 24 * mm, 26 * mm, 24 * mm],
        repeatRows=1,
    )
    style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), bold),
        ("ALIGN", (1, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#d9e4ef")),
        ("SPAN", (0, -1), (3, -1)),
    ]
    for i in range(1, len(data) - 1):
        if i % 2 == 0:
            style_commands.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
    table.setStyle(TableStyle(style_commands))
    story.append(table)

    if note.strip():
        story.append(Paragraph(f"Примечание: {note.strip()}", footer))
    story.append(
        Paragraph(
            "Документ является коммерческим предложением. Срок действия — 5 рабочих дней, если не указано иное.",
            footer,
        )
    )

    def _header_line(canvas, doc_):
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, A4[1] - 6 * mm, A4[0], 6 * mm, fill=1, stroke=0)
        canvas.setFillColor(NAVY)
        canvas.rect(0, 0, A4[0], 8 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont(regular, 7)
        canvas.drawString(16 * mm, 3 * mm, "Материалы ВСП · коммерческое предложение")
        canvas.drawRightString(A4[0] - 16 * mm, 3 * mm, f"стр. {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_header_line, onLaterPages=_header_line)
    return buffer.getvalue()


def build_settlement_pdf(
    lines: list[dict[str, Any]],
    shipment: dict[str, float],
    settlement: dict[str, float],
    quote_currency: str = "USD",
    note: str = "",
) -> bytes:
    regular, bold = _register_fonts()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="Расчёт поступления",
        author="Калькулятор ВСП",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "SetTitle",
        parent=styles["Title"],
        fontName=bold,
        fontSize=16,
        textColor=NAVY_DARK,
        alignment=TA_LEFT,
        spaceAfter=2 * mm,
        leading=20,
    )
    subtitle = ParagraphStyle(
        "SetSub",
        parent=styles["Normal"],
        fontName=regular,
        fontSize=9,
        textColor=MUTED,
        alignment=TA_LEFT,
        leading=13,
    )
    cell = ParagraphStyle(
        "SetCell",
        parent=styles["Normal"],
        fontName=regular,
        fontSize=8.5,
        textColor=TEXT,
        leading=11,
        alignment=TA_LEFT,
    )
    cell_right = ParagraphStyle("SetCellR", parent=cell, alignment=TA_RIGHT)
    cell_center = ParagraphStyle("SetCellC", parent=cell, alignment=TA_CENTER)
    head = ParagraphStyle(
        "SetHead",
        parent=cell,
        fontName=bold,
        textColor=colors.white,
        alignment=TA_CENTER,
        fontSize=8,
        leading=11,
    )
    footer = ParagraphStyle(
        "SetFoot",
        parent=subtitle,
        fontSize=8,
        alignment=TA_LEFT,
        spaceBefore=4 * mm,
    )
    tot_left = ParagraphStyle("SetTotL", parent=cell, fontName=bold)
    tot_right = ParagraphStyle("SetTotR", parent=cell_right, fontName=bold)
    section = ParagraphStyle(
        "SetSec",
        parent=cell,
        fontName=bold,
        fontSize=10,
        textColor=NAVY_DARK,
        spaceBefore=3 * mm,
        spaceAfter=2 * mm,
    )

    story: list[Any] = []
    today = datetime.now().strftime("%d.%m.%Y")
    story.append(Paragraph("Расчёт поступления", title_style))
    story.append(Paragraph(f"Дата: {today}", subtitle))
    story.append(
        Paragraph(
            "Сумма отгрузки — по ценам закупки из базы. "
            "После затаможки и комиссии банка вычитается отгрузка, "
            "затем процент от итоговой суммы.",
            subtitle,
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("Отгрузка", section))

    header = [
        Paragraph("Название", head),
        Paragraph("Состояние", head),
        Paragraph("Кол-во", head),
        Paragraph("Ед. изм.", head),
        Paragraph("Вес", head),
        Paragraph("Цена", head),
        Paragraph("Сумма", head),
    ]
    data: list[list[Any]] = [header]
    for line in lines:
        data.append(
            [
                Paragraph(str(line["name"]), cell),
                Paragraph(str(line["condition"]), cell_center),
                Paragraph(qty_fmt(line["quantity"]), cell_right),
                Paragraph(str(line["input_unit"]), cell_center),
                Paragraph(weight_fmt(line["weight_tons"]), cell_right),
                Paragraph(money(line["unit_price"], "UAH"), cell_right),
                Paragraph(money(line["line_total"], "UAH"), cell_right),
            ]
        )
    data.append(
        [
            Paragraph("Итого отгрузка", tot_left),
            "",
            "",
            "",
            Paragraph(weight_fmt(shipment["weight_tons"]), tot_right),
            "",
            Paragraph(money(shipment["line_total"], "UAH"), tot_right),
        ]
    )
    table = Table(
        data,
        colWidths=[48 * mm, 20 * mm, 18 * mm, 18 * mm, 24 * mm, 26 * mm, 24 * mm],
        repeatRows=1,
    )
    style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#d9e4ef")),
        ("SPAN", (0, -1), (3, -1)),
    ]
    for i in range(1, len(data) - 1):
        if i % 2 == 0:
            style_commands.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
    table.setStyle(TableStyle(style_commands))
    story.append(table)
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("Поступление и удержания", section))

    bank_label = (
        f"Комиссия банка {pct_fmt(settlement['bank_value'])}%"
        if settlement["bank_type"] == "%"
        else "Комиссия банка"
    )
    money_rows = [
        ("Зашло, валюта", money(settlement["amount_fx"], quote_currency)),
        (
            f"Курс на день расчёта (грн за 1 {quote_currency})",
            qty_fmt(settlement["uah_per_unit"]),
        ),
        ("Зашло, грн", money(settlement["incoming_uah"], "UAH")),
        (
            f"Затаможка {pct_fmt(settlement['customs_percent'])}%",
            "− " + money(settlement["customs_amount"], "UAH"),
        ),
        (bank_label, "− " + money(settlement["bank_amount"], "UAH")),
        ("После затаможки и банка", money(settlement["remainder"], "UAH")),
        ("Сумма отгрузки", "− " + money(settlement["shipment_uah"], "UAH")),
        ("Итоговая сумма", money(settlement["after_shipment"], "UAH")),
        (
            f"Процент от итоговой {pct_fmt(settlement['remainder_percent'])}%",
            "− " + money(settlement["hold_amount"], "UAH"),
        ),
        ("Конечная сумма", money(settlement["final_uah"], "UAH")),
    ]
    money_data: list[list[Any]] = []
    for label, value in money_rows:
        money_data.append(
            [
                Paragraph(label, cell),
                Paragraph(
                    value,
                    tot_right if label in ("Итоговая сумма", "Конечная сумма") else cell_right,
                ),
            ]
        )
    money_table = Table(money_data, colWidths=[118 * mm, 60 * mm])
    money_style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#d9e4ef")),
        ("FONTNAME", (0, -1), (-1, -1), bold),
        ("BACKGROUND", (0, 7), (-1, 7), colors.HexColor("#d9e4ef")),
        ("FONTNAME", (0, 7), (-1, 7), bold),
    ]
    for i in range(len(money_data)):
        if i % 2 == 1 and i != len(money_data) - 1:
            money_style.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
    money_table.setStyle(TableStyle(money_style))
    story.append(money_table)

    if note.strip():
        story.append(Paragraph(f"Примечание: {note.strip()}", footer))

    def _header_line(canvas, doc_):
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, A4[1] - 6 * mm, A4[0], 6 * mm, fill=1, stroke=0)
        canvas.setFillColor(NAVY)
        canvas.rect(0, 0, A4[0], 8 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont(regular, 7)
        canvas.drawString(16 * mm, 3 * mm, "Материалы ВСП · расчёт поступления")
        canvas.drawRightString(A4[0] - 16 * mm, 3 * mm, f"стр. {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_header_line, onLaterPages=_header_line)
    return buffer.getvalue()
