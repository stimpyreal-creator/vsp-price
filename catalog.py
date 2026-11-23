"""Каталог материалов, который переживает перезапуск Streamlit Cloud через GitHub."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

CATALOG_HASH_KEY = "catalog_json_hash"
DEFAULT_REPO = "stimpyreal-creator/vsp-price"
DEFAULT_BRANCH = "main"


def catalog_path() -> Path:
    from db import DB_PATH

    return Path(DB_PATH).resolve().parent / "catalog.json"


def catalog_text_and_digest(payload: dict[str, Any]) -> tuple[str, str]:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return text, digest


def payload_from_db() -> dict[str, Any]:
    from db import get_connection

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, name, condition, purchase_unit, purchase_price, piece_weight_kg
            FROM materials
            ORDER BY id
            """
        ).fetchall()
    materials = [
        {
            "id": int(row["id"]),
            "name": str(row["name"]),
            "condition": str(row["condition"]),
            "purchase_unit": str(row["purchase_unit"]),
            "purchase_price": float(row["purchase_price"]),
            "piece_weight_kg": float(row["piece_weight_kg"]),
        }
        for row in rows
    ]
    return {"materials": materials}


def write_catalog_file(payload: dict[str, Any] | None = None) -> tuple[str, str]:
    data = payload if payload is not None else payload_from_db()
    text, digest = catalog_text_and_digest(data)
    catalog_path().write_text(text, encoding="utf-8")
    return text, digest


def _set_hash(digest: str) -> None:
    from db import get_connection

    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (CATALOG_HASH_KEY, digest),
        )
        conn.commit()


def _stored_hash() -> str | None:
    from db import get_connection

    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?",
                (CATALOG_HASH_KEY,),
            ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    return str(row[0] if not hasattr(row, "keys") else row["value"])


def apply_catalog_file() -> None:
    """Поднимает каталог из catalog.json после перезапуска облака."""
    path = catalog_path()
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    materials = payload.get("materials") if isinstance(payload, dict) else None
    if not isinstance(materials, list) or not materials:
        return
    _, digest = catalog_text_and_digest({"materials": materials})
    if _stored_hash() == digest:
        return
    from db import replace_catalog_rows

    replace_catalog_rows(materials)
    _set_hash(digest)


def _github_config() -> dict[str, str]:
    section: dict[str, Any] = {}
    try:
        import streamlit as st

        raw = st.secrets.get("github", {})
        if raw:
            section = dict(raw)
    except Exception:
        section = {}
    token = str(section.get("token") or os.environ.get("GITHUB_TOKEN") or "").strip()
    return {
        "token": token,
        "repo": str(section.get("repo") or os.environ.get("GITHUB_REPO") or DEFAULT_REPO),
        "branch": str(section.get("branch") or os.environ.get("GITHUB_BRANCH") or DEFAULT_BRANCH),
    }


def github_configured() -> bool:
    return bool(_github_config()["token"])


def _github_request(url: str, token: str, method: str = "GET", body: dict | None = None) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "vsp-price",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def push_catalog_to_github(text: str) -> str | None:
    """Пишет catalog.json в GitHub. None = ок, иначе текст ошибки."""
    cfg = _github_config()
    if not cfg["token"]:
        return "no-token"
    repo = cfg["repo"]
    branch = cfg["branch"]
    api = f"https://api.github.com/repos/{repo}/contents/catalog.json"
    sha = None
    try:
        current = _github_request(f"{api}?ref={branch}", cfg["token"])
        remote_bytes = base64.b64decode(current.get("content") or "")
        if remote_bytes.decode("utf-8") == text:
            return None
        sha = current.get("sha")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            return f"GitHub: не удалось прочитать catalog.json ({exc.code})"
    body: dict[str, Any] = {
        "message": "Save materials catalog from the app.",
        "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        body["sha"] = sha
    try:
        _github_request(api, cfg["token"], method="PUT", body=body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        return f"GitHub: не удалось сохранить каталог ({exc.code}) {detail}"
    except Exception as exc:
        return f"GitHub: {exc}"
    return None


def persist_catalog() -> str | None:
    """Сохраняет каталог в файл и, если задан токен, в GitHub."""
    text, digest = write_catalog_file()
    _set_hash(digest)
    from db import DB_PATH

    app_dir = Path(__file__).resolve().parent
    if Path(DB_PATH).resolve().parent != app_dir:
        return None
    return push_catalog_to_github(text)
