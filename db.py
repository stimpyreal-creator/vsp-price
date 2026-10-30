"""Локальная SQLite-база материалов ВСП."""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

DB_PATH = Path(__file__).resolve().parent / "vsp.db"
SEED_DB_PATH = Path(__file__).resolve().parent / "vsp_seed.db"
CATALOG_FLAG = "catalog_imported"

CONDITIONS = ("Новое", "БУ")
UNITS = ("Тонна", "Штука")
QUOTE_CURRENCIES = ("USD", "EUR", "PLN", "RUB")
DEFAULT_QUOTE_CURRENCY = "USD"
DEFAULT_UAH_PER_UNIT = 41.50

SEED_MATERIALS = [
    ("Рельс Р65, 12,5 м", "Новое", "Тонна", 62000.0, 812.5),
    ("Рельс Р65, 12,5 м", "БУ", "Тонна", 41000.0, 812.5),
    ("Рельс Р50, 12,5 м", "Новое", "Тонна", 58000.0, 625.0),
    ("Шпала железобетонная Ш1", "Новое", "Штука", 3200.0, 265.0),
    ("Шпала железобетонная Ш1", "БУ", "Штука", 1450.0, 265.0),
    ("Накладка 1Р65", "Новое", "Штука", 1850.0, 21.6),
    ("Подкладка КД-65", "Новое", "Штука", 420.0, 7.5),
    ("Костыль путевой 16×16×165", "Новое", "Штука", 28.0, 0.38),
    ("Болт стыковой М24×160", "Новое", "Штука", 95.0, 0.62),
    ("Скрепление АРС", "Новое", "Штука", 780.0, 4.2),
]


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _catalog_already_imported() -> bool:
    if not DB_PATH.exists():
        return False
    try:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?",
                (CATALOG_FLAG,),
            ).fetchone()
            return bool(row)
    except sqlite3.Error:
        return False


def _apply_seed_copy() -> None:
    if not SEED_DB_PATH.exists() or _catalog_already_imported():
        return
    shutil.copy2(SEED_DB_PATH, DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (CATALOG_FLAG, "1"),
        )
        conn.commit()


def init_db() -> None:
    _apply_seed_copy()
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                condition TEXT NOT NULL CHECK (condition IN ('Новое', 'БУ')),
                purchase_unit TEXT NOT NULL CHECK (purchase_unit IN ('Тонна', 'Штука')),
                purchase_price REAL NOT NULL CHECK (purchase_price >= 0),
                piece_weight_kg REAL NOT NULL CHECK (piece_weight_kg >= 0)
            )
            """
        )
        count = conn.execute("SELECT COUNT(*) FROM materials").fetchone()[0]
        if count == 0:
            conn.executemany(
                """
                INSERT INTO materials (name, condition, purchase_unit, purchase_price, piece_weight_kg)
                VALUES (?, ?, ?, ?, ?)
                """,
                SEED_MATERIALS,
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        existing = {
            row[0] for row in conn.execute("SELECT key FROM settings")
        }
        defaults = {
            "quote_currency": DEFAULT_QUOTE_CURRENCY,
            "uah_per_unit": str(DEFAULT_UAH_PER_UNIT),
        }
        for key, value in defaults.items():
            if key not in existing:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?)",
                    (key, value),
                )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                comment TEXT NOT NULL DEFAULT '',
                client_name TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                tax_percent REAL NOT NULL DEFAULT 0,
                customs_mode TEXT NOT NULL,
                customs_value REAL NOT NULL DEFAULT 0,
                quote_currency TEXT NOT NULL,
                uah_per_unit REAL NOT NULL,
                weight_tons REAL NOT NULL DEFAULT 0,
                selling_fx REAL NOT NULL DEFAULT 0,
                selling_uah REAL NOT NULL DEFAULT 0,
                profit_uah REAL NOT NULL DEFAULT 0,
                cost_uah REAL NOT NULL DEFAULT 0,
                items_json TEXT NOT NULL
            )
            """
        )
        conn.commit()


def get_settings() -> dict[str, Any]:
    with get_connection() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    raw = {row["key"]: row["value"] for row in rows}
    currency = str(raw.get("quote_currency", DEFAULT_QUOTE_CURRENCY)).upper()
    if currency not in QUOTE_CURRENCIES:
        currency = DEFAULT_QUOTE_CURRENCY
    try:
        rate = float(raw.get("uah_per_unit", DEFAULT_UAH_PER_UNIT))
    except (TypeError, ValueError):
        rate = DEFAULT_UAH_PER_UNIT
    if rate <= 0:
        rate = DEFAULT_UAH_PER_UNIT
    return {"quote_currency": currency, "uah_per_unit": rate}


