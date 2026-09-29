from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class TelegramMessageType(str, Enum):  # noqa: UP042
    TEXT = "text"
    PHOTO = "photo"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    STICKER = "sticker"
    CONTACT = "contact"
    LOCATION = "location"
    VOICE = "voice"
    VIDEO_NOTE = "video_note"
    ANIMATION = "animation"
    POLL = "poll"
    UNKNOWN = "unknown"


class TelegramMessageDirection(str, Enum):  # noqa: UP042
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class TelegramDeliveryStatus(str, Enum):  # noqa: UP042
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TelegramContactIdentity:
    """Normalized contact identity from Telegram."""

    provider: str  # e.g., "telegram_bot"
    provider_user_id: str  # Telegram user ID (e.g., "123456789")
    normalized_identifier: str | None = None  # Username if available
    display_name: str | None = None
    is_bot: bool = False
    is_premium: bool = False
    language_code: str | None = None


@dataclass(frozen=True, slots=True)
class TelegramMessageAttachment:
    """Normalized media attachment from Telegram."""

    media_type: TelegramMessageType
    mime_type: str | None = None
    file_name: str | None = None
    file_size: int | None = None
    file_id: str | None = None  # Telegram file ID for download
    file_unique_id: str | None = None
    caption: str | None = None


@dataclass(frozen=True, slots=True)
class TelegramInteractiveReply:
    """Normalized interactive message reply (callback query)."""

    reply_id: str
    data: str | None = None
    message_text: str | None = None


@dataclass(frozen=True, slots=True)
class IncomingTelegramMessage:
    """Normalized inbound message from Telegram."""

    # Identity (required, no defaults)
    event_id: str  # Telegram update ID + message ID for idempotency
    provider: str
    provider_timestamp: int  # Unix timestamp from Telegram

    # Contact (required, no defaults)
    from_contact: TelegramContactIdentity
    to_contact: TelegramContactIdentity  # Our bot identity

    # Content (required, no defaults)
    message_type: TelegramMessageType

    # Metadata (required, no defaults)
    chat_id: str  # Telegram chat ID (for routing replies) - required

    # Content (optional, with defaults)
    text: str | None = None
    attachment: TelegramMessageAttachment | None = None
    interactive_reply: TelegramInteractiveReply | None = None

    # Context (optional, with defaults)
    reply_to_message_id: str | None = None
    is_forwarded: bool = False
    is_from_me: bool = False  # Should always be False for inbound
    raw_provider_data: dict[str, Any] | None = None  # Preserved for debugging
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def get_idempotency_key(self) -> str:
        """Generate idempotency key from provider event ID."""
        return f"telegram:{self.provider}:{self.event_id}"


@dataclass(frozen=True, slots=True)
class OutgoingTelegramMessage:
    """Normalized outbound message to Telegram."""

    # Identity (required, no defaults)
    to_contact: TelegramContactIdentity
    from_contact: TelegramContactIdentity  # Our bot identity

    # Content (required, no defaults)
    message_type: TelegramMessageType

    # Metadata (required, no defaults)
    chat_id: str  # Target Telegram chat ID

    # Content (optional, with defaults)
    text: str | None = None
    attachment: TelegramMessageAttachment | None = None
    interactive_reply: TelegramInteractiveReply | None = None

    # Context (optional, with defaults)
    reply_to_message_id: str | None = None
    parse_mode: str | None = None

    # Metadata (optional, with defaults)
    provider: str | None = None  # If None, use default provider
    idempotency_key: str | None = None  # Client-generated for deduplication


@dataclass(frozen=True, slots=True)
class TelegramMessageDeliveryReceipt:
    """Normalized delivery status update (not typically available in Bot API)."""

    message_id: str  # Our internal message ID
    provider_message_id: str  # Telegram message ID
    status: TelegramDeliveryStatus
    provider_timestamp: int
    recipient: TelegramContactIdentity
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class TelegramConnectionEvent:
    """Normalized connection state change event."""

    state: str  # e.g., "connected", "disconnected", "polling"
    provider: str
    provider_identity: TelegramContactIdentity | None = None
    error_message: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
