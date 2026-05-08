# mypy: disable-error-code="no-untyped-def, no-untyped-call, type-arg, unused-ignore, attr-defined, comparison-overlap, misc"
"""Tests for `/runs` endpoints."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from rpa_recorder.models import (
    ActionExecution,
    ActionType,
    ClickPayload,
    ElementSelector,
    ExecutionAttempt,
    ExecutionStatus,
    RecordedAction,
    Recording,
    RunResult,
)
from rpa_recorder.storage.repositories import RecordingRepository, RunResultRepository


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


def _run(rec_id, status: ExecutionStatus = ExecutionStatus.SUCCESS):
    return RunResult(
        id=uuid4(),
        recording_id=rec_id,
        started_at=datetime.now(UTC),
        ended_at=datetime.now(UTC),
        status=status,
        executions=[
            ActionExecution(
                action_id=uuid4(),
                status=status,
                attempts=[
                    ExecutionAttempt(
                        attempt_number=1,
                        started_at=datetime.now(UTC),
                        ended_at=datetime.now(UTC),
                        status=status,
                    )
                ],
                duration_ms=100,
            )
        ],
    )


async def _seed(engine, rec, run):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await RecordingRepository(session).save(rec)
        await RunResultRepository(session).save(run)
        await session.commit()


@pytest.mark.asyncio
async def test_list_runs_filters_by_recording_id(async_client, db_engine):
    rec = _recording()
    run = _run(rec.id)
    await _seed(db_engine, rec, run)
    r = await async_client.get(f"/runs?recording_id={rec.id}")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["recording_id"] == str(rec.id)


@pytest.mark.asyncio
async def test_list_runs_returns_empty_without_recording_id(async_client):
    r = await async_client.get("/runs")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_get_run_returns_detail(async_client, db_engine):
    rec = _recording()
    run = _run(rec.id)
    await _seed(db_engine, rec, run)
    r = await async_client.get(f"/runs/{run.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(run.id)
    assert body["status"] == "success"
    assert len(body["executions"]) == 1


@pytest.mark.asyncio
async def test_get_run_404_for_unknown(async_client):
    r = await async_client.get(f"/runs/{uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_cancel_run_sets_redis_flag(async_client, app_under_test):
    run_id = uuid4()
    r = await async_client.post(f"/runs/{run_id}/cancel")
    assert r.status_code == 200
    body = r.json()
    assert body["cancelled"] is True
    flag = await app_under_test.state.redis.get(f"cancel:{run_id}")
    assert flag in (b"1", "1")
