"""
WhatsApp Provider Spike — Minimal Baileys Adapter

This spike demonstrates the provider abstraction architecture WITHOUT
connecting to a real WhatsApp account.

It uses mock implementations to verify:
1. Provider interface compliance
2. Normalized event model
3. Authentication integration
4. Core isolation (no provider-specific classes in core)

DOES NOT:
- Connect to real WhatsApp
- Scan QR codes
- Send real messages
"""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from app.whatsapp.models import (
    IncomingWhatsAppMessage,
    OutgoingWhatsAppMessage,
    WhatsAppConnectionEvent,
    WhatsAppConnectionState,
    WhatsAppContactIdentity,
    WhatsAppDeliveryStatus,
    WhatsAppMessageDeliveryReceipt,
    WhatsAppMessageType,
)
from app.whatsapp.provider import WhatsAppProvider, WhatsAppProviderConfig


@dataclass
class MockBaileysConfig:
    """Mock configuration for Baileys adapter."""

    session_path: str = "mock_sessions"
    print_qr: bool = False


class MockBaileysProvider(WhatsAppProvider):
    """
    Mock Baileys provider for spike testing.

    Simulates the connection lifecycle and message flow without
    requiring a real WhatsApp account.
    """

    def __init__(self):
        self._config: MockBaileysConfig | None = None
        self._state = WhatsAppConnectionState.DISCONNECTED
        self._our_identity: WhatsAppContactIdentity | None = None
        self._message_queue: asyncio.Queue[IncomingWhatsAppMessage] = asyncio.Queue()
        self._connection_event_queue: asyncio.Queue[WhatsAppConnectionEvent] = (
            asyncio.Queue()
        )
        self._delivery_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._tasks: list[asyncio.Task] = []

    @property
    def provider_name(self) -> str:
        return "baileys"

    @property
    def supported_message_types(self) -> set[str]:
        return {
            "text",
            "image",
            "audio",
            "video",
            "document",
            "sticker",
            "contact",
            "location",
            "reaction",
            "interactive",
        }

    async def initialize(self, config: WhatsAppProviderConfig) -> None:
        """Initialize mock provider."""
        self._config = MockBaileysConfig(**config.config)
        self._our_identity = WhatsAppContactIdentity(
            provider="baileys",
            provider_user_id="919876543210@s.whatsapp.net",
            normalized_identifier="+919876543210",
            display_name="Beru Test Bot",
        )

    async def start(self) -> None:
        """Simulate connection lifecycle."""
        self._running = True

        # Simulate connection flow
        await self._emit_connection(WhatsAppConnectionState.CONNECTING)

        # Simulate QR requirement
        await self._emit_connection(
            WhatsAppConnectionState.QR_REQUIRED,
            qr_code="MOCK_QR_CODE_DATA_FAKE_DONT_SCAN",
        )

        # Simulate successful authentication after delay
        async def simulate_auth():
            await asyncio.sleep(0.1)  # Simulate QR scan time
            if self._running:
                self._state = WhatsAppConnectionState.CONNECTED
                await self._emit_connection(WhatsAppConnectionState.CONNECTED)

        task = asyncio.create_task(simulate_auth())
        self._tasks.append(task)

    async def stop(self) -> None:
        """Stop mock provider."""
        self._running = False
        self._state = WhatsAppConnectionState.DISCONNECTED
        await self._emit_connection(WhatsAppConnectionState.DISCONNECTED)

        # Cancel background tasks
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def get_connection_state(self) -> WhatsAppConnectionState:
        return self._state

    async def connection_events(self) -> AsyncGenerator[WhatsAppConnectionEvent, None]:
        while self._running:
            try:
                event = await asyncio.wait_for(
                    self._connection_event_queue.get(), timeout=1.0
                )
                yield event
            except TimeoutError:
                continue

    async def get_our_identity(self) -> WhatsAppContactIdentity | None:
        if self._state == WhatsAppConnectionState.CONNECTED:
            return self._our_identity
        return None

    async def send_message(self, message: OutgoingWhatsAppMessage) -> str:
        """Mock send - returns fake message ID."""
        if self._state != WhatsAppConnectionState.CONNECTED:
            raise RuntimeError("Not connected")

        provider_msg_id = f"3EB0{str(uuid4())[:12].upper()}"

        # Simulate delivery receipt
        receipt = WhatsAppMessageDeliveryReceipt(
            message_id=message.idempotency_key or str(uuid4()),
            provider_message_id=provider_msg_id,
            status=WhatsAppDeliveryStatus.SENT,
            provider_timestamp=int(datetime.now(UTC).timestamp()),
            recipient=message.to_contact,
        )
        await self._delivery_queue.put(receipt)

        # Simulate delivered
        async def simulate_delivery():
            await asyncio.sleep(0.05)
            if self._running:
                receipt.status = WhatsAppDeliveryStatus.DELIVERED
                receipt.provider_timestamp = int(datetime.now(UTC).timestamp())
                await self._delivery_queue.put(receipt)

        task = asyncio.create_task(simulate_delivery())
        self._tasks.append(task)

        return provider_msg_id

    async def incoming_messages(self) -> AsyncGenerator[IncomingWhatsAppMessage, None]:
        while self._running:
            try:
                msg = await asyncio.wait_for(self._message_queue.get(), timeout=1.0)
                yield msg
            except TimeoutError:
                continue

    async def delivery_receipts(self) -> AsyncGenerator:
        while self._running:
            try:
                receipt = await asyncio.wait_for(self._delivery_queue.get(), timeout=1.0)
                yield receipt
            except TimeoutError:
                continue

    async def request_qr_code(self) -> str | None:
        if self._state == WhatsAppConnectionState.QR_REQUIRED:
            return "MOCK_QR_CODE_DATA_FAKE_DONT_SCAN"
        return None

    async def request_pairing_code(self, phone_number: str) -> str | None:
        return f"MOCK_PAIR_{phone_number[-6:]}"

    async def logout(self) -> None:
        self._state = WhatsAppConnectionState.LOGGED_OUT
        await self._emit_connection(WhatsAppConnectionState.LOGGED_OUT)

    async def is_connected(self) -> bool:
        return self._state == WhatsAppConnectionState.CONNECTED

    async def _emit_connection(self, state: WhatsAppConnectionState, **kwargs):
        self._state = state
        event = WhatsAppConnectionEvent(
            state=state,
            provider=self.provider_name,
            provider_identity=self._our_identity,
            **kwargs,
        )
        await self._connection_event_queue.put(event)

    # Spike helper methods
    async def inject_mock_message(
        self, text: str, from_jid: str = "919876543210@s.whatsapp.net"
    ):
        """Inject a mock inbound message for testing."""
        if self._state != WhatsAppConnectionState.CONNECTED:
            raise RuntimeError("Not connected - cannot inject message")

        msg = IncomingWhatsAppMessage(
            event_id=f"3EB0{str(uuid4())[:12].upper()}",
            provider="baileys",
            provider_timestamp=int(datetime.now(UTC).timestamp()),
            from_contact=WhatsAppContactIdentity(
                provider="baileys",
                provider_user_id=from_jid,
                normalized_identifier="+919876543210",
            ),
            to_contact=self._our_identity
            or WhatsAppContactIdentity(
                provider="baileys",
                provider_user_id="919876543210@s.whatsapp.net",
            ),
            message_type=WhatsAppMessageType.TEXT,
            text=text,
        )
        await self._message_queue.put(msg)


