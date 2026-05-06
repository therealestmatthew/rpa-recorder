"""Concurrency: per-instance semaphore, bounded fan-out."""

import asyncio

import pytest

from rpa_recorder.classifier.llm.concurrency import make_semaphore


def test_make_semaphore_validates_size() -> None:
    with pytest.raises(ValueError, match=r"size must be"):
        make_semaphore(0)


async def test_semaphore_caps_in_flight() -> None:
    sem = make_semaphore(2)
    in_flight = 0
    peak = 0
    lock = asyncio.Lock()

    async def worker() -> None:
        nonlocal in_flight, peak
        async with sem:
            async with lock:
                in_flight += 1
                peak = max(peak, in_flight)
            await asyncio.sleep(0.01)
            async with lock:
                in_flight -= 1

    await asyncio.gather(*(worker() for _ in range(8)))
    assert peak <= 2
    assert peak >= 1


async def test_two_instances_have_independent_semaphores() -> None:
    sem_a = make_semaphore(1)
    sem_b = make_semaphore(1)
    # Acquiring sem_a does not block sem_b.
    async with sem_a, sem_b:
        assert sem_a.locked() is True
        assert sem_b.locked() is True
