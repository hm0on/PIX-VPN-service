"""Main menu inline keyboard."""

from __future__ import annotations

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.utils.texts import TextService

_COLOR_TO_STYLE: dict[str, ButtonStyle] = {
    "blue": ButtonStyle.PRIMARY,
    "primary": ButtonStyle.PRIMARY,
    "green": ButtonStyle.SUCCESS,
    "success": ButtonStyle.SUCCESS,
    "red": ButtonStyle.DANGER,
    "danger": ButtonStyle.DANGER,
}


def make_button(
    text: str,
    *,
    callback_data: str | None = None,
    url: str | None = None,
    style: ButtonStyle | None = None,
    color: str | None = None,
    icon_custom_emoji_id: str | None = None,
) -> InlineKeyboardButton:
    """Build an InlineKeyboardButton.

    Since Bot API 9.4 (aiogram 3.25+), inline buttons support a ``style``
    parameter (``ButtonStyle.PRIMARY`` / ``SUCCESS`` / ``DANGER``). Older
    Telegram clients render them as default — no error, just no color.

    ``color`` is a backwards-compatible string alias ("blue" / "green" / "red")
    used by older call-sites; it maps to the corresponding ``ButtonStyle``.
    Explicit ``style=`` always wins.

    ``icon_custom_emoji_id`` (Bot API ≥ 7.x) attaches a Telegram premium
    custom-emoji icon to the left of the button label. The label itself
    cannot contain HTML or entities — Telegram silently strips them — so
    this is the only way to put a fancy emoji on an inline button. Pass
    ``None`` (the default) to leave the icon empty.
    """
    if style is None and color is not None:
        style = _COLOR_TO_STYLE.get(color.lower())
    # Only forward ``icon_custom_emoji_id`` when set — older aiogram releases
    # tolerate the kwarg, but keeping the kwargs minimal is safer for clients
    # that haven't pulled the field yet.
    extra: dict[str, object] = {}
    if icon_custom_emoji_id:
        extra["icon_custom_emoji_id"] = icon_custom_emoji_id
    if callback_data is not None:
        return InlineKeyboardButton(
            text=text, callback_data=callback_data, style=style, **extra  # type: ignore[arg-type]
        )
    if url is not None:
        return InlineKeyboardButton(
            text=text, url=url, style=style, **extra  # type: ignore[arg-type]
        )
    raise ValueError("make_button requires either callback_data or url")


async def _labels(
    svc: TextService, *keys: str
) -> dict[str, tuple[str, str | None]]:
    """Fetch ``(label, icon)`` for each key — a tiny helper that lets a
    keyboard builder hit ``TextService`` once and read its labels off a
    plain dict instead of awaiting per-button.
    """
    return {k: await svc.get_button(k) for k in keys}


async def main_menu_kb(text_service: TextService) -> InlineKeyboardMarkup:
    """Main menu layout.

    Row 1: [Каталог (синяя)] [Профиль]
    Row 2: [Поддержка] [Промокод]
    Row 3: [🎁 5 дней бесплатно (зелёная)]
    Row 4: [Предложить идею]
    Row 5: [О проекте]

    Row 3 was added in conversion-pack 2026-05-13 to make the FREE-trial
    discoverable at the top level (was buried in catalog → FREE tariff).
    Callback ``free_trial`` is handled in ``handlers/free_trial.py`` and
    shares the activation flow with the catalog path.

    Labels come from the ``texts`` table (kind=button) so admins can rename
    them without a code change. The fallback path in ``TextService`` keeps
    the original Russian strings if backend is unreachable.
    """
    lbl = await _labels(
        text_service,
        "btn.main_menu.catalog",
        "btn.main_menu.profile",
        "btn.main_menu.support",
        "btn.main_menu.promo",
        "btn.main_menu.free_gift",
        "btn.main_menu.idea",
        "btn.main_menu.about",
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                make_button(
                    lbl["btn.main_menu.catalog"][0],
                    callback_data="catalog",
                    style=ButtonStyle.PRIMARY,
                    icon_custom_emoji_id=lbl["btn.main_menu.catalog"][1],
                ),
                make_button(
                    lbl["btn.main_menu.profile"][0],
                    callback_data="profile",
                    icon_custom_emoji_id=lbl["btn.main_menu.profile"][1],
                ),
            ],
            [
                make_button(
                    lbl["btn.main_menu.support"][0],
                    callback_data="support",
                    icon_custom_emoji_id=lbl["btn.main_menu.support"][1],
                ),
                make_button(
                    lbl["btn.main_menu.promo"][0],
                    callback_data="promo",
                    icon_custom_emoji_id=lbl["btn.main_menu.promo"][1],
                ),
            ],
            [
                make_button(
                    lbl["btn.main_menu.free_gift"][0],
                    callback_data="free_trial",
                    style=ButtonStyle.SUCCESS,
                    icon_custom_emoji_id=lbl["btn.main_menu.free_gift"][1],
                )
            ],
            [
                make_button(
                    lbl["btn.main_menu.idea"][0],
                    callback_data="idea",
                    icon_custom_emoji_id=lbl["btn.main_menu.idea"][1],
                )
            ],
            [
                make_button(
                    lbl["btn.main_menu.about"][0],
                    callback_data="about",
                    icon_custom_emoji_id=lbl["btn.main_menu.about"][1],
                )
            ],
        ]
    )
