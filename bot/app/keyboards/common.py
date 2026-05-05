"""Shared inline keyboards: back-to-menu, subscription check."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def back_kb(callback: str = "main_menu", text: str = "← Назад") -> InlineKeyboardMarkup:
    """A single "Back" button. Default target: main menu."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=callback)]]
    )


def subscription_check_kb(channel_url: str) -> InlineKeyboardMarkup:
    """Two-row keyboard for the channel-subscription gate.

    Row 1: external "Подписаться" link.
    Row 2: callback "Я подписался" → re-checks via ``check_sub`` handler.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подписаться", url=channel_url)],
            [InlineKeyboardButton(text="Я подписался ✅", callback_data="check_sub")],
        ]
    )
