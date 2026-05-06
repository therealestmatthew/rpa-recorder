"""Per-instance semaphore factory for the LLM tier.

A fresh `asyncio.Semaphore` per `LLMClassifier` keeps the semaphore bound
to the running event loop. Sharing a module-global one across worker
processes — each with its own loop — crashes with `RuntimeError: ...
attached to a different loop` (see m9 §"Known pitfalls").
"""

import asyncio


def make_semaphore(size: int) -> asyncio.Semaphore:
    """Construct a semaphore. Validates `size >= 1`."""
    if size < 1:
        raise ValueError(f"semaphore size must be ≥ 1, got {size}")
    return asyncio.Semaphore(size)


__all__ = ["make_semaphore"]
