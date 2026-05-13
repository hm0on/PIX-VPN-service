"""Tariff.is_unlimited_traffic: enforce true unlimited VPN quota via NorthLine.

Why
---
До этой миграции `NorthLineClient.create_key` НЕ передавал
`unlimited_traffic`, поэтому провайдер выдавал дефолт **1000 GB на
устройство в месяц** (масштабируется под `days/30`). Для FREE-триала
2 устр × 5 дн это вылилось в ~334 GB — пользователи получали лимит,
а маркетинговое обещание (везде «Безлимитный трафик») не выполнялось.

Решение — добавить булев флаг на тариф (NorthLine принимает только
бинарный признак «безлимит / по-дефолту-1ТБ», см. документацию
Reseller API → POST /keys → unlimited_traffic). Все 4 текущих тарифа
(free/basic/plus/max) включаем флаг сразу backfill'ом — это совпадает
с описанием карточек тарифа и тем, что мы и так уже обещаем юзерам.

Schema
------
- ALTER tariffs ADD COLUMN is_unlimited_traffic BOOLEAN NOT NULL DEFAULT FALSE
  (NOT NULL + server_default — ничего не сломается на старых тарифах).
- UPDATE tariffs SET is_unlimited_traffic = TRUE WHERE code IN
  ('free', 'basic', 'plus', 'max'). Идемпотентно — повторный прогон
  миграции просто перепишет TRUE→TRUE.

Стоимость на стороне провайдера +50% к цене ключа (см. документацию
Reseller). Это сознательное решение: реселлер-баланс пополнен, лучше
заплатить +50%, чем терять конверсию из-за «закончился трафик».

Revision ID: 0018_tariff_unlimited_traffic
Revises: 0017_conversion_pack_texts
Create Date: 2026-05-13 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018_tariff_unlimited_traffic"
down_revision: str | None = "0017_conversion_pack_texts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tariffs",
        sa.Column(
            "is_unlimited_traffic",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Backfill: все существующие тарифы получают безлимит. Маркетинговая
    # копия в карточках уже это обещает, реселлер-баланс позволяет +50%.
    op.execute(
        "UPDATE tariffs SET is_unlimited_traffic = TRUE "
        "WHERE code IN ('free', 'basic', 'plus', 'max')"
    )


def downgrade() -> None:
    op.drop_column("tariffs", "is_unlimited_traffic")
