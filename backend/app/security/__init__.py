from app.security.audit import AuditService
from app.security.authentication import (
    AuthenticationResolver,
    IncomingIdentity,
    StudentResolver,
)
from app.security.authorization import (
    AuthorizationError,
    authorize_student_access,
    authorize_student_resource,
    require_authenticated_identity,
    require_student,
)
from app.security.authorization_service import AuthorizationService
from app.security.context import (
    AuthenticatedIdentity,
    AuthenticationMethod,
    IdentityResolutionResult,
    UnauthenticatedIdentity,
)
from app.security.student_resolver import DatabaseStudentResolver

__all__ = [
    "AuditService",
    "AuthenticatedIdentity",
    "AuthenticationMethod",
    "AuthenticationResolver",
    "AuthorizationError",
    "AuthorizationService",
    "DatabaseStudentResolver",
    "IdentityResolutionResult",
    "IncomingIdentity",
    "StudentResolver",
    "UnauthenticatedIdentity",
    "authorize_student_access",
    "authorize_student_resource",
    "require_authenticated_identity",
    "require_student",
]
