from app.telegram.auth import (
    TelegramAuthenticatedIdentity,
    TelegramIdentityResolver,
    TelegramIncomingIdentity,
    create_telegram_incoming_identity,
)
from app.telegram.bot_adapter import register_telegram_provider
from app.telegram.linking_service import (
    ChallengeAlreadyUsedError,
    ChallengeExpiredError,
    ChallengeInvalidError,
    StudentAlreadyHasTelegramIdentityError,
    StudentNotFoundError,
    TelegramIdentityAlreadyLinkedError,
    TelegramIdentityLinkedToAnotherStudentError,
    TelegramLinkingError,
    TelegramLinkingResult,
    TelegramLinkingService,
)
from app.telegram.models import (
    IncomingTelegramMessage,
    OutgoingTelegramMessage,
    TelegramConnectionEvent,
    TelegramContactIdentity,
    TelegramDeliveryStatus,
    TelegramMessageAttachment,
    TelegramMessageDirection,
    TelegramMessageType,
)
from app.telegram.provider import (
    TelegramProvider,
    TelegramProviderConfig,
    telegram_provider_registry,
)

# Register the Telegram provider on module import
register_telegram_provider()

__all__ = [
    "ChallengeAlreadyUsedError",
    "ChallengeExpiredError",
    "ChallengeInvalidError",
    "IncomingTelegramMessage",
    "OutgoingTelegramMessage",
    "StudentAlreadyHasTelegramIdentityError",
    "StudentNotFoundError",
    "TelegramAuthenticatedIdentity",
    "TelegramBotAdapter",
    "TelegramConnectionEvent",
    "TelegramContactIdentity",
    "TelegramDeliveryStatus",
    "TelegramIdentityAlreadyLinkedError",
    "TelegramIdentityLinkedToAnotherStudentError",
    "TelegramIdentityResolver",
    "TelegramIncomingIdentity",
    "TelegramLinkingError",
    "TelegramLinkingResult",
    "TelegramLinkingService",
    "TelegramMessageAttachment",
    "TelegramMessageDirection",
    "TelegramMessageType",
    "TelegramProvider",
    "TelegramProviderConfig",
    "create_telegram_incoming_identity",
    "telegram_provider_registry",
]
