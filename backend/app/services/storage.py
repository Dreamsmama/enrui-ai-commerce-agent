"""Storage facade with a local provider and an OSS-ready boundary."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Protocol

import aiofiles

from app.config import get_settings


class StorageProvider(Protocol):
    async def save(self, data: bytes, filename: str, subdir: str) -> str: ...
    async def delete(self, url: str) -> None: ...


class LocalStorageProvider:
    def __init__(self) -> None:
        self.root = get_settings().upload_path

    async def save(self, data: bytes, filename: str, subdir: str) -> str:
        suffix = Path(filename).suffix
        stored_name = f"{uuid.uuid4().hex}{suffix}"
        directory = self.root / subdir
        directory.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(directory / stored_name, "wb") as output:
            await output.write(data)
        return f"/uploads/{subdir}/{stored_name}"

    async def delete(self, url: str) -> None:
        relative = url.removeprefix("/uploads/")
        path = (self.root / relative).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("非法存储路径")
        if path.exists():
            path.unlink()


class StorageService:
    def __init__(self, provider: StorageProvider | None = None) -> None:
        self.provider = provider or LocalStorageProvider()

    async def upload(self, data: bytes, filename: str, subdir: str) -> str:
        return await self.provider.save(data, filename, subdir)

    async def delete(self, url: str) -> None:
        await self.provider.delete(url)


_storage: StorageService | None = None


def get_storage() -> StorageService:
    global _storage
    if _storage is None:
        _storage = StorageService()
    return _storage
