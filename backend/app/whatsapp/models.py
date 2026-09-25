from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class WhatsAppMessageType(str, Enum):  # noqa: UP042
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    STICKER = "sticker"
    CONTACT = "contact"
    LOCATION = "location"
    REACTION = "reaction"
    INTERACTIVE = "interactive"
    UNKNOWN = "unknown"


class WhatsAppMessageDirection(str, Enum):  # noqa: UP042
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class WhatsAppDeliveryStatus(str, Enum):  # noqa: UP042
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


class WhatsAppConnectionState(str, Enum):  # noqa: UP042
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    QR_REQUIRED = "qr_required"
    PAIRING_CODE = "pairing_code"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"
    LOGGED_OUT = "logged_out"


@dataclass(frozen=True, slots=True)
class WhatsAppContactIdentity:
    """Normalized contact identity from any WhatsApp provider."""

    provider: str
    provider_user_id: str  # e.g., "919876543210@s.whatsapp.net" (Baileys)
    # or "919876543210" (Cloud API)
    normalized_identifier: str | None = None  # E.164 format if available
    display_name: str | None = None
    is_business: bool = False


@dataclass(frozen=True, slots=True)
class WhatsAppMessageAttachment:
    """Normalized media attachment."""

    media_type: WhatsAppMessageType
    mime_type: str
    file_name: str | None = None
    file_size: int | None = None
    media_key: str | None = None
    url: str | None = None  # Provider-specific download URL
    sha256: str | None = None
    caption: str | None = None


@dataclass(frozen=True, slots=True)
class WhatsAppInteractiveReply:
    """Normalized interactive message reply (button/list)."""

    reply_id: str
    title: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class IncomingWhatsAppMessage:
    """Normalized inbound message from any WhatsApp provider."""

    # Identity
    event_id: str  # Provider-specific event/message ID (for idempotency)
    provider: str
    provider_timestamp: int  # Unix timestamp from provider

    # Contact
    from_contact: WhatsAppContactIdentity
    to_contact: WhatsAppContactIdentity  # Our WhatsApp identity

    # Content
    message_type: WhatsAppMessageType
    text: str | None = None
    attachment: WhatsAppMessageAttachment | None = None
    interactive_reply: WhatsAppInteractiveReply | None = None

    # Context
    quoted_message_id: str | None = None
    is_forwarded: bool = False
    is_from_me: bool = False  # Should always be False for inbound

    # Metadata
    raw_provider_data: dict | None = None  # Preserved for debugging (not logged)
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def get_idempotency_key(self) -> str:
        """Generate idempotency key from provider event ID."""
        return f"whatsapp:{self.provider}:{self.event_id}"


@dataclass(frozen=True, slots=True)
class OutgoingWhatsAppMessage:
    """Normalized outbound message to any WhatsApp provider."""

    # Identity
    to_contact: WhatsAppContactIdentity
    from_contact: WhatsAppContactIdentity  # Our WhatsApp identity

    # Content
    message_type: WhatsAppMessageType
    text: str | None = None
    attachment: WhatsAppMessageAttachment | None = None
    interactive_reply: WhatsAppInteractiveReply | None = None

    # Context
    quoted_message_id: str | None = None

    # Metadata
    provider: str | None = None  # If None, use default provider
    idempotency_key: str | None = None  # Client-generated for deduplication


@dataclass(frozen=True, slots=True)
class WhatsAppMessageDeliveryReceipt:
    """Normalized delivery status update."""

    message_id: str  # Our internal message ID
    provider_message_id: str  # Provider's message ID (e.g., WA message ID)
    status: WhatsAppDeliveryStatus
    provider_timestamp: int
    recipient: WhatsAppContactIdentity
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class WhatsAppConnectionEvent:
    """Normalized connection state change event."""

    state: WhatsAppConnectionState
    provider: str
    provider_identity: WhatsAppContactIdentity | None = None
    qr_code: str | None = None
    pairing_code: str | None = None
    error_message: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
