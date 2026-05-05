"""Tests for ``notify_expiring_subscriptions_task``.

We don't spin up a real Postgres for unit tests — instead we fake
``session.execute`` and inspect the recorded SQL/params. The task
issues exactly four kinds of ``execute`` calls per tick:

1. SELECT of expiring subscriptions
2. SELECT of the ``texts`` template (one-shot per tick)
3. INSERT into ``notifications_sent`` (per row)
4. INSERT into ``outbox`` (per row that won the race)

Coverage:

- happy path: 2 candidates → 2 outbox rows + 2 notifications_sent rows
- second tick: same candidates re-queried but ON CONFLICT returns NULL
  → no outbox rows queued (one-shot guard works)
- DB error → counters reset, task does not raise
"""

from __future__ import annotations

from typing import Any

import pytest

from app.tasks.notify_expiring import notify_expiring_subscriptions_task


# --------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------- #
class _Row:
    """Minimal stand-in for SQLAlchemy ``Row`` — attribute access only."""

    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


class _FakeResult:
    def __init__(self, rows: list[_Row] | None = None, scalar: Any = None) -> None:
        self._rows = rows or []
        self._scalar = scalar

    def all(self) -> list[_Row]:
        return list(self._rows)

    def first(self) -> _Row | None:
        return self._rows[0] if self._rows else None

    def scalar(self) -> Any:
        return self._scalar


class FakeSession:
    """Records every ``execute`` call so tests can assert SQL routing."""

    def __init__(self, scripts: list[_FakeResult]) -> None:
        self._scripts = list(scripts)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if not self._scripts:
            return _FakeResult()
        return self._scripts.pop(0)

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    def begin(self) -> "FakeSession":
        return self


class FakeSessionFactory:
    def __init__(self, scripts: list[_FakeResult]) -> None:
        self.session = FakeSession(scripts)

    def __call__(self) -> FakeSession:
        return self.session


class FakeAPIClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    async def post(self, path: str, json: dict[str, Any] | None = None):
        self.calls.append(("POST", path, json))

        class _R:
            status_code = 204

        return _R()


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #
def _ctx(session_factory: FakeSessionFactory, api: FakeAPIClient) -> dict[str, Any]:
    return {"db_session_factory": session_factory, "api_client": api}


def _outbox_inserts(session: FakeSession) -> list[dict[str, Any]]:
    return [params for sql, params in session.calls if "INTO outbox" in sql]


def _notification_inserts(session: FakeSession) -> list[dict[str, Any]]:
    return [params for sql, params in session.calls if "notifications_sent" in sql]


# --------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_happy_path_queues_outbox_for_each_candidate() -> None:
    """Two candidates → two outbox rows + two notifications_sent rows."""
    rows = [
        _Row(subscription_id=11, user_id=1, tg_id=10001),
        _Row(subscription_id=22, user_id=2, tg_id=20002),
    ]
    scripts = [
        _FakeResult(rows=rows),                # SELECT candidates
        _FakeResult(rows=[]),                   # SELECT texts (no template)
        _FakeResult(scalar=101),                # INSERT notifications_sent #1 (won)
        _FakeResult(rows=[_Row(id=501)]),       # INSERT outbox #1
        _FakeResult(scalar=102),                # INSERT notifications_sent #2 (won)
        _FakeResult(rows=[_Row(id=502)]),       # INSERT outbox #2
    ]
    factory = FakeSessionFactory(scripts)
    api = FakeAPIClient()

    counters = await notify_expiring_subscriptions_task(_ctx(factory, api))

    assert counters == {"candidates": 2, "sent": 2, "skipped": 0}

    outbox_inserts = _outbox_inserts(factory.session)
    assert len(outbox_inserts) == 2
    assert outbox_inserts[0]["chat_id"] == 10001
    assert outbox_inserts[0]["user_id"] == 1
    assert "subscription" in outbox_inserts[0]["payload"].lower()
    # payload is a JSON string with the dispatcher-compatible shape
    assert "\"text\"" in outbox_inserts[0]["payload"]
    assert "\"reply_markup\"" in outbox_inserts[0]["payload"]
    assert "extend:11" in outbox_inserts[0]["payload"]
    assert "extend:22" in outbox_inserts[1]["payload"]

    notif_inserts = _notification_inserts(factory.session)
    assert len(notif_inserts) == 2
    assert notif_inserts[0] == {"user_id": 1, "subscription_id": 11}
    assert notif_inserts[1] == {"user_id": 2, "subscription_id": 22}

    # business_log called
    assert any(p == "/api/bot/logs" for _, p, _ in api.calls)


@pytest.mark.asyncio
async def test_second_run_does_not_duplicate_outbox() -> None:
    """If ON CONFLICT swallows both inserts, no outbox rows are queued."""
    rows = [
        _Row(subscription_id=11, user_id=1, tg_id=10001),
        _Row(subscription_id=22, user_id=2, tg_id=20002),
    ]
    scripts = [
        _FakeResult(rows=rows),         # SELECT candidates
        _FakeResult(rows=[]),            # SELECT texts
        _FakeResult(scalar=None),        # INSERT notifications_sent #1 (LOST race)
        _FakeResult(scalar=None),        # INSERT notifications_sent #2 (LOST race)
    ]
    factory = FakeSessionFactory(scripts)
    api = FakeAPIClient()

    counters = await notify_expiring_subscriptions_task(_ctx(factory, api))

    assert counters == {"candidates": 2, "sent": 0, "skipped": 2}
    assert _outbox_inserts(factory.session) == []
    # No business_log when nothing sent
    assert not any(p == "/api/bot/logs" for _, p, _ in api.calls)


@pytest.mark.asyncio
async def test_no_candidates_is_a_noop() -> None:
    factory = FakeSessionFactory([_FakeResult(rows=[])])
    api = FakeAPIClient()

    counters = await notify_expiring_subscriptions_task(_ctx(factory, api))

    assert counters == {"candidates": 0, "sent": 0, "skipped": 0}
    assert _outbox_inserts(factory.session) == []


@pytest.mark.asyncio
async def test_uses_text_template_when_present() -> None:
    """If the ``texts`` table has the key, its value_html replaces the fallback."""
    rows = [_Row(subscription_id=11, user_id=1, tg_id=10001)]
    scripts = [
        _FakeResult(rows=rows),                                # SELECT candidates
        _FakeResult(rows=[_Row(value_html="CUSTOM TEMPLATE")]),  # SELECT texts
        _FakeResult(scalar=101),                               # INSERT notif (won)
        _FakeResult(rows=[_Row(id=501)]),                       # INSERT outbox
    ]
    factory = FakeSessionFactory(scripts)
    api = FakeAPIClient()

    await notify_expiring_subscriptions_task(_ctx(factory, api))

    inserts = _outbox_inserts(factory.session)
    assert len(inserts) == 1
    assert "CUSTOM TEMPLATE" in inserts[0]["payload"]


@pytest.mark.asyncio
async def test_db_error_returns_counters_without_raising() -> None:
    class _BoomSession(FakeSession):
        async def execute(self, *args: Any, **kwargs: Any):
            raise RuntimeError("db gone")

    class _BoomFactory:
        def __init__(self) -> None:
            self.session = _BoomSession([])

        def __call__(self) -> _BoomSession:
            return self.session

    factory = _BoomFactory()
    api = FakeAPIClient()

    counters = await notify_expiring_subscriptions_task(_ctx(factory, api))

    assert counters == {"candidates": 0, "sent": 0, "skipped": 0}
