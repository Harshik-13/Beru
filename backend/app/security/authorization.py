from uuid import UUID

from app.security.context import AuthenticatedIdentity


class AuthorizationError(Exception):
    """Raised when authorization fails."""

    def __init__(
        self,
        message: str,
        resource_type: str | None = None,
        resource_id: UUID | None = None,
    ):
        super().__init__(message)
        self.resource_type = resource_type
        self.resource_id = resource_id


def require_authenticated_identity(
    identity: AuthenticatedIdentity | None,
) -> AuthenticatedIdentity:
    """Ensure an authenticated identity is present."""
    if identity is None:
        raise AuthorizationError("Authentication required")
    return identity


def require_student(identity: AuthenticatedIdentity) -> UUID:
    """Extract student ID from authenticated identity."""
    return identity.student_id


def authorize_student_resource(
    authenticated_student_id: UUID,
    resource_owner_id: UUID,
    resource_type: str = "resource",
    resource_id: UUID | None = None,
) -> None:
    """
    Enforce that the authenticated student owns the resource.

    Raises AuthorizationError if the student IDs don't match.
    """
    if authenticated_student_id != resource_owner_id:
        raise AuthorizationError(
            f"Unauthorized access to {resource_type}",
            resource_type=resource_type,
            resource_id=resource_id,
        )


def authorize_student_access(
    authenticated_student_id: UUID,
    target_student_id: UUID,
    action: str = "access",
) -> None:
    """
    Enforce that the authenticated student can access another student's data.

    Currently only allows self-access. Future: could allow admin, parents, etc.
    """
    if authenticated_student_id != target_student_id:
        raise AuthorizationError(
            f"Student not authorized to {action} another student's data"
        )
