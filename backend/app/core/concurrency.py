"""
Concurrency utilities for managing key-based locks and mutual exclusion.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator


class KeyedLockManager:
    """
    Manages named asyncio locks to prevent concurrent duplicate operations
    for the same key (e.g. portal sync for the same student).
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._ref_counts: dict[str, int] = {}
        self._master_lock = asyncio.Lock()

    @asynccontextmanager
    async def lock(self, key: str) -> AsyncIterator[None]:
        """Acquire a lock for the specific key, releasing and cleaning up afterwards."""
        async with self._master_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
                self._ref_counts[key] = 0
            self._ref_counts[key] += 1
            lock = self._locks[key]

        async with lock:
            try:
                yield
            finally:
                async with self._master_lock:
                    self._ref_counts[key] -= 1
                    if self._ref_counts[key] <= 0:
                        self._locks.pop(key, None)
                        self._ref_counts.pop(key, None)


keyed_lock_manager = KeyedLockManager()