def save_settings(quote_currency: str, uah_per_unit: float) -> None:
    currency = str(quote_currency).upper()
    if currency not in QUOTE_CURRENCIES:
        raise ValueError("Неизвестная валюта КП")
    rate = float(uah_per_unit)
    if rate <= 0:
        raise ValueError("Курс должен быть больше нуля")
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('quote_currency', ?)",
            (currency,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('uah_per_unit', ?)",
            (str(rate),),
        )
        conn.commit()


def list_materials() -> pd.DataFrame:
    with get_connection() as conn:
        df = pd.read_sql_query(
            """
            SELECT
                id AS ID,
                name AS "Название",
                condition AS "Состояние",
                purchase_unit AS "Единица закупки",
                purchase_price AS "Цена закупки",
                piece_weight_kg AS "Вес 1 шт, кг"
            FROM materials
            ORDER BY name, condition
            """,
            conn,
        )
    return df


def get_material(material_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM materials WHERE id = ?", (material_id,)
        ).fetchone()
    return dict(row) if row else None


def add_material(
    name: str,
    condition: str,
    purchase_unit: str,
    purchase_price: float,
    piece_weight_kg: float,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO materials (name, condition, purchase_unit, purchase_price, piece_weight_kg)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name.strip(), condition, purchase_unit, purchase_price, piece_weight_kg),
        )
        conn.commit()
        return int(cur.lastrowid)


def update_material(
    material_id: int,
    name: str,
    condition: str,
    purchase_unit: str,
    purchase_price: float,
    piece_weight_kg: float,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE materials
            SET name = ?, condition = ?, purchase_unit = ?, purchase_price = ?, piece_weight_kg = ?
            WHERE id = ?
            """,
            (
                name.strip(),
                condition,
                purchase_unit,
                purchase_price,
                piece_weight_kg,
                material_id,
            ),
        )
        conn.commit()


def delete_material(material_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM materials WHERE id = ?", (material_id,))
        conn.commit()


def replace_from_dataframe(df: pd.DataFrame) -> None:
    """Сохраняет правки из таблицы админки."""
    required = {"ID", "Название", "Состояние", "Единица закупки", "Цена закупки", "Вес 1 шт, кг"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Нет колонок: {', '.join(sorted(missing))}")

    with get_connection() as conn:
        existing_ids = {row[0] for row in conn.execute("SELECT id FROM materials")}
        incoming_ids = set()
        for _, row in df.iterrows():
            material_id = int(row["ID"])
            incoming_ids.add(material_id)
            conn.execute(
                """
                UPDATE materials
                SET name = ?, condition = ?, purchase_unit = ?, purchase_price = ?, piece_weight_kg = ?
                WHERE id = ?
                """,
                (
                    str(row["Название"]).strip(),
                    str(row["Состояние"]),
                    str(row["Единица закупки"]),
                    float(row["Цена закупки"]),
                    float(row["Вес 1 шт, кг"]),
                    material_id,
                ),
            )
        stale = existing_ids - incoming_ids
        for material_id in stale:
            conn.execute("DELETE FROM materials WHERE id = ?", (material_id,))
        conn.commit()


def save_order(
    comment: str,
    items: list[dict[str, Any]],
    totals: dict[str, float],
    tax_percent: float,
    customs_mode: str,
    customs_value: float,
    quote_currency: str,
    uah_per_unit: float,
    client_name: str = "",
    note: str = "",
) -> int:
    if not items:
        raise ValueError("Нельзя сохранить пустой заказ")
    payload = json.dumps(items, ensure_ascii=False)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO saved_orders (
                created_at, comment, client_name, note,
                tax_percent, customs_mode, customs_value,
                quote_currency, uah_per_unit,
                weight_tons, selling_fx, selling_uah, profit_uah, cost_uah,
                items_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                comment.strip(),
                client_name.strip(),
                note.strip(),
                float(tax_percent),
                customs_mode,
                float(customs_value),
                quote_currency,
                float(uah_per_unit),
                float(totals.get("weight_tons", 0)),
                float(totals.get("selling_fx", 0)),
                float(totals.get("selling", 0)),
                float(totals.get("profit", 0)),
                float(totals.get("cost", 0)),
                payload,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_saved_orders() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                id, created_at, comment, client_name, note,
                tax_percent, customs_mode, customs_value,
                quote_currency, uah_per_unit,
                weight_tons, selling_fx, selling_uah, profit_uah, cost_uah
            FROM saved_orders
            ORDER BY id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_saved_order(order_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM saved_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["items"] = json.loads(data["items_json"])
    return data


def delete_saved_order(order_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM saved_orders WHERE id = ?", (order_id,))
        conn.commit()
