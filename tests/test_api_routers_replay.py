# mypy: disable-error-code="no-untyped-def, no-untyped-call, type-arg, unused-ignore, attr-defined, comparison-overlap, misc"
"""Tests for `POST /recordings/{id}/replay`."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from rpa_recorder.models import (
    ActionType,
    ClickPayload,
    ElementSelector,
    RecordedAction,
    Recording,
)
from rpa_recorder.storage.repositories import RecordingRepository


def _recording():
    return Recording(
        id=uuid4(),
        name="r",
        created_at=datetime.now(UTC),
        starting_url="https://example.com",
        actions=[
            RecordedAction(
                sequence=1,
                timestamp=datetime.now(UTC),
                action_type=ActionType.CLICK,
                payload=ClickPayload(),
                selector=ElementSelector(test_id="x"),
                url="https://example.com",
            )
        ],
    )


async def _seed(engine, rec):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await RecordingRepository(session).save(rec)
        await session.commit()


@pytest.mark.asyncio
async def test_replay_enqueues_job_and_returns_run_id(async_client, app_under_test, db_engine):
    rec = _recording()
    await _seed(db_engine, rec)

    seen: list[dict] = []

    async def handler(_pool, **kwargs):
        seen.append(kwargs)

    app_under_test.state.queue_pool._registry["replay_run"] = handler

    r = await async_client.post(
        f"/recordings/{rec.id}/replay",
        json={"parameters": {"email": "u@example.com"}},
    )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    import asyncio

    await asyncio.sleep(0.05)
    assert len(seen) == 1
    assert seen[0]["recording_id"] == str(rec.id)
    assert seen[0]["params"] == {"email": "u@example.com"}


@pytest.mark.asyncio
async def test_replay_404_for_unknown_recording(async_client):
    r = await async_client.post(f"/recordings/{uuid4()}/replay", json={"parameters": {}})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_replay_returns_429_when_queue_saturated(async_client, app_under_test, db_engine):
    rec = _recording()
    await _seed(db_engine, rec)

    async def fake_queue_size(_name: str) -> int:
        return 10_000

    app_under_test.state.queue_pool.queue_size = fake_queue_size  # type: ignore[method-assign]

    r = await async_client.post(f"/recordings/{rec.id}/replay", json={"parameters": {}})
    assert r.status_code == 429
    assert "retry-after" in {k.lower() for k in r.headers}
