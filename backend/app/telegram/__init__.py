from app.telegram.auth import (
    TelegramAuthenticatedIdentity,
    TelegramIdentityResolver,
    TelegramIncomingIdentity,
    create_telegram_incoming_identity,
)
from app.telegram.bot_adapter import register_telegram_provider
from app.telegram.linking_service import (
    TelegramLinkingService,
    TelegramLinkingError,
    ChallengeExpiredError,
    ChallengeAlreadyUsedError,
    ChallengeInvalidError,
    TelegramIdentityAlreadyLinkedError,
    TelegramIdentityLinkedToAnotherStudentError,
    StudentAlreadyHasTelegramIdentityError,
    StudentNotFoundError,
    TelegramLinkingResult,
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
    "IncomingTelegramMessage",
    "OutgoingTelegramMessage",
    "TelegramAuthenticatedIdentity",
    "TelegramBotAdapter",
    "TelegramConnectionEvent",
    "TelegramContactIdentity",
    "TelegramDeliveryStatus",
    "TelegramIdentityResolver",
    "TelegramIncomingIdentity",
    "TelegramLinkingService",
    "TelegramLinkingError",
    "ChallengeExpiredError",
    "ChallengeAlreadyUsedError",
    "ChallengeInvalidError",
    "TelegramIdentityAlreadyLinkedError",
    "TelegramIdentityLinkedToAnotherStudentError",
    "StudentAlreadyHasTelegramIdentityError",
    "StudentNotFoundError",
    "TelegramLinkingResult",
    "TelegramMessageAttachment",
    "TelegramMessageDirection",
    "TelegramMessageType",
    "TelegramProvider",
    "TelegramProviderConfig",
    "telegram_provider_registry",
    "create_telegram_incoming_identity",
]
