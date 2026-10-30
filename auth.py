"""Вход по логину и паролю из .streamlit/secrets.toml."""

from __future__ import annotations

import hmac
from typing import Any

import streamlit as st


def _users() -> dict[str, str]:
    try:
        section: Any = st.secrets["credentials"]
    except Exception:
        return {}
    return {str(name): str(password) for name, password in section.items()}


def _passwords_match(entered: str, stored: str) -> bool:
    try:
        return hmac.compare_digest(entered, stored)
    except Exception:
        return False


def require_login() -> bool:
    if st.session_state.get("auth_user"):
        bar = st.container()
        with bar:
            left, right = st.columns([4, 1])
            left.caption(f"Вход: **{st.session_state.auth_user}**")
            if right.button("Выйти", width="stretch"):
                st.session_state.pop("auth_user", None)
                st.rerun()
        return True

    users = _users()
    st.title("Калькулятор ВСП")
    st.caption("Введите логин и пароль, чтобы открыть расчёты.")

    if not users:
        st.error(
            "Не заданы пользователи. Создайте файл `.streamlit/secrets.toml` "
            "по образцу `.streamlit/secrets.toml.example`."
        )
        return False

    with st.form("login"):
        username = st.text_input("Логин")
        password = st.text_input("Пароль", type="password")
        submitted = st.form_submit_button("Войти", type="primary", width="stretch")

    if submitted:
        name = username.strip()
        stored = users.get(name)
        if stored and _passwords_match(password, stored):
            st.session_state.auth_user = name
            st.rerun()
        st.error("Неверный логин или пароль.")
    return False
