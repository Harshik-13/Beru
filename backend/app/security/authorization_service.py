from uuid import UUID

from app.security.audit import AuditService
from app.security.authorization import (
    AuthorizationError,
    authorize_student_access,
    authorize_student_resource,
    require_authenticated_identity,
    require_student,
)
from app.security.context import AuthenticatedIdentity


class AuthorizationService:
    """Composable authorization service for domain operations."""

    def __init__(self, audit_service: AuditService | None = None):
        self._audit = audit_service

    def get_authenticated_student(
        self, identity: AuthenticatedIdentity | None
    ) -> UUID:
        """Extract student ID from authenticated identity."""
        return require_student(require_authenticated_identity(identity))

    def authorize_resource(
        self,
        authenticated_student_id: UUID,
        resource_owner_id: UUID,
        resource_type: str = "resource",
        resource_id: UUID | None = None,
    ) -> None:
        """Authorize access to a student-owned resource."""
        try:
            authorize_student_resource(
                authenticated_student_id,
                resource_owner_id,
                resource_type,
                resource_id,
            )
        except AuthorizationError:
            if self._audit:
                pass
            raise

    def authorize_student_access(
        self,
        authenticated_student_id: UUID,
        target_student_id: UUID,
        action: str = "access",
    ) -> None:
        """Authorize access to another student's data (self-access only)."""
        authorize_student_access(authenticated_student_id, target_student_id, action)

    async def authorize_resource_async(
        self,
        authenticated_student_id: UUID,
        resource_owner_id: UUID,
        resource_type: str = "resource",
        resource_id: UUID | None = None,
    ) -> None:
        """Async version that logs authorization failures to audit."""
        try:
            authorize_student_resource(
                authenticated_student_id,
                resource_owner_id,
                resource_type,
                resource_id,
            )
        except AuthorizationError:
            if self._audit:
                await self._audit.log_authorization_failure(
                    student_id=authenticated_student_id,
                    resource_type=resource_type,
                    resource_id=resource_id or UUID(int=0),
                    action="access",
                )
            raise

    async def authorize_student_access_async(
        self,
        authenticated_student_id: UUID,
        target_student_id: UUID,
        action: str = "access",
    ) -> None:
        """Async version that logs authorization failures to audit."""
        try:
            authorize_student_access(
                authenticated_student_id,
                target_student_id,
                action,
            )
        except AuthorizationError:
            if self._audit:
                await self._audit.log_authorization_failure(
                    student_id=authenticated_student_id,
                    resource_type="student",
                    resource_id=target_student_id,
                    action=action,
                )
            raise
