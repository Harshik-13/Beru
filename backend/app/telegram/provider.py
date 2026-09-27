from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from app.telegram.models import (
    IncomingTelegramMessage,
    OutgoingTelegramMessage,
    TelegramConnectionEvent,
    TelegramContactIdentity,
    TelegramMessageDeliveryReceipt,
)


@dataclass(frozen=True, slots=True)
class TelegramProviderConfig:
    """Configuration for a Telegram provider instance."""

    provider_name: str
    config: dict  # Provider-specific configuration


class TelegramProvider(ABC):
    """
    Abstract interface for Telegram providers.

    All provider implementations must conform to this interface.
    The Beru core never imports provider-specific classes directly.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique provider identifier (e.g., 'telegram_bot')."""
        ...

    @property
    @abstractmethod
    def supported_message_types(self) -> set[str]:
        """Set of supported TelegramMessageType values."""
        ...

    @abstractmethod
    async def initialize(self, config: TelegramProviderConfig) -> None:
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
    async def get_connection_state(self) -> str:
        """Get current connection state."""
        ...

    @abstractmethod
    async def connection_events(self) -> AsyncGenerator[TelegramConnectionEvent, None]:
        """Async generator yielding connection state changes."""
        ...

    @abstractmethod
    async def get_our_identity(self) -> TelegramContactIdentity | None:
        """Get our own Telegram identity (after connection)."""
        ...

    @abstractmethod
    async def send_message(self, message: OutgoingTelegramMessage) -> str:
        """
        Send a message.

        Returns:
            Provider's message ID (e.g., Telegram message ID)
        """
        ...

    @abstractmethod
    async def incoming_messages(self) -> AsyncGenerator[IncomingTelegramMessage, None]:
        """Async generator yielding normalized inbound messages."""
        ...

    @abstractmethod
    async def delivery_receipts(
        self,
    ) -> AsyncGenerator[TelegramMessageDeliveryReceipt, None]:
        """Async generator yielding delivery status updates."""
        ...


class TelegramProviderRegistry:
    """Registry for Telegram provider implementations."""

    def __init__(self):
        self._providers: dict[str, type[TelegramProvider]] = {}

    def register(self, provider_class: type[TelegramProvider]) -> None:
        """Register a provider implementation."""
        instance = provider_class()
        self._providers[instance.provider_name] = provider_class

    def get(self, provider_name: str) -> type[TelegramProvider]:
        """Get a registered provider class by name."""
        if provider_name not in self._providers:
            raise ValueError(f"Provider not registered: {provider_name}")
        return self._providers[provider_name]

    def list_providers(self) -> list[str]:
        """List registered provider names."""
        return list(self._providers.keys())


# Global registry instance
telegram_provider_registry = TelegramProviderRegistry()
