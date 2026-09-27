
from app.models.telegram_identity import TelegramIdentityStatus
from app.models.whatsapp_identity import WhatsAppIdentityStatus
from app.repositories.telegram_identity import TelegramIdentityRepository
from app.repositories.whatsapp_identity import WhatsAppIdentityRepository
from app.security.authentication import StudentResolver
from app.security.context import AuthenticatedIdentity, AuthenticationMethod


class DatabaseStudentResolver(StudentResolver):
    """Resolves students from WhatsApp/Telegram identities using the database."""

    def __init__(
        self,
        whatsapp_identity_repo: WhatsAppIdentityRepository,
        telegram_identity_repo: TelegramIdentityRepository,
    ):
        self._whatsapp_repo = whatsapp_identity_repo
        self._telegram_repo = telegram_identity_repo

    async def get_student_for_identity(
        self, provider: str, external_identity_id: str
    ) -> AuthenticatedIdentity | None:
        if provider == "telegram_bot":
            return await self._get_student_from_telegram(external_identity_id)
        else:
            # Default to WhatsApp for backwards compatibility
            return await self._get_student_from_whatsapp(provider, external_identity_id)

    async def _get_student_from_telegram(
        self, external_identity_id: str
    ) -> AuthenticatedIdentity | None:
        identity = await self._telegram_repo.get_by_provider_identity(
            "telegram_bot", external_identity_id
        )

        if identity is None:
            return None

        if identity.status != TelegramIdentityStatus.ACTIVE:
            return None

        return AuthenticatedIdentity(
            provider=identity.provider.value,
            external_identity_id=identity.provider_user_id,
            student_id=identity.student_id,
            authentication_method=AuthenticationMethod.BAILEYS,
        )

    async def _get_student_from_whatsapp(
        self, provider: str, external_identity_id: str
    ) -> AuthenticatedIdentity | None:
        identity = await self._whatsapp_repo.get_by_provider_identity(
            provider, external_identity_id
        )

        if identity is None:
            return None

        if identity.status != WhatsAppIdentityStatus.ACTIVE:
            return None

        try:
            auth_method = AuthenticationMethod(provider)
        except ValueError:
            auth_method = AuthenticationMethod.WHATSAPP_WEB_JS

        return AuthenticatedIdentity(
            provider=identity.provider,
            external_identity_id=identity.provider_user_id,
            student_id=identity.student_id,
            authentication_method=auth_method,
        )

    async def get_identity_status(
        self, provider: str, external_identity_id: str
    ) -> str | None:
        if provider == "telegram_bot":
            identity = await self._telegram_repo.get_by_provider_identity(
                "telegram_bot", external_identity_id
            )
        else:
            identity = await self._whatsapp_repo.get_by_provider_identity(
                provider, external_identity_id
            )

        if identity is None:
            return "unknown"

        return str(identity.status.value)
