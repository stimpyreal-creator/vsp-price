"""Калькулятор цен продажи материалов ВСП."""

from __future__ import annotations

import importlib
import inspect
from datetime import datetime

import pandas as pd
import streamlit as st

import calculations as calc_mod
from calculations import (
    ceil_int,
    order_totals,
    settle_incoming,
    shipment_lines,
    shipment_totals,
)
from db import (
    CONDITIONS,
    QUOTE_CURRENCIES,
    UNITS,
    add_material,
    delete_material,
    delete_saved_order,
    get_saved_order,
    get_settings,
    init_db,
    list_materials,
    list_saved_orders,
    replace_from_dataframe,
    save_order,
    save_settings,
)
from auth import require_login
from pdf_export import build_quote_pdf, build_settlement_pdf, money, qty_fmt

st.set_page_config(
    page_title="Калькулятор ВСП",
    page_icon="🛤️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
      .block-container {
        padding-top: 0.65rem;
        padding-bottom: 1.6rem;
        max-width: min(1180px, 100%);
        overflow-x: hidden;
      }
      [data-testid="stAppViewContainer"],
      [data-testid="stMain"],
      .main {
        overflow-x: hidden !important;
      }
      [data-testid="stSelectbox"],
      [data-testid="stSelectbox"] > div,
      [data-baseweb="select"] {
        max-width: 100% !important;
      }
      [data-baseweb="select"] > div {
        overflow: hidden;
      }
      div[data-testid="stDataFrame"],
      div[data-testid="stDataEditor"] {
        width: 100% !important;
        max-width: 100% !important;
        overflow-x: hidden !important;
      }
      div[data-testid="stDataFrame"] [data-testid="stDataFrameResizable"],
      div[data-testid="stDataFrame"] [class*="glideDataEditor"] {
        max-width: 100% !important;
        overflow-x: hidden !important;
      }
      div[data-testid="stExpander"] summary,
      div[data-testid="stExpander"] p {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      h1 { font-size: 1.22rem !important; letter-spacing: -0.02em; margin-bottom: 0.25rem !important; }
      h2, h3 { letter-spacing: -0.02em; font-size: 1.02rem !important; }
      [data-testid="stHeader"] { background: transparent; }
      div[data-testid="stMetric"] {
        background: #1a1f26;
        border: 1px solid #2c343e;
        border-radius: 8px;
        padding: 0.18rem 0.42rem 0.22rem;
      }
      div[data-testid="stMetric"] label {
        color: #8b97a6 !important;
        font-size: 0.66rem !important;
      }
      div[data-testid="stMetricValue"] {
        font-size: 0.9rem !important;
        line-height: 1.15 !important;
      }
      .stTabs [data-baseweb="tab-list"] { gap: 0.12rem; flex-wrap: wrap; }
      .stTabs [data-baseweb="tab"] {
        background: #1a1f26;
        border-radius: 8px 8px 0 0;
        padding: 0.28rem 0.65rem;
        font-size: 0.82rem;
      }
      [data-testid="stCaptionContainer"] p { font-size: 0.76rem !important; }
      .stButton button { min-height: 2rem; }
      .mini-row {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(10.5rem, 1fr));
        gap: 0.45rem;
        margin: 0.2rem 0 0.55rem;
      }
      .mini-card {
        background: #1a1f26;
        border: 1px solid #2c343e;
        border-radius: 8px;
        padding: 0.36rem 0.84rem 0.42rem;
        min-width: 0;
      }
      .mini-k {
        display: block;
        color: #8b97a6;
        font-size: 1.05rem;
        line-height: 1.2;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .mini-v {
        display: block;
        font-size: 1.6rem;
        font-weight: 600;
        line-height: 1.2;
        color: #d5dbe3;
      }
      @media (max-width: 768px) {
        .block-container { padding-left: 0.5rem; padding-right: 0.5rem; padding-top: 0.4rem; }
        h1 { font-size: 1.08rem !important; }
        div[data-testid="stMetricValue"] { font-size: 0.82rem !important; }
        .mini-row {
          grid-template-columns: 1fr 1fr;
          gap: 0.28rem;
          margin: 0.1rem 0 0.35rem;
        }
        .mini-card {
          padding: 0.16rem 0.38rem 0.18rem;
          border-radius: 6px;
        }
        .mini-k { font-size: 0.62rem; }
        .mini-v { font-size: 0.92rem; }
      }
    </style>
    """,
    unsafe_allow_html=True,
)

if not require_login():
    st.stop()

init_db()


def init_state() -> None:
    st.session_state.setdefault("order", [])
    st.session_state.setdefault("tax_percent", 8.0)
    st.session_state.setdefault("customs_mode", "На весь заказ")
    st.session_state.setdefault("customs_value", 6000.0)
    if not st.session_state.get("defaults_tax8_customs6000"):
        st.session_state.tax_percent = 8.0
        st.session_state.customs_value = 6000.0
        st.session_state.defaults_tax8_customs6000 = True
    st.session_state.setdefault("margin_deduct_percent", 20.0)
    if not st.session_state.get("defaults_margin_deduct20"):
        st.session_state.margin_deduct_percent = 20.0
        st.session_state.defaults_margin_deduct20 = True
    st.session_state.setdefault("default_margin_type", "%")
    st.session_state.setdefault("default_margin_value", 15.0)
    st.session_state.setdefault("materials_ver", 0)
    st.session_state.setdefault("kp_client", "")
    st.session_state.setdefault("kp_note", "")
    st.session_state.setdefault("opened_saved_id", None)
    st.session_state.setdefault("flash", None)
    stored = get_settings()
    st.session_state.setdefault("ship_order", [])
    st.session_state.setdefault("ship_fx_amount", 0.0)
    st.session_state.setdefault("ship_customs_percent", 7.0)
    st.session_state.setdefault("ship_bank_type", "грн")
    st.session_state.setdefault("ship_bank_value", 6000.0)
    if not st.session_state.get("defaults_ship_customs7_bank6000"):
        st.session_state.ship_customs_percent = 7.0
        st.session_state.ship_bank_type = "грн"
        st.session_state.ship_bank_value = 6000.0
        st.session_state.defaults_ship_customs7_bank6000 = True
    st.session_state.setdefault("ship_remainder_percent", 20.0)
    if not st.session_state.get("defaults_vat20"):
        st.session_state.ship_remainder_percent = 20.0
        st.session_state.defaults_vat20 = True
    st.session_state.setdefault("ship_note", "")
    st.session_state.setdefault("ship_fx_currency", stored["quote_currency"])
    st.session_state.setdefault("ship_fx_rate", stored["uah_per_unit"])
    st.session_state.setdefault("fx_currency", stored["quote_currency"])
    st.session_state.setdefault("fx_rate", stored["uah_per_unit"])
    if st.session_state.get("default_margin_type") == "Валюта":
        st.session_state.default_margin_type = "грн"
    apply_pending_saved_order()


def apply_pending_saved_order() -> None:
    payload = st.session_state.pop("pending_load_order", None)
    if not payload:
        return
    items = payload["items"]
    st.session_state.order = items
    st.session_state.tax_percent = float(payload["tax_percent"])
    st.session_state.margin_deduct_percent = float(payload.get("margin_deduct_percent", 20.0))
    st.session_state.customs_mode = payload["customs_mode"]
    st.session_state.customs_value = float(payload["customs_value"])
    st.session_state.fx_currency = payload["quote_currency"]
    st.session_state.fx_rate = float(payload["uah_per_unit"])
    st.session_state.kp_client = payload.get("client_name", "")
    st.session_state.kp_note = payload.get("note", "")
    st.session_state.opened_saved_id = payload["id"]
    for item in items:
        if item.get("margin_type") == "Валюта":
            item["margin_type"] = "грн"
        uid = item["uid"]
        st.session_state[f"mt_{uid}"] = item["margin_type"]
        qty = float(item["quantity"])
        st.session_state[f"qty_{uid}"] = qty
        st.session_state[qty_widget_key(f"qty_{uid}", item.get("input_unit", "Тонна"))] = qty
        if item["margin_type"] == "%":
            st.session_state[f"mv_pct_{uid}"] = float(item["margin_value"])
        else:
            st.session_state[f"mv_rub_{uid}"] = float(item["margin_value"])


def persist_fx() -> None:
    save_settings(st.session_state.fx_currency, float(st.session_state.fx_rate))


def material_label(row: pd.Series) -> str:
    return f"{int(row['ID'])} · {row['Название']} ({row['Состояние']})"


def pick_material_row(materials_df: pd.DataFrame, key: str | None = None) -> pd.Series:
    ids = [int(i) for i in materials_df["ID"].tolist()]
    kwargs: dict = {}
    if key:
        kwargs["key"] = key
    chosen = st.selectbox(
        "Материал из базы",
        ids,
        format_func=lambda i: clip_text(
            material_label(materials_df.loc[materials_df["ID"] == i].iloc[0]),
            48,
        ),
        label_visibility="collapsed",
        **kwargs,
    )
    return materials_df.loc[materials_df["ID"] == chosen].iloc[0]


def ensure_item_keys(item: dict, profit: float | None = None) -> None:
    uid = item["uid"]
    if item.get("margin_type") == "Валюта":
        item["margin_type"] = "грн"
    st.session_state.setdefault(f"mt_{uid}", item["margin_type"])
    if st.session_state.get(f"mt_{uid}") == "Валюта":
        st.session_state[f"mt_{uid}"] = "грн"
    st.session_state.setdefault(f"qty_{uid}", float(item["quantity"]))
    if item["margin_type"] == "%":
        st.session_state.setdefault(f"mv_pct_{uid}", float(item["margin_value"]))
    else:
        st.session_state.setdefault(f"mv_rub_{uid}", float(item["margin_value"]))
    if profit is not None:
        st.session_state.setdefault(f"mv_rub_{uid}", float(profit))
        st.session_state.setdefault(f"mv_pct_{uid}", 15.0)


def sync_order_from_widgets() -> None:
    """Подхватывает наценку и количество до пересчёта итогов."""
    for item in st.session_state.order:
        uid = item["uid"]
        if f"mt_{uid}" in st.session_state:
            item["margin_type"] = st.session_state[f"mt_{uid}"]
        qty = read_qty(f"qty_{uid}", item.get("input_unit", "Тонна"), item["quantity"])
        if qty is not None:
            item["quantity"] = qty
        if item.get("margin_type") in ("Валюта", "грн"):
            key = f"mv_rub_{uid}"
        else:
            key = f"mv_pct_{uid}"
        if key in st.session_state:
            item["margin_value"] = float(st.session_state[key])


def run_recompute(
    items: list,
    tax_percent: float,
    customs_value: float,
    customs_mode: str,
    uah_per_unit: float,
    margin_deduct_percent: float | None = None,
) -> list[dict]:
    global calc_mod
    fn = calc_mod.recompute_order
    params = inspect.signature(fn).parameters
    if "margin_deduct_percent" not in params:
        calc_mod = importlib.reload(calc_mod)
        fn = calc_mod.recompute_order
        params = inspect.signature(fn).parameters
    extra: dict = {}
    if "margin_deduct_percent" in params:
        extra["margin_deduct_percent"] = float(
            st.session_state.get("margin_deduct_percent", 20.0)
            if margin_deduct_percent is None
            else margin_deduct_percent
        )
    return fn(items, tax_percent, customs_value, customs_mode, uah_per_unit, **extra)


def computed_lines() -> list[dict]:
    return run_recompute(
        st.session_state.order,
        st.session_state.tax_percent,
        st.session_state.customs_value,
        st.session_state.customs_mode,
        st.session_state.fx_rate,
        st.session_state.margin_deduct_percent,
    )


def conversion_ok(input_unit: str, purchase_unit: str, piece_weight_kg: float) -> bool:
    if input_unit == purchase_unit:
        return True
    return float(piece_weight_kg) > 0


def _margin_deduct_share() -> float:
    return 1.0 - min(max(float(st.session_state.get("margin_deduct_percent", 20.0)), 0.0), 100.0) / 100.0


def margin_net_uah(row: dict) -> float:
    if "profit_net" in row:
        return float(row["profit_net"])
    return ceil_int(float(row.get("profit") or 0) * _margin_deduct_share())


def margin_net_fx(row: dict) -> float:
    if "profit_net_fx" in row:
        return float(row["profit_net_fx"])
    if "profit_fx" in row:
        return ceil_int(float(row.get("profit_fx") or 0) * _margin_deduct_share())
    return 0.0


def clip_text(text: object, limit: int = 36) -> str:
    raw = " ".join(str(text or "").split())
    if len(raw) <= limit:
        return raw
    return raw[: limit - 1].rstrip() + "…"


def show_fit_table(frame: pd.DataFrame) -> None:
    config: dict = {}
    if "Материал" in frame.columns:
        config["Материал"] = st.column_config.TextColumn("Материал", width="medium")
    for col in ("Состояние", "Ед.", "Кол-во", "Вес т"):
        if col in frame.columns:
            config[col] = st.column_config.TextColumn(col, width="small")
    display = frame.copy()
    if "Материал" in display.columns:
        display["Материал"] = display["Материал"].map(lambda v: clip_text(v, 36))
    st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        column_config=config,
    )


def compact_cards(items: list[tuple[str, str]]) -> None:
    cells = "".join(
        f'<div class="mini-card"><span class="mini-k">{label}</span>'
        f'<span class="mini-v">{value}</span></div>'
        for label, value in items
    )
    st.markdown(f'<div class="mini-row">{cells}</div>', unsafe_allow_html=True)


def qty_widget_key(base: str, unit: str) -> str:
    return f"{base}__pcs" if unit == "Штука" else f"{base}__ton"


def read_qty(base: str, unit: str, fallback: float | None = None) -> float | None:
    key = qty_widget_key(base, unit)
    if key in st.session_state:
        return float(st.session_state[key])
    if base in st.session_state:
        return float(st.session_state[base])
    return fallback


def quantity_input(label: str, *, base_key: str, unit: str, container=None, value: float | None = None):
    target = container if container is not None else st
    pcs = unit == "Штука"
    wkey = qty_widget_key(base_key, unit)
    if wkey not in st.session_state:
        other = qty_widget_key(base_key, "Тонна" if pcs else "Штука")
        raw = st.session_state.get(
            other,
            st.session_state.get(base_key, 1.0 if value is None else value),
        )
        st.session_state[wkey] = float(int(round(float(raw)))) if pcs else float(raw)
    return target.number_input(
        label,
        min_value=0.0,
        step=1.0 if pcs else 0.1,
        format="%.0f" if pcs else "%.3f",
        key=wkey,
    )


def sync_ship_from_widgets() -> None:
    for item in st.session_state.ship_order:
        uid = item["uid"]
        if f"sunit_{uid}" in st.session_state:
            item["input_unit"] = st.session_state[f"sunit_{uid}"]
        qty = read_qty(f"sqty_{uid}", item.get("input_unit", "Тонна"), item["quantity"])
        if qty is not None:
            item["quantity"] = qty


init_state()

tab_admin, tab_calc, tab_ship, tab_saved = st.tabs(
    ["База материалов", "Калькулятор заказа", "Расчёт поступления", "Сохранённые расчёты"]
)

with tab_admin:
    stored = get_settings()
    with st.expander("Курс валюты для КП", expanded=False):
        with st.form("fx_settings"):
            f1, f2 = st.columns(2)
            fx_cur = f1.selectbox(
                "Валюта коммерческого предложения",
                list(QUOTE_CURRENCIES),
                index=list(QUOTE_CURRENCIES).index(stored["quote_currency"]),
            )
            fx_rate = f2.number_input(
                f"Курс: грн за 1 {fx_cur}",
                min_value=0.0001,
                value=float(stored["uah_per_unit"]),
                step=0.01,
                format="%.4f",
                help="Например 41.50 означает: 1 USD = 41.50 грн. Цена КП = сумма в грн / курс.",
            )
            if st.form_submit_button("Сохранить курс в базу", width="stretch"):
                save_settings(fx_cur, fx_rate)
                st.session_state.fx_currency = fx_cur
                st.session_state.fx_rate = float(fx_rate)
                st.success(f"Курс сохранён: 1 {fx_cur} = {fx_rate:.4f} грн.")
                st.rerun()

    materials_df = list_materials()

    with st.expander("Добавить материал", expanded=materials_df.empty):
        with st.form("add_material", clear_on_submit=True):
            c1, c2 = st.columns([2, 1])
            name = c1.text_input("Название")
            condition = c2.selectbox("Состояние", CONDITIONS)
            c3, c4, c5 = st.columns(3)
            unit = c3.selectbox("Единица закупки", UNITS)
            price = c4.number_input("Цена закупки, грн", min_value=0.0, step=10.0, format="%.0f")
            weight = c5.number_input("Вес 1 штуки, кг", min_value=0.0, step=0.1, format="%.3f")
            submitted = st.form_submit_button("Добавить в базу", width="stretch")
            if submitted:
                if not name.strip():
                    st.error("Укажите название материала.")
                elif unit == "Штука" and weight <= 0:
                    st.error("Для штучной закупки укажите вес 1 штуки — он нужен для пересчёта в тонны.")
                else:
                    add_material(name, condition, unit, price, weight)
                    st.session_state.materials_ver += 1
                    st.success("Материал сохранён.")
                    st.rerun()

    if materials_df.empty:
        st.info("База пуста. Добавьте первую позицию.")
    else:
        st.caption("Правите название, состояние, единицу, цену и вес в таблице, затем сохраните.")
        edited = st.data_editor(
            materials_df,
            hide_index=True,
            width="stretch",
            num_rows="fixed",
            column_config={
                "ID": st.column_config.NumberColumn("ID", disabled=True, width="small"),
                "Название": st.column_config.TextColumn("Название", required=True, width="large"),
                "Состояние": st.column_config.SelectboxColumn(
                    "Состояние", options=list(CONDITIONS), required=True
                ),
                "Единица закупки": st.column_config.SelectboxColumn(
                    "Единица закупки", options=list(UNITS), required=True
                ),
                "Цена закупки": st.column_config.NumberColumn(
                    "Цена закупки, грн",
                    min_value=0,
                    format="%d грн",
                    help="За 1 тонну или за 1 штуку — по единице закупки, в гривнах",
                ),
                "Вес 1 шт, кг": st.column_config.NumberColumn(
                    "Вес 1 шт, кг", min_value=0, format="%.3f"
                ),
            },
            key=f"materials_editor_{st.session_state.materials_ver}",
        )

        if st.button("Сохранить изменения в таблице", type="primary", width="stretch"):
            try:
                invalid = edited[
                    (edited["Единица закупки"] == "Штука") & (edited["Вес 1 шт, кг"] <= 0)
                ]
                if not edited["Название"].astype(str).str.strip().all():
                    st.error("Название не должно быть пустым.")
                elif not invalid.empty:
                    st.error("У штучных позиций вес 1 штуки должен быть больше нуля.")
                else:
                    replace_from_dataframe(edited)
                    st.session_state.materials_ver += 1
                    st.success("База обновлена.")
                    st.rerun()
            except Exception as exc:
                st.error(f"Не удалось сохранить: {exc}")

        st.markdown("**Удаление**")
        chosen = st.selectbox(
            "Материал",
            options=edited["ID"].tolist(),
            format_func=lambda i: material_label(edited.loc[edited["ID"] == i].iloc[0]),
            label_visibility="collapsed",
        )
        if st.button("Удалить выбранный", width="stretch"):
            delete_material(int(chosen))
            st.session_state.materials_ver += 1
            st.success("Позиция удалена.")
            st.rerun()

with tab_calc:
    materials_df = list_materials()
    if materials_df.empty:
        st.warning("Сначала добавьте материалы на вкладке «База материалов».")
    else:
        if st.session_state.flash:
            st.success(st.session_state.flash)
            st.session_state.flash = None
        with st.expander("Параметры расчёта заказа", expanded=False):
            fx1, fx2 = st.columns(2)
            fx1.selectbox(
                "Валюта КП",
                list(QUOTE_CURRENCIES),
                key="fx_currency",
                help="Отпускные цены для клиента и PDF считаются в этой валюте.",
            )
            fx2.number_input(
                f"Курс: грн за 1 {st.session_state.fx_currency}",
                min_value=0.0001,
                step=0.01,
                format="%.4f",
                key="fx_rate",
                help="Цена КП = себестоимость и наценка в грн, делённые на курс.",
            )
            persist_fx()
            st.caption(
                f"1 {st.session_state.fx_currency} = {st.session_state.fx_rate:.4f} грн. "
                "Курс пишется в базу и сразу пересчитывает КП."
            )

            p1, p2, p3 = st.columns(3)
            p1.number_input(
                "Налог, %",
                min_value=0.0,
                max_value=100.0,
                step=0.5,
                key="tax_percent",
                help="Начисляется на сумму закупки и затаможки позиции.",
            )
            p2.radio(
                "Затаможка",
                ["На весь заказ", "За тонну"],
                horizontal=True,
                key="customs_mode",
            )
            customs_label = (
                "Стоимость затаможки, грн (весь заказ)"
                if st.session_state.customs_mode == "На весь заказ"
                else "Стоимость затаможки, грн за тонну"
            )
            p3.number_input(
                customs_label,
                min_value=0.0,
                step=10.0,
                format="%.0f",
                key="customs_value",
            )
            st.number_input(
                "Вычет от маржи, %",
                min_value=0.0,
                max_value=100.0,
                step=0.5,
                format="%.1f",
                key="margin_deduct_percent",
                help="Снимается с маржи. По умолчанию 20%.",
            )

            m1, m2 = st.columns(2)
            m1.radio(
                "Наценка по умолчанию для новых позиций",
                ["%", "грн"],
                horizontal=True,
                key="default_margin_type",
                help="«%» — доля от себестоимости в грн. «грн» — фиксированная прибыль в гривнах.",
            )
            margin_caption = (
                "Наценка, %"
                if st.session_state.default_margin_type == "%"
                else "Наценка, грн (чистая маржа позиции)"
            )
            m2.number_input(
                margin_caption,
                step=1.0,
                format="%.0f" if st.session_state.default_margin_type == "грн" else "%.2f",
                key="default_margin_value",
            )

        sync_order_from_widgets()

        selected_row = pick_material_row(materials_df, key="calc_material_id")
        purchase_unit = str(selected_row["Единица закупки"])
        unit_word = "тонну" if purchase_unit == "Тонна" else "штуку"
        purchase_price = float(selected_row["Цена закупки"])
        piece_weight = float(selected_row["Вес 1 шт, кг"])
        if purchase_unit == "Штука":
            piece_price = purchase_price
        elif piece_weight > 0:
            piece_price = ceil_int(purchase_price * piece_weight / 1000.0)
        else:
            piece_price = 0.0
        st.caption(
            f"Цена закупки: {money(purchase_price, 'UAH')} за 1 {unit_word}. "
            f"{money(piece_price, 'UAH')} за 1 шт. "
            f"Вес 1 шт: {qty_fmt(piece_weight)} кг"
        )

        unit_key = f"add_unit_{int(selected_row['ID'])}"
        st.session_state.setdefault(unit_key, purchase_unit)
        q1, q2 = st.columns([1.2, 1])
        add_unit = q2.radio("Ввод количества", list(UNITS), horizontal=True, key=unit_key)
        add_qty = quantity_input(
            "Количество",
            base_key=f"add_qty_{int(selected_row['ID'])}",
            unit=add_unit,
            container=q1,
        )

        draft = {
            "quantity": add_qty,
            "input_unit": add_unit,
            "purchase_unit": str(selected_row["Единица закупки"]),
            "purchase_price": float(selected_row["Цена закупки"]),
            "piece_weight_kg": float(selected_row["Вес 1 шт, кг"]),
            "margin_type": st.session_state.default_margin_type,
            "margin_value": st.session_state.default_margin_value,
            "name": str(selected_row["Название"]),
            "condition": str(selected_row["Состояние"]),
        }
        can_convert = conversion_ok(
            add_unit,
            str(selected_row["Единица закупки"]),
            float(selected_row["Вес 1 шт, кг"]),
        )
        if not can_convert:
            st.error("Нельзя пересчитать единицы: в карточке материала не задан вес 1 штуки.")
        else:
            preview_lines = run_recompute(
                [*st.session_state.order, draft],
                st.session_state.tax_percent,
                st.session_state.customs_value,
                st.session_state.customs_mode,
                st.session_state.fx_rate,
                st.session_state.margin_deduct_percent,
            )
            preview = preview_lines[-1]
            order_now = order_totals(computed_lines()) if st.session_state.order else None
            compact_cards(
                [
                    ("Вес позиции", f"{qty_fmt(preview['weight_tons'])} т"),
                    (
                        "Вес заказа сейчас",
                        f"{qty_fmt(order_now['weight_tons'])} т" if order_now else "0 т",
                    ),
                    (
                        "Вес заказа с этой позицией",
                        f"{qty_fmt(order_totals(preview_lines)['weight_tons'])} т",
                    ),
                ]
            )
            if add_unit != str(selected_row["Единица закупки"]):
                st.caption(
                    f"Пересчёт: {qty_fmt(preview['pieces'])} шт ≈ {qty_fmt(preview['weight_tons'])} т, "
                    f"закупка {money(preview['purchase_cost'], 'UAH')}."
                )

        if st.button("Добавить в заказ", type="primary", width="stretch"):
            if add_qty <= 0:
                st.error("Количество должно быть больше нуля.")
            elif not can_convert:
                st.error("Сначала укажите вес 1 штуки в базе материалов.")
            else:
                new_item = {
                    "uid": datetime.now().timestamp(),
                    "material_id": int(selected_row["ID"]),
                    "name": str(selected_row["Название"]),
                    "condition": str(selected_row["Состояние"]),
                    "purchase_unit": str(selected_row["Единица закупки"]),
                    "purchase_price": float(selected_row["Цена закупки"]),
                    "piece_weight_kg": float(selected_row["Вес 1 шт, кг"]),
                    "quantity": float(add_qty),
                    "input_unit": add_unit,
                    "margin_type": st.session_state.default_margin_type,
                    "margin_value": float(st.session_state.default_margin_value),
                }
                st.session_state.order.append(new_item)
                ensure_item_keys(new_item)
                st.rerun()

        st.divider()
        st.subheader("Текущий заказ")
        lines = computed_lines()
        if not lines:
            st.info("Заказ пуст. Добавьте хотя бы одну позицию.")
        else:
            totals = order_totals(lines)
            quote = st.session_state.fx_currency
            compact_cards(
                [
                    ("Вес заказа", f"{qty_fmt(totals['weight_tons'])} т"),
                    ("Полная себестоимость", money(totals["cost"], "UAH")),
                    ("Итоговая цена продажи (КП)", money(totals["selling_fx"], quote)),
                    ("Маржа", money(margin_net_uah(totals), "UAH")),
                ]
            )
            st.caption(
                f"Маржа в валюте КП: {money(margin_net_fx(totals), quote)}. "
                f"Курс 1 {quote} = {st.session_state.fx_rate:.4f} грн."
            )

            table = pd.DataFrame(
                [
                    {
                        "Материал": line["name"],
                        "Состояние": line["condition"],
                        "Кол-во": qty_fmt(line["quantity"]),
                        "Ед.": line["input_unit"],
                        "Вес т": qty_fmt(line["weight_tons"]),
                        "Себест грн": money(line["cost"], "UAH"),
                        f"Цена ед {quote}": money(line["unit_selling_fx"], quote),
                        f"Продажа {quote}": money(line["selling_fx"], quote),
                        "Маржа": money(margin_net_uah(line), "UAH"),
                    }
                    for line in lines
                ]
            ).astype(str)
            show_fit_table(table)

            remove_uid = None
            for line in lines:
                ensure_item_keys(line, profit=line["profit"])
                title = (
                    f"{clip_text(line['name'], 40)} · {line['condition']} · "
                    f"{qty_fmt(line['quantity'])} {line['input_unit']}"
                )
                with st.expander(title, expanded=False):
                    c1, c2, c3 = st.columns(3)
                    c1.radio(
                        "Тип наценки",
                        ["%", "грн"],
                        key=f"mt_{line['uid']}",
                        horizontal=True,
                    )
                    if st.session_state[f"mt_{line['uid']}"] == "%":
                        c2.number_input(
                            "Наценка, %",
                            step=0.5,
                            key=f"mv_pct_{line['uid']}",
                        )
                    else:
                        c2.number_input(
                            "Чистая маржа, грн",
                            step=10.0,
                            format="%.0f",
                            key=f"mv_rub_{line['uid']}",
                            help="Цена продажи в грн = себестоимость + эта сумма, затем перевод в валюту КП.",
                        )
                    quantity_input(
                        "Количество",
                        base_key=f"qty_{line['uid']}",
                        unit=str(line["input_unit"]),
                        container=c3,
                        value=float(line["quantity"]),
                    )
                    d1, d2, d3 = st.columns(3)
                    d1.write(f"Вес: **{qty_fmt(line['weight_tons'])} т**")
                    d2.write(f"Себестоимость: **{money(line['cost'], 'UAH')}**")
                    d3.write(
                        f"Продажа КП: **{money(line['selling_fx'], st.session_state.fx_currency)}**"
                    )
                    if st.button("Убрать из заказа", key=f"del_{line['uid']}"):
                        remove_uid = line["uid"]

            if remove_uid is not None:
                st.session_state.order = [x for x in st.session_state.order if x["uid"] != remove_uid]
                st.rerun()

            st.divider()
            if st.session_state.opened_saved_id:
                st.info(
                    f"Открыт сохранённый расчёт №{st.session_state.opened_saved_id}. "
                    "После правок нажмите «Сохранить расчёт», чтобы записать новую копию."
                )
            e1, e2 = st.columns(2)
            e1.text_input("Заказчик (в PDF)", placeholder="Необязательно", key="kp_client")
            e2.text_input("Примечание (в PDF)", placeholder="Необязательно", key="kp_note")

            pdf_bytes = build_quote_pdf(
                lines,
                totals,
                client_name=st.session_state.kp_client,
                note=st.session_state.kp_note,
                quote_currency=st.session_state.fx_currency,
            )
            file_name = f"KP_VSP_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
            st.download_button(
                "Экспорт в PDF",
                data=pdf_bytes,
                file_name=file_name,
                mime="application/pdf",
                type="primary",
                width="stretch",
            )

            with st.form("save_calc"):
                comment = st.text_area(
                    "Комментарий к расчёту",
                    placeholder="Например: КП для ООО «Путь», рельс Р65, май 2026",
                    height=80,
                )
                save_clicked = st.form_submit_button(
                    "Сохранить расчёт", type="primary", width="stretch"
                )
            if save_clicked:
                comment = str(comment or "").strip()
                if not comment:
                    st.error("Напишите комментарий — по нему потом найдёте расчёт.")
                else:
                    sync_order_from_widgets()
                    saved_lines = computed_lines()
                    saved_totals = order_totals(saved_lines)
                    order_id = save_order(
                        comment=comment,
                        items=list(st.session_state.order),
                        totals=saved_totals,
                        tax_percent=st.session_state.tax_percent,
                        customs_mode=st.session_state.customs_mode,
                        customs_value=st.session_state.customs_value,
                        quote_currency=st.session_state.fx_currency,
                        uah_per_unit=st.session_state.fx_rate,
                        client_name=st.session_state.kp_client,
                        note=st.session_state.kp_note,
                        margin_deduct_percent=st.session_state.margin_deduct_percent,
                    )
                    st.session_state.opened_saved_id = order_id
                    st.session_state.flash = f"Расчёт сохранён под №{order_id}."
                    st.rerun()

            if st.button("Очистить заказ", width="stretch"):
                st.session_state.order = []
                st.session_state.opened_saved_id = None
                st.rerun()

with tab_ship:
    materials_df = list_materials()
    if materials_df.empty:
        st.warning("Сначала добавьте материалы на вкладке «База материалов».")
    else:
        sync_ship_from_widgets()
        selected_row = pick_material_row(materials_df, key="ship_material_id")
        purchase_unit = str(selected_row["Единица закупки"])
        unit_key = f"ship_add_unit_{int(selected_row['ID'])}"
        st.session_state.setdefault(unit_key, purchase_unit)
        q1, q2 = st.columns([1.2, 1])
        add_unit = q2.radio("Ввод количества", list(UNITS), horizontal=True, key=unit_key)
        add_qty = quantity_input(
            "Количество",
            base_key=f"ship_add_qty_{int(selected_row['ID'])}",
            unit=add_unit,
            container=q1,
        )
        can_convert = conversion_ok(
            add_unit,
            purchase_unit,
            float(selected_row["Вес 1 шт, кг"]),
        )
        if not can_convert:
            st.error("Нельзя пересчитать единицы: в карточке материала не задан вес 1 штуки.")
        if st.button("Добавить в отгрузку", type="primary", width="stretch"):
            if add_qty <= 0:
                st.error("Количество должно быть больше нуля.")
            elif not can_convert:
                st.error("Сначала укажите вес 1 штуки в базе материалов.")
            else:
                new_item = {
                    "uid": datetime.now().timestamp(),
                    "material_id": int(selected_row["ID"]),
                    "name": str(selected_row["Название"]),
                    "condition": str(selected_row["Состояние"]),
                    "purchase_unit": purchase_unit,
                    "purchase_price": float(selected_row["Цена закупки"]),
                    "piece_weight_kg": float(selected_row["Вес 1 шт, кг"]),
                    "quantity": float(add_qty),
                    "input_unit": add_unit,
                }
                st.session_state.ship_order.append(new_item)
                st.rerun()

        lines = shipment_lines(st.session_state.ship_order)
        if not lines:
            st.info("Добавьте хотя бы одну позицию отгрузки.")
        else:
            totals = shipment_totals(lines)
            table = pd.DataFrame(
                [
                    {
                        "Материал": line["name"],
                        "Состояние": line["condition"],
                        "Кол-во": qty_fmt(line["quantity"]),
                        "Ед.": line["input_unit"],
                        "Вес т": qty_fmt(line["weight_tons"]),
                        "Цена грн": money(line["unit_price"], "UAH"),
                        "Сумма грн": money(line["line_total"], "UAH"),
                    }
                    for line in lines
                ]
            ).astype(str)
            show_fit_table(table)
            compact_cards(
                [
                    ("Вес отгрузки", f"{qty_fmt(totals['weight_tons'])} т"),
                    ("Сумма отгрузки", money(totals["line_total"], "UAH")),
                ]
            )

            remove_uid = None
            for line in lines:
                uid = line["uid"]
                st.session_state.setdefault(f"sqty_{uid}", float(line["quantity"]))
                st.session_state.setdefault(f"sunit_{uid}", line["input_unit"])
                with st.expander(
                    f"{line['name']} · {line['condition']} · {line['quantity']} {line['input_unit']}",
                    expanded=False,
                ):
                    c1, c2 = st.columns(2)
                    ship_unit = c2.radio(
                        "Единица",
                        list(UNITS),
                        horizontal=True,
                        key=f"sunit_{uid}",
                    )
                    quantity_input(
                        "Количество",
                        base_key=f"sqty_{uid}",
                        unit=ship_unit,
                        container=c1,
                        value=float(line["quantity"]),
                    )
                    st.write(f"Сумма: **{money(line['line_total'], 'UAH')}**")
                    if st.button("Убрать", key=f"sdel_{uid}"):
                        remove_uid = uid
            if remove_uid is not None:
                st.session_state.ship_order = [
                    x for x in st.session_state.ship_order if x["uid"] != remove_uid
                ]
                st.rerun()

        st.divider()
        st.markdown("**Поступление валюты**")
        p1, p2, p3 = st.columns(3)
        p1.selectbox("Валюта, которая зашла", list(QUOTE_CURRENCIES), key="ship_fx_currency")
        p2.number_input(
            f"Сумма, {st.session_state.ship_fx_currency}",
            min_value=0.0,
            step=100.0,
            format="%.2f",
            key="ship_fx_amount",
        )
        p3.number_input(
            f"Курс: грн за 1 {st.session_state.ship_fx_currency}",
            min_value=0.0001,
            step=0.01,
            format="%.4f",
            key="ship_fx_rate",
            help="Курс на день расчёта. Зашло в грн = сумма в валюте × курс.",
        )

        d1, d2, d3 = st.columns(3)
        d1.number_input(
            "Затаможка, %",
            min_value=0.0,
            max_value=100.0,
            step=0.1,
            format="%.2f",
            key="ship_customs_percent",
            help="Процент снимается с суммы в гривнах, которая зашла по курсу.",
        )
        d2.radio(
            "Комиссия банка",
            ["грн", "%"],
            horizontal=True,
            key="ship_bank_type",
        )
        bank_label = (
            "Комиссия банка, %"
            if st.session_state.ship_bank_type == "%"
            else "Комиссия банка, грн"
        )
        d3.number_input(
            bank_label,
            min_value=0.0,
            step=1.0,
            format="%.2f",
            key="ship_bank_value",
        )

        ship_sum = shipment_totals(lines)["line_total"] if lines else 0.0
        settlement = settle_incoming(
            st.session_state.ship_fx_amount,
            st.session_state.ship_fx_rate,
            st.session_state.ship_customs_percent,
            st.session_state.ship_bank_type,
            st.session_state.ship_bank_value,
            0.0,
            ship_sum,
        )
        compact_cards(
            [
                ("Зашло, грн", money(settlement["incoming_uah"], "UAH")),
                ("После затаможки и банка", money(settlement["remainder"], "UAH")),
                ("Сумма отгрузки", money(settlement["shipment_uah"], "UAH")),
                ("Итоговая сумма", money(settlement["after_shipment"], "UAH")),
            ]
        )
        st.caption(
            f"Затаможка: {money(settlement['customs_amount'], 'UAH')}. "
            f"Комиссия банка: {money(settlement['bank_amount'], 'UAH')}. "
            "Итоговая = после затаможки и банка минус отгрузка."
        )

        st.number_input(
            "НДС 20%",
            min_value=0.0,
            max_value=100.0,
            step=0.1,
            format="%.2f",
            key="ship_remainder_percent",
            help="НДС снимается с итоговой суммы после вычета отгрузки. По умолчанию 20%.",
        )
        settlement = settle_incoming(
            st.session_state.ship_fx_amount,
            st.session_state.ship_fx_rate,
            st.session_state.ship_customs_percent,
            st.session_state.ship_bank_type,
            st.session_state.ship_bank_value,
            st.session_state.ship_remainder_percent,
            ship_sum,
        )
        compact_cards(
            [
                ("НДС", money(settlement["hold_amount"], "UAH")),
                ("Сумма без НДС", money(settlement["final_uah"], "UAH")),
            ]
        )

        st.text_input("Примечание (в PDF)", key="ship_note", placeholder="Необязательно")
        ship_pdf = build_settlement_pdf(
            lines,
            shipment_totals(lines) if lines else {"weight_tons": 0.0, "line_total": 0.0},
            settlement,
            quote_currency=st.session_state.ship_fx_currency,
            note=st.session_state.ship_note,
        )
        st.download_button(
            "Экспорт расчёта в PDF",
            data=ship_pdf,
            file_name=f"Postuplenie_VSP_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf",
            type="primary",
            width="stretch",
        )
        if st.button("Очистить отгрузку", width="stretch"):
            st.session_state.ship_order = []
            st.rerun()

with tab_saved:
    st.subheader("Сохранённые расчёты")
    st.caption("Откройте расчёт, чтобы снова увидеть позиции, маржу и PDF.")
    saved_rows = list_saved_orders()
    if not saved_rows:
        st.info("Пока нет сохранённых расчётов. Посчитайте заказ и нажмите «Сохранить расчёт».")
    else:
        for row in saved_rows:
            title = f"№{row['id']} · {row['created_at']} · {row['comment']}"
            with st.expander(title, expanded=False):
                c1, c2, c3 = st.columns(3)
                c1.write(f"Вес: **{qty_fmt(row['weight_tons'])} т**")
                c2.write(
                    f"КП: **{money(row['selling_fx'], row['quote_currency'])}**"
                )
                c3.write(f"Маржа: **{money(row['profit_uah'], 'UAH')}**")
                if row["client_name"]:
                    st.caption(f"Заказчик: {row['client_name']}")
                if row["note"]:
                    st.caption(f"Примечание в PDF: {row['note']}")
                st.caption(
                    f"Налог {row['tax_percent']:.1f}%, затаможка: {row['customs_mode']}, "
                    f"{money(row['customs_value'], 'UAH')}. "
                    f"Курс: 1 {row['quote_currency']} = {row['uah_per_unit']:.4f} грн."
                )
                full = get_saved_order(int(row["id"]))
                if full:
                    saved_lines = run_recompute(
                        full["items"],
                        full["tax_percent"],
                        full["customs_value"],
                        full["customs_mode"],
                        full["uah_per_unit"],
                        float(full.get("margin_deduct_percent", 20.0)),
                    )
                    preview = pd.DataFrame(
                        [
                            {
                                "Материал": line["name"],
                                "Состояние": line["condition"],
                                "Кол-во": qty_fmt(line["quantity"]),
                                "Ед.": line["input_unit"],
                                "Вес т": qty_fmt(line["weight_tons"]),
                                f"Продажа {full['quote_currency']}": money(
                                    line["selling_fx"], full["quote_currency"]
                                ),
                                "Маржа": money(margin_net_uah(line), "UAH"),
                            }
                            for line in saved_lines
                        ]
                    ).astype(str)
                    show_fit_table(preview)
                    saved_pdf = build_quote_pdf(
                        saved_lines,
                        order_totals(saved_lines),
                        client_name=full["client_name"],
                        note=full["note"],
                        quote_currency=full["quote_currency"],
                    )
                    st.download_button(
                        "Скачать PDF этого расчёта",
                        data=saved_pdf,
                        file_name=f"KP_VSP_{full['id']}.pdf",
                        mime="application/pdf",
                        key=f"pdf_{row['id']}",
                        width="stretch",
                    )
                b1, b2 = st.columns(2)
                if b1.button("Открыть в калькуляторе", key=f"open_{row['id']}", width="stretch"):
                    if full is None:
                        st.error("Расчёт не найден.")
                    else:
                        st.session_state.pending_load_order = full
                        st.rerun()
                if b2.button("Удалить", key=f"forget_{row['id']}", width="stretch"):
                    delete_saved_order(int(row["id"]))
                    if st.session_state.opened_saved_id == row["id"]:
                        st.session_state.opened_saved_id = None
                    st.rerun()
