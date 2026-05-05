"""Tests for ``notify_expired_subscriptions_task``.

Mirror of :mod:`tests.test_notify_expiring` — same shape, different
SQL/text key/buttons.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.tasks.notify_expired import notify_expired_subscriptions_task


class _Row:
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
    def __init__(self, scripts: list[_FakeResult]) -> None:
        self._scripts = list(scripts)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None):
        self.calls.append((str(statement), params or {}))
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
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def post(self, path: str, json: dict[str, Any] | None = None):
        self.calls.append((path, json))

        class _R:
            status_code = 204

        return _R()


def _ctx(factory: FakeSessionFactory, api: FakeAPIClient) -> dict[str, Any]:
    return {"db_session_factory": factory, "api_client": api}


def _outbox_inserts(session: FakeSession) -> list[dict[str, Any]]:
    return [params for sql, params in session.calls if "INTO outbox" in sql]


@pytest.mark.asyncio
async def test_happy_path_queues_notifications_with_two_buttons() -> None:
    rows = [_Row(subscription_id=11, user_id=1, tg_id=10001)]
    scripts = [
        _FakeResult(rows=rows),                # SELECT candidates
        _FakeResult(rows=[]),                   # SELECT texts (no template)
        _FakeResult(scalar=101),                # INSERT notifications_sent (won)
        _FakeResult(rows=[_Row(id=501)]),       # INSERT outbox
    ]
    factory = FakeSessionFactory(scripts)
    api = FakeAPIClient()

    counters = await notify_expired_subscriptions_task(_ctx(factory, api))

    assert counters == {"candidates": 1, "sent": 1, "skipped": 0}

    inserts = _outbox_inserts(factory.session)
    assert len(inserts) == 1
    payload = inserts[0]["payload"]
    assert "extend:11" in payload
    assert "catalog" in payload  # the second inline button


@pytest.mark.asyncio
async def test_second_run_does_not_dispatch_when_unique_blocks() -> None:
    rows = [_Row(subscription_id=11, user_id=1, tg_id=10001)]
    scripts = [
        _FakeResult(rows=rows),         # SELECT candidates
        _FakeResult(rows=[]),            # SELECT texts
        _FakeResult(scalar=None),        # ON CONFLICT DO NOTHING — lost race
    ]
    factory = FakeSessionFactory(scripts)
    api = FakeAPIClient()

    counters = await notify_expired_subscriptions_task(_ctx(factory, api))

    assert counters == {"candidates": 1, "sent": 0, "skipped": 1}
    assert _outbox_inserts(factory.session) == []
    assert api.calls == []  # no business_log on zero sent


@pytest.mark.asyncio
async def test_no_candidates_is_a_noop() -> None:
    factory = FakeSessionFactory([_FakeResult(rows=[])])
    api = FakeAPIClient()

    counters = await notify_expired_subscriptions_task(_ctx(factory, api))

    assert counters == {"candidates": 0, "sent": 0, "skipped": 0}
    assert _outbox_inserts(factory.session) == []
