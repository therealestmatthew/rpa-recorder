"""Tests for `rpa_recorder.cli.async_runner.run_async`."""

import asyncio

import pytest

from rpa_recorder.cli.async_runner import run_async
from rpa_recorder.cli.errors import CLIError


def test_run_async_returns_value() -> None:
    async def coro() -> int:
        return 42

    assert run_async(coro)() == 42


def test_run_async_translates_keyboard_interrupt() -> None:
    async def coro() -> None:
        raise KeyboardInterrupt

    with pytest.raises(CLIError) as info:
        run_async(coro)()
    assert info.value.exit_code == 130
    assert info.value.message == "interrupted"


def test_run_async_translates_cancelled_error() -> None:
    async def coro() -> None:
        raise asyncio.CancelledError

    with pytest.raises(CLIError) as info:
        run_async(coro)()
    assert info.value.exit_code == 130


def test_run_async_runs_finally_block() -> None:
    teardown_ran = False

    async def coro() -> None:
        nonlocal teardown_ran
        try:
            raise KeyboardInterrupt
        finally:
            teardown_ran = True

    with pytest.raises(CLIError):
        run_async(coro)()
    assert teardown_ran is True


def test_run_async_passes_kwargs_through() -> None:
    async def coro(*, x: int, y: int) -> int:
        return x + y

    assert run_async(coro)(x=1, y=2) == 3
