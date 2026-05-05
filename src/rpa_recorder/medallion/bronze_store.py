"""`BronzeStore` Protocol and `LocalFilesystemStore` implementation.

The Protocol decouples bronze writers from their backend. Today only
`LocalFilesystemStore` exists; an S3 / MinIO implementation can land later
behind the same interface without touching `BronzeWriter` or its callers.

All operations are async to fit the project's broader asyncio model. Inside
`LocalFilesystemStore`, real I/O happens via `aiofiles`; path manipulation
uses `pathlib.Path` only (no string concatenation, per ruff PTH).

Atomicity: `put()` writes to `<target>.tmp` first, then renames in place.
On any failure the temp file is cleaned up and the target stays untouched.
"""

import hashlib
from pathlib import Path
from typing import BinaryIO, Protocol

import aiofiles


class BronzeStore(Protocol):
    """Async key-value store for bronze artifacts.

    Implementations must treat `path` as forward-slash-separated and join it
    under a backend-specific root. `put` is atomic (write-temp + rename);
    `delete` is idempotent.
    """

    async def put(self, path: str, data: bytes | BinaryIO) -> str:
        """Write `data` at `path` atomically. Returns the SHA-256 hex digest."""

    async def append_line(self, path: str, line: str) -> None:
        """Append `line` followed by `\\n`. Creates parents as needed."""

    async def append_lines(self, path: str, lines: list[str]) -> None:
        """Append multiple `\\n`-terminated lines in one open. Empty list is a no-op."""

    async def get(self, path: str) -> bytes:
        """Read the whole file at `path`. Raises if it does not exist."""

    async def list(self, prefix: str) -> list[str]:
        """Return store-relative paths under `prefix`, sorted alphabetically."""

    async def delete(self, path: str) -> None:
        """Remove `path`. Idempotent — missing files do not raise."""

    async def stat(self, path: str) -> tuple[int, str]:
        """Return `(size_bytes, sha256)` for the file at `path`."""


class LocalFilesystemStore:
    """`BronzeStore` backed by local files under `root`."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()

    def _resolve(self, path: str) -> Path:
        # Forward-slash store paths join cleanly across platforms.
        return self._root.joinpath(*path.split("/"))

    async def put(self, path: str, data: bytes | BinaryIO) -> str:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")

        if isinstance(data, bytes):
            payload: bytes = data
        else:
            raw = data.read()
            payload = raw if isinstance(raw, bytes) else str(raw).encode("utf-8")

        async with aiofiles.open(tmp, "wb") as f:
            await f.write(payload)

        moved = False
        try:
            tmp.replace(target)
            moved = True
        finally:
            if not moved and tmp.exists():
                tmp.unlink(missing_ok=True)

        return hashlib.sha256(payload).hexdigest()

    async def append_line(self, path: str, line: str) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(target, "a", encoding="utf-8") as f:
            await f.write(line + "\n")

    async def append_lines(self, path: str, lines: list[str]) -> None:
        if not lines:
            return
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = "".join(line + "\n" for line in lines)
        async with aiofiles.open(target, "a", encoding="utf-8") as f:
            await f.write(payload)

    async def get(self, path: str) -> bytes:
        target = self._resolve(path)
        async with aiofiles.open(target, "rb") as f:
            return await f.read()

    async def list(self, prefix: str) -> list[str]:
        prefix_path = self._resolve(prefix)
        if not prefix_path.exists():
            return []
        results: list[str] = []
        if prefix_path.is_file():
            rel = prefix_path.relative_to(self._root)
            return ["/".join(rel.parts)]
        for sub in prefix_path.rglob("*"):
            if sub.is_file():
                rel = sub.relative_to(self._root)
                results.append("/".join(rel.parts))
        return sorted(results)

    async def delete(self, path: str) -> None:
        target = self._resolve(path)
        target.unlink(missing_ok=True)

    async def stat(self, path: str) -> tuple[int, str]:
        target = self._resolve(path)
        async with aiofiles.open(target, "rb") as f:
            data = await f.read()
        return len(data), hashlib.sha256(data).hexdigest()


__all__ = ["BronzeStore", "LocalFilesystemStore"]
