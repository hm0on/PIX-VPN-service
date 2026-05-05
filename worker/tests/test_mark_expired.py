"""Tests for ``mark_expired_subscriptions_task``.

The SQL is a single ``UPDATE ... RETURNING`` so we mostly assert the
counters returned by the task and that ``business_log`` is called only
when at least one row flips. The actual ``status='active' AND
expires_at < now()`` filter is enforced by Postgres — we simulate two
shapes of result here:

- 2 active subs flip to expired → counter=2, business_log fires
- nothing in the past → counter=0, no business_log
- DB blows up → counter=0, no exception bubbles up
"""

from __future__ import annotations

from typing import Any

import pytest

from app.tasks.mark_expired import mark_expired_subscriptions_task


class _Row:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


class _FakeResult:
    def __init__(self, rows: list[_Row] | None = None) -> None:
        self._rows = rows or []

    def all(self) -> list[_Row]:
        return list(self._rows)


class FakeSession:
    def __init__(self, scripts: list[_FakeResult]) -> None:
        self._scripts = list(scripts)
        self.calls: list[str] = []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None):
        self.calls.append(str(statement))
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


@pytest.mark.asyncio
async def test_marks_active_with_past_expires_at_as_expired() -> None:
    """Two active subs in the past → both flip; business_log emitted."""
    scripts = [
        _FakeResult(
            rows=[
                _Row(id=11, user_id=1),
                _Row(id=22, user_id=2),
            ]
        )
    ]
    factory = FakeSessionFactory(scripts)
    api = FakeAPIClient()

    result = await mark_expired_subscriptions_task(_ctx(factory, api))

    assert result == {"expired": 2}
    # exactly one statement was issued (the WITH updated AS UPDATE ...)
    assert len(factory.session.calls) == 1
    assert "UPDATE subscriptions" in factory.session.calls[0]
    # business_log fired with the correct ids
    assert len(api.calls) == 1
    path, body = api.calls[0]
    assert path == "/api/bot/logs"
    assert body is not None
    assert body["event"] == "subscriptions_marked_expired"
    assert body["context"]["count"] == 2
    assert body["context"]["subscription_ids"] == [11, 22]


@pytest.mark.asyncio
async def test_no_rows_in_the_past_is_a_noop() -> None:
    """Subs whose expires_at > now() never reach the RETURNING clause."""
    factory = FakeSessionFactory([_FakeResult(rows=[])])
    api = FakeAPIClient()

    result = await mark_expired_subscriptions_task(_ctx(factory, api))

    assert result == {"expired": 0}
    assert api.calls == []  # no business_log on no-op


@pytest.mark.asyncio
async def test_db_error_swallows_and_returns_zero() -> None:
    class _BoomSession(FakeSession):
        async def execute(self, *args: Any, **kwargs: Any):
            raise RuntimeError("db gone")

    class _BoomFactory:
        def __init__(self) -> None:
            self.session = _BoomSession([])

        def __call__(self) -> _BoomSession:
            return self.session

    api = FakeAPIClient()
    result = await mark_expired_subscriptions_task(_ctx(_BoomFactory(), api))
    assert result == {"expired": 0}
    assert api.calls == []
