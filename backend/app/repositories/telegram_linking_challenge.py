import contextlib
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telegram_linking_challenge import (
    TelegramLinkingChallenge,
    TelegramLinkingChallengeStatus,
)


class TelegramLinkingChallengeRepository:
    def __init__(self, session_or_factory: AsyncSession | Callable[[], Any]):
        if isinstance(session_or_factory, AsyncSession):
            self._session: AsyncSession | None = session_or_factory
            self._session_factory: Callable[[], Any] | None = None
        else:
            self._session = None
            self._session_factory = session_or_factory

    @contextlib.asynccontextmanager
    async def _get_session_cm(self) -> AsyncIterator[AsyncSession]:
        if self._session is not None:
            yield self._session
        elif self._session_factory is not None:
            async with self._session_factory() as session:
                yield session
        else:
            raise RuntimeError("No session or session_factory configured")

    async def create(
        self,
        *,
        telegram_user_id: str,
        challenge_token: str,
        expires_at: str,  # ISO format datetime string
    ) -> "TelegramLinkingChallenge":
        from datetime import datetime

        async with self._get_session_cm() as session:
            challenge = TelegramLinkingChallenge(
                telegram_user_id=telegram_user_id,
                challenge_token=challenge_token,
                expires_at=datetime.fromisoformat(expires_at.replace("Z", "+00:00")),
                status=TelegramLinkingChallengeStatus.PENDING,
            )
            session.add(challenge)
            await session.flush()
            # Refresh to get the generated ID and other defaults
            await session.refresh(challenge)
            # Expunge the object from the session so it can be used outside
            session.expunge(challenge)
            return challenge

    async def get_by_token(
        self, challenge_token: str
    ) -> "TelegramLinkingChallenge | None":
        async with self._get_session_cm() as session:
            result = await session.execute(
                select(TelegramLinkingChallenge).where(
                    TelegramLinkingChallenge.challenge_token == challenge_token
                )
            )
            return result.scalar_one_or_none()

    async def get_by_telegram_user_id(
        self, telegram_user_id: str
    ) -> list["TelegramLinkingChallenge"]:
        async with self._get_session_cm() as session:
            result = await session.execute(
                select(TelegramLinkingChallenge).where(
                    TelegramLinkingChallenge.telegram_user_id == telegram_user_id
                )
            )
            return list(result.scalars().all())

    async def get_pending_by_telegram_user_id(
        self, telegram_user_id: str
    ) -> "TelegramLinkingChallenge | None":
        async with self._get_session_cm() as session:
            result = await session.execute(
                select(TelegramLinkingChallenge).where(
                    TelegramLinkingChallenge.telegram_user_id == telegram_user_id,
                    TelegramLinkingChallenge.status
                    == TelegramLinkingChallengeStatus.PENDING,
                    TelegramLinkingChallenge.expires_at > datetime.now(UTC),
                )
            )
        return result.scalar_one_or_none()

    async def mark_used(
        self,
        challenge: "TelegramLinkingChallenge",
        student_id: UUID,
        telegram_identity_id: UUID,
    ) -> None:

        async with self._get_session_cm() as session:
            challenge.status = TelegramLinkingChallengeStatus.USED
            challenge.student_id = student_id
            challenge.telegram_identity_id = telegram_identity_id
            await session.flush()

    async def mark_expired(self, challenge: "TelegramLinkingChallenge") -> None:

        async with self._get_session_cm() as session:
            challenge.status = TelegramLinkingChallengeStatus.EXPIRED
            await session.flush()
