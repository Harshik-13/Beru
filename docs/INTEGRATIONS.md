# Integrations — Beru

All external integrations are behind abstraction interfaces. The core application depends on the interface, not the concrete provider.

## WhatsApp

### Status
- **Investigation**: ✅ Complete (see `docs/ADR/004-whatsapp-provider.md`)
- **Provider Abstraction**: ✅ Implemented (`app/whatsapp/provider.py`)
- **Normalized Models**: ✅ Implemented (`app/whatsapp/models.py`)
- **Authentication Integration**: ✅ Implemented (`app/whatsapp/auth.py`)
- **Spike Implementation**: ✅ Mock spike (`app/whatsapp/spike.py`)
- **Core Isolation Tests**: ✅ Implemented (`backend/tests/test_whatsapp_isolation.py`)

### Architecture

```
WhatsApp Provider (Baileys/Meta/etc.)
        ↓
Provider Adapter (implements WhatsAppProvider interface)
        ↓
Normalized Events (IncomingWhatsAppMessage, WhatsAppConnectionEvent, etc.)
        ↓
WhatsAppGateway (internal routing)
        ↓
AuthenticationResolver → StudentResolver → AuthenticatedIdentity
        ↓
AuthorizationService → Application Services
```

### Provider Abstraction

**Interface**: `app/whatsapp/provider.py` — `WhatsAppProvider` abstract base class

```python
class WhatsAppProvider(ABC):
    @property
    def provider_name(self) -> str: ...

    @property
    def supported_message_types(self) -> set[str]: ...

    async def initialize(self, config: WhatsAppProviderConfig) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def get_connection_state(self) -> WhatsAppConnectionState: ...
    async def connection_events(self) -> AsyncGenerator[WhatsAppConnectionEvent, None]: ...
    async def get_our_identity(self) -> Optional[WhatsAppContactIdentity]: ...
    async def send_message(self, message: OutgoingWhatsAppMessage) -> str: ...
    async def incoming_messages(self) -> AsyncGenerator[IncomingWhatsAppMessage, None]: ...
    async def delivery_receipts(self) -> AsyncGenerator[WhatsAppMessageDeliveryReceipt, None]: ...
    async def request_qr_code(self) -> Optional[str]: ...
    async def request_pairing_code(self, phone_number: str) -> Optional[str]: ...
    async def logout(self) -> None: ...
    async def is_connected(self) -> bool: ...
```

**Registry**: `provider_registry` — Global registry for provider implementations

### Normalized Event Models

Defined in `app/whatsapp/models.py`:

| Model | Purpose |
|-------|---------|
| `IncomingWhatsAppMessage` | Normalized inbound message with idempotency key |
| `OutgoingWhatsAppMessage` | Normalized outbound message |
| `WhatsAppConnectionEvent` | Connection state change events |
| `WhatsAppContactIdentity` | Provider-neutral contact identity |
| `WhatsAppMessageAttachment` | Normalized media attachments |
| `WhatsAppMessageDeliveryReceipt` | Delivery status updates |
| `WhatsAppConnectionState` | Normalized connection states |

### Idempotency Strategy

Each inbound message generates an idempotency key:
```
whatsapp:<provider>:<provider_message_id>
```

Duplicate detection via database table with unique constraint on `idempotency_key`.

### Authentication Integration

Flow:
```
IncomingWhatsAppMessage
       ↓
WhatsAppIncomingIdentity (provider, provider_user_id, normalized_identifier)
       ↓
WhatsAppIdentityResolver → DatabaseStudentResolver
       ↓
AuthenticatedIdentity (student_id, provider, authentication_method)
       ↓
AuthorizationService.authorize_resource(student_id, resource_owner_id)
```

### Connection Lifecycle

Normalized states (provider-agnostic):

| State | Description |
|-------|-------------|
| `DISCONNECTED` | Not connected, no session |
| `CONNECTING` | Attempting connection |
| `QR_REQUIRED` | Waiting for QR scan |
| `PAIRING_CODE` | Waiting for pairing code |
| `CONNECTED` | Authenticated, ready |
| `RECONNECTING` | Lost connection, retrying |
| `FAILED` | Permanent error |
| `LOGGED_OUT` | Session invalidated |

### Personal Alpha: Baileys

**Selected for personal alpha** — See `docs/ADR/004-whatsapp-provider.md`

- Self-hosted Node.js process
- WebSocket-based (no browser)
- PostgreSQL session storage
- QR code or pairing code auth
- Full feature set

### Future: Meta Cloud API

Target for production scale:
- Official REST API + Webhooks
- No infrastructure management
- Business verification required
- Per-message pricing

### Security Constraints

- Core never receives raw provider objects
- Provider-specific data stays in adapter
- Idempotency keys never contain message content
- Provider-specific data never logged
- Webhook signature validation (Cloud API)

---

## LLM

- **Status:** Not implemented. Abstraction layer planned.
- **Direction:** LLM handles NL understanding, intent/entity extraction, typed tool selection.
- **Constraint:** LLM is NOT a security boundary. All tool calls require backend authorization.
- **Future:** Support multiple providers behind the same interface.

## College Portal

- **Target:** https://automation.vnrvjiet.ac.in/
- **Status:** Not implemented. Investigation pending.
- **Constraint:** Read-only integration. Never bypass CAPTCHA/MFA/access controls. Never modify portal data. Never use real credentials.
- **Future:** Read-only scraping for attendance and profile data.

## OCR/Vision

- **Status:** Not implemented.
- **Purpose:** Timetable image extraction.
- **Constraint:** OCR output is untrusted. Validate extracted data before use.