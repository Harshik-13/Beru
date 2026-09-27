from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telegram_linking_challenge import (
    TelegramLinkingChallenge,
    TelegramLinkingChallengeStatus,
)


class TelegramLinkingChallengeRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        *,
        telegram_user_id: str,
        challenge_token: str,
        expires_at: str,  # ISO format datetime string
    ) -> "TelegramLinkingChallenge":
        from datetime import datetime

        from app.models.telegram_linking_challenge import TelegramLinkingChallenge

        challenge = TelegramLinkingChallenge(
            telegram_user_id=telegram_user_id,
            challenge_token=challenge_token,
            expires_at=datetime.fromisoformat(expires_at.replace("Z", "+00:00")),
        )
        self._session.add(challenge)
        await self._session.flush()
        return challenge

    async def get_by_token(
        self, challenge_token: str
    ) -> "TelegramLinkingChallenge | None":
        from app.models.telegram_linking_challenge import TelegramLinkingChallenge

        result = await self._session.execute(
            select(TelegramLinkingChallenge).where(
                TelegramLinkingChallenge.challenge_token == challenge_token
            )
        )
        return result.scalar_one_or_none()

    async def get_by_telegram_user_id(
        self, telegram_user_id: str
    ) -> list["TelegramLinkingChallenge"]:
        from app.models.telegram_linking_challenge import TelegramLinkingChallenge

        result = await self._session.execute(
            select(TelegramLinkingChallenge).where(
                TelegramLinkingChallenge.telegram_user_id == telegram_user_id
            )
        )
        return list(result.scalars().all())

    async def get_pending_by_telegram_user_id(
        self, telegram_user_id: str
    ) -> "TelegramLinkingChallenge | None":
        from datetime import UTC, datetime

        from app.models.telegram_linking_challenge import (
            TelegramLinkingChallenge,
        )

        result = await self._session.execute(
            select(TelegramLinkingChallenge).where(
                TelegramLinkingChallenge.telegram_user_id == telegram_user_id,
                TelegramLinkingChallenge.status == TelegramLinkingChallengeStatus.PENDING,
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

        challenge.status = TelegramLinkingChallengeStatus.USED
        challenge.student_id = student_id
        challenge.telegram_identity_id = telegram_identity_id
        await self._session.flush()

    async def mark_expired(self, challenge: "TelegramLinkingChallenge") -> None:

        challenge.status = TelegramLinkingChallengeStatus.EXPIRED
        await self._session.flush()
