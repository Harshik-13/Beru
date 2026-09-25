from app.models.whatsapp_identity import WhatsAppIdentityStatus
from app.repositories.whatsapp_identity import WhatsAppIdentityRepository
from app.security.authentication import StudentResolver
from app.security.context import AuthenticatedIdentity, AuthenticationMethod


class DatabaseStudentResolver(StudentResolver):
    """Resolves students from WhatsApp identities using the database."""

    def __init__(self, identity_repo: WhatsAppIdentityRepository):
        self._identity_repo = identity_repo

    async def get_student_for_identity(
        self, provider: str, external_identity_id: str
    ) -> AuthenticatedIdentity | None:
        identity = await self._identity_repo.get_by_provider_identity(
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
        identity = await self._identity_repo.get_by_provider_identity(
            provider, external_identity_id
        )

        if identity is None:
            return "unknown"

        return identity.status.value
