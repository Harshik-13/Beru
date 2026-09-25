from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from app.whatsapp.models import (
    IncomingWhatsAppMessage,
    OutgoingWhatsAppMessage,
    WhatsAppConnectionEvent,
    WhatsAppConnectionState,
    WhatsAppContactIdentity,
    WhatsAppMessageDeliveryReceipt,
)


@dataclass(frozen=True, slots=True)
class WhatsAppProviderConfig:
    """Configuration for a WhatsApp provider instance."""

    provider_name: str
    config: dict  # Provider-specific configuration


class WhatsAppProvider(ABC):
    """
    Abstract interface for WhatsApp providers.

    All provider implementations must conform to this interface.
    The Beru core never imports provider-specific classes directly.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique provider identifier (e.g., 'baileys', 'meta_cloud_api')."""
        ...

    @property
    @abstractmethod
    def supported_message_types(self) -> set[str]:
        """Set of supported WhatsAppMessageType values."""
        ...

    @abstractmethod
    async def initialize(self, config: WhatsAppProviderConfig) -> None:
        """Initialize the provider with configuration."""
        ...

    @abstractmethod
    async def start(self) -> None:
        """Start the provider (connect, begin listening)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the provider gracefully."""
        ...

    @abstractmethod
    async def get_connection_state(self) -> WhatsAppConnectionState:
        """Get current connection state."""
        ...

    @abstractmethod
    async def connection_events(self) -> AsyncGenerator[WhatsAppConnectionEvent, None]:
        """Async generator yielding connection state changes."""
        ...

    @abstractmethod
    async def get_our_identity(self) -> WhatsAppContactIdentity | None:
        """Get our own WhatsApp identity (after connection)."""
        ...

    @abstractmethod
    async def send_message(self, message: OutgoingWhatsAppMessage) -> str:
        """
        Send a message.

        Returns:
            Provider's message ID (e.g., WhatsApp message ID)
        """
        ...

    @abstractmethod
    async def incoming_messages(self) -> AsyncGenerator[IncomingWhatsAppMessage, None]:
        """Async generator yielding normalized inbound messages."""
        ...

    @abstractmethod
    async def delivery_receipts(
        self,
    ) -> AsyncGenerator["WhatsAppMessageDeliveryReceipt", None]:
        """Async generator yielding delivery status updates."""
        ...

    @abstractmethod
    async def request_qr_code(self) -> str | None:
        """Request QR code for pairing. Returns QR code data if supported."""
        ...

    @abstractmethod
    async def request_pairing_code(self, phone_number: str) -> str | None:
        """Request pairing code for phone number. Returns code if supported."""
        ...

    @abstractmethod
    async def logout(self) -> None:
        """Log out and clear session."""
        ...

    @abstractmethod
    async def is_connected(self) -> bool:
        """Check if currently connected and authenticated."""
        ...


class WhatsAppProviderRegistry:
    """Registry for WhatsApp provider implementations."""

    def __init__(self):
        self._providers: dict[str, type[WhatsAppProvider]] = {}

    def register(self, provider_class: type[WhatsAppProvider]) -> None:
        """Register a provider implementation."""
        instance = provider_class()
        self._providers[instance.provider_name] = provider_class

    def get(self, provider_name: str) -> type[WhatsAppProvider]:
        """Get a registered provider class by name."""
        if provider_name not in self._providers:
            raise ValueError(f"Provider not registered: {provider_name}")
        return self._providers[provider_name]

    def list_providers(self) -> list[str]:
        """List registered provider names."""
        return list(self._providers.keys())


# Global registry instance
provider_registry = WhatsAppProviderRegistry()