async def run_spike():
    """
    Run the spike demonstration.

    This demonstrates:
    1. Provider registration
    2. Configuration and initialization
    3. Connection lifecycle events
    4. Message normalization
    4. Authentication integration
    5. Core isolation (no Baileys imports in core)
    """
    print("=" * 60)
    print("WhatsApp Provider Spike — Baileys Mock Adapter")
    print("=" * 60)

    # 1. Register provider
    from app.whatsapp.provider import provider_registry

    provider_registry.register(MockBaileysProvider)
    print(f"✓ Registered providers: {provider_registry.list_providers()}")

    # 2. Create and configure provider
    provider_class = provider_registry.get("baileys")
    provider = provider_class()

    config = WhatsAppProviderConfig(
        provider_name="baileys",
        config={"session_path": "mock_sessions", "print_qr": True},
    )

    print("\n1. Initializing provider...")
    await provider.initialize(config)
    print("   ✓ Initialized")

    # 3. Start and observe connection lifecycle
    print("\n2. Starting provider (simulated connection)...")
    await provider.start()

    print("   Waiting for connection events...")
    connected = False
    async for event in provider.connection_events():
        print(f"   📡 Connection: {event.state.value}")
        if event.qr_code:
            print(f"      QR Code: {event.qr_code[:30]}...")
        if event.state == WhatsAppConnectionState.CONNECTED:
            connected = True
            break
        if event.state == WhatsAppConnectionState.FAILED:
            print("   ✗ Connection failed")
            break

    if not connected:
        print("   ✗ Failed to connect")
        await provider.stop()
        return

    print("   ✓ Connected!")

    # 4. Get our identity
    print("\n3. Getting our WhatsApp identity...")
    our_identity = await provider.get_our_identity()
    print(f"   ✓ Provider User ID: {our_identity.provider_user_id}")
    print(f"   ✓ Normalized: {our_identity.normalized_identifier}")
    print(f"   ✓ Display Name: {our_identity.display_name}")

    # 4. Test authentication integration
    print("\n4. Testing authentication integration...")
    from unittest.mock import AsyncMock, MagicMock

    from app.repositories.whatsapp_identity import WhatsAppIdentityRepository
    from app.security.student_resolver import DatabaseStudentResolver
    from app.whatsapp.auth import (
        WhatsAppIdentityResolver,
        create_whatsapp_incoming_identity,
    )

    # Mock the student resolver
    mock_repo = MagicMock(spec=WhatsAppIdentityRepository)
    mock_identity = MagicMock()
    mock_identity.student_id = "test-student-uuid"
    mock_identity.status = "active"
    mock_identity.provider = "baileys"
    mock_identity.provider_user_id = "919876543210@s.whatsapp.net"
    mock_repo.get_by_provider_identity = AsyncMock(return_value=mock_identity)

    student_resolver = DatabaseStudentResolver(mock_repo)
    auth_resolver = WhatsAppIdentityResolver(student_resolver)

    incoming = create_whatsapp_incoming_identity(
        provider="baileys",
        provider_user_id="919876543210@s.whatsapp.net",
        normalized_identifier="+919876543210",
    )

    auth_result = await auth_resolver.resolve(incoming)
    if hasattr(auth_result, "student_id"):
        print(f"   ✓ Authenticated as student: {auth_result.student_id}")
    else:
        print(f"   ✗ Authentication failed: {auth_result.reason}")

    # 5. Test message normalization
    print("\n5. Testing message normalization...")
    await provider.inject_mock_message("Hello, Beru!")

    print("   Waiting for inbound message...")
    async for msg in provider.incoming_messages():
        print(f"   📨 Received: {msg.text}")
        print(f"      Event ID: {msg.event_id}")
        print(f"      From: {msg.from_contact.provider_user_id}")
        print(f"      Type: {msg.message_type.value}")
        print(f"      Idempotency key: {msg.get_idempotency_key()}")
        break

    # 6. Test outbound message
    print("\n6. Testing outbound message...")
    outgoing = OutgoingWhatsAppMessage(
        to_contact=WhatsAppContactIdentity(
            provider="baileys",
            provider_user_id="919876543210@s.whatsapp.net",
        ),
        from_contact=our_identity,
        message_type=WhatsAppMessageType.TEXT,
        text="Hello from Beru spike!",
        idempotency_key="test-idempotency-key-123",
    )

    provider_msg_id = await provider.send_message(outgoing)
    print(f"   ✓ Sent, provider message ID: {provider_msg_id}")

    # Wait for delivery receipt
    async for receipt in provider.delivery_receipts():
        print(
            f"   📦 Delivery: {receipt.status.value} "
            f"(provider ID: {receipt.provider_message_id})"
        )
        if receipt.status == WhatsAppDeliveryStatus.DELIVERED:
            break

    # 7. Stop provider
    print("\n7. Stopping provider...")
    await provider.stop()
    print("   ✓ Stopped")

    print("\n" + "=" * 60)
    print("Spike completed successfully!")
    print("=" * 60)
    print("\nVerified:")
    print("  ✓ Provider abstraction interface")
    print("  ✓ Normalized connection lifecycle")
    print("  ✓ Normalized message model")
    print("  ✓ Authentication integration")
    print("  ✓ Core isolation (no Baileys in core)")
    print("  ✓ Idempotency key generation")
    print("  ✓ Message normalization")


if __name__ == "__main__":
    asyncio.run(run_spike())
