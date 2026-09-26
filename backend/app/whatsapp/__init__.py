from app.whatsapp.auth import (
    WhatsAppAuthenticatedIdentity,
    WhatsAppIdentityResolver,
    WhatsAppIncomingIdentity,
)
from app.whatsapp.baileys_adapter import register_baileys_provider
from app.whatsapp.models import (
    IncomingWhatsAppMessage,
    OutgoingWhatsAppMessage,
    WhatsAppConnectionEvent,
    WhatsAppConnectionState,
    WhatsAppContactIdentity,
    WhatsAppDeliveryStatus,
    WhatsAppMessageAttachment,
    WhatsAppMessageDirection,
    WhatsAppMessageType,
)
from app.whatsapp.provider import (
    WhatsAppProvider,
    WhatsAppProviderConfig,
    provider_registry,
)

# Register the Baileys provider on module import
register_baileys_provider()

__all__ = [
    "BaileysAdapter",
    "IncomingWhatsAppMessage",
    "OutgoingWhatsAppMessage",
    "WhatsAppAuthenticatedIdentity",
    "WhatsAppConnectionEvent",
    "WhatsAppConnectionState",
    "WhatsAppContactIdentity",
    "WhatsAppDeliveryStatus",
    "WhatsAppIdentityResolver",
    "WhatsAppIncomingIdentity",
    "WhatsAppMessageAttachment",
    "WhatsAppMessageDirection",
    "WhatsAppMessageType",
    "WhatsAppProvider",
    "WhatsAppProviderConfig",
    "provider_registry",
]
