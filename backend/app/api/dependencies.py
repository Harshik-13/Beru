from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.repositories.whatsapp_identity import WhatsAppIdentityRepository
from app.security.audit import AuditService
from app.security.authorization_service import AuthorizationService
from app.security.context import (
    AuthenticatedIdentity,
    UnauthenticatedIdentity,
)
from app.security.student_resolver import DatabaseStudentResolver


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


async def get_identity_repo(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WhatsAppIdentityRepository:
    return WhatsAppIdentityRepository(session)


async def get_student_resolver(
    identity_repo: Annotated[WhatsAppIdentityRepository, Depends(get_identity_repo)],
) -> DatabaseStudentResolver:
    return DatabaseStudentResolver(identity_repo)


async def get_audit_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuditService:
    return AuditService(session)


async def get_authorization_service(
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
) -> AuthorizationService:
    return AuthorizationService(audit_service)


async def resolve_identity_from_request(
    request: Request,
    student_resolver: Annotated[DatabaseStudentResolver, Depends(get_student_resolver)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
) -> AuthenticatedIdentity | UnauthenticatedIdentity:
    """
    Resolve identity from request.

    This is the main entry point for authentication. The actual extraction
    of provider/external_identity_id depends on the WhatsApp bridge implementation.
    For now, we extract from headers (placeholder for future bridge integration).
    """
    # In the real implementation, these would come from the WhatsApp bridge
    # For now, we use headers as a placeholder for testing
    provider = request.headers.get("X-WhatsApp-Provider")
    external_identity_id = request.headers.get("X-WhatsApp-Identity")

    if not provider or not external_identity_id:
        return UnauthenticatedIdentity(
            provider="unknown",
            external_identity_id="unknown",
            reason="Missing authentication headers",
        )

    identity = await student_resolver.get_student_for_identity(
        provider, external_identity_id
    )

    if identity is None:
        await audit_service.log_authentication_failure(
            provider=provider,
            external_identity_id=external_identity_id,
            reason="Identity not found or not active",
        )
        return UnauthenticatedIdentity(
            provider=provider,
            external_identity_id=external_identity_id,
            reason="Identity not found or not active",
        )

    await audit_service.log_authentication_success(
        student_id=identity.student_id,
        provider=identity.provider,
        external_identity_id=identity.external_identity_id,
    )

    return identity


async def get_authenticated_student(
    identity: Annotated[
        AuthenticatedIdentity | UnauthenticatedIdentity,
        Depends(resolve_identity_from_request),
    ],
) -> AuthenticatedIdentity:
    """Dependency that ensures the request is authenticated and returns the identity."""
    if isinstance(identity, UnauthenticatedIdentity):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=identity.reason,
        )
    return identity


async def get_current_student_id(
    identity: Annotated[AuthenticatedIdentity, Depends(get_authenticated_student)],
) -> str:
    """Get the current student's UUID as string."""
    return str(identity.student_id)
