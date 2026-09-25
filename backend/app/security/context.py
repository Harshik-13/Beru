from dataclasses import dataclass
from enum import Enum
from uuid import UUID


class AuthenticationMethod(str, Enum):  # noqa: UP042
    WHATSAPP_WEB_JS = "whatsapp_web_js"
    BAILEYS = "baileys"
    META_CLOUD_API = "meta_cloud_api"
    INTERNAL_ADMIN = "internal_admin"


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    """Represents a verified identity from an authentication provider."""

    provider: str
    external_identity_id: str
    student_id: UUID
    authentication_method: AuthenticationMethod

    def __repr__(self) -> str:
        return (
            f"AuthenticatedIdentity(provider={self.provider!r}, "
            f"external_identity_id={self.external_identity_id!r}, "
            f"student_id={self.student_id})"
        )


@dataclass(frozen=True, slots=True)
class UnauthenticatedIdentity:
    """Represents an identity that could not be authenticated."""

    provider: str
    external_identity_id: str
    reason: str

    def __repr__(self) -> str:
        return (
            f"UnauthenticatedIdentity(provider={self.provider!r}, "
            f"external_identity_id={self.external_identity_id!r}, "
            f"reason={self.reason!r})"
        )


IdentityResolutionResult = AuthenticatedIdentity | UnauthenticatedIdentity
