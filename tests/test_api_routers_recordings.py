# mypy: disable-error-code="no-untyped-def, no-untyped-call, type-arg, unused-ignore, attr-defined, comparison-overlap, misc"
"""Tests for `/recordings` and `/recordings/{id}`."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

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


def _sample_recording(name: str = "login") -> Recording:
    return Recording(
        id=uuid4(),
        name=name,
        created_at=datetime.now(UTC),
        starting_url="https://example.com/login",
        actions=[
            RecordedAction(
                sequence=1,
                timestamp=datetime.now(UTC),
                action_type=ActionType.CLICK,
                payload=ClickPayload(),
                selector=ElementSelector(test_id="submit-btn"),
                url="https://example.com/login",
            )
        ],
    )


async def _seed(engine, recording: Recording) -> UUID:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await RecordingRepository(session).save(recording)
        await session.commit()
    return recording.id


@pytest.mark.asyncio
async def test_list_recordings_returns_summaries(async_client, db_engine):
    rec = _sample_recording()
    await _seed(db_engine, rec)
    r = await async_client.get("/recordings")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["name"] == "login"
    assert body[0]["action_count"] == 1


@pytest.mark.asyncio
async def test_list_recordings_supports_pagination(async_client, db_engine):
    for i in range(5):
        await _seed(db_engine, _sample_recording(f"flow-{i}"))
    r = await async_client.get("/recordings?limit=2&offset=1")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2


@pytest.mark.asyncio
async def test_get_recording_returns_detail(async_client, db_engine):
    rec = _sample_recording("detail-test")
    await _seed(db_engine, rec)
    r = await async_client.get(f"/recordings/{rec.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "detail-test"
    assert len(body["actions"]) == 1


@pytest.mark.asyncio
async def test_get_recording_404_for_unknown_id(async_client):
    r = await async_client.get(f"/recordings/{uuid4()}")
    assert r.status_code == 404
