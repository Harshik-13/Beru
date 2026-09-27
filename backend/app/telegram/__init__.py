from app.telegram.auth import (
    TelegramAuthenticatedIdentity,
    TelegramIdentityResolver,
    TelegramIncomingIdentity,
)
from app.telegram.bot_adapter import register_telegram_provider
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
    "TelegramMessageAttachment",
    "TelegramMessageDirection",
    "TelegramMessageType",
    "TelegramProvider",
    "TelegramProviderConfig",
    "telegram_provider_registry",
]
