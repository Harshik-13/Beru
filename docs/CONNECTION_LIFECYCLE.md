# WhatsApp Connection Lifecycle — Beru

## Overview

The WhatsApp connection lifecycle is normalized across all providers through the `WhatsAppConnectionState` enum and `WhatsAppConnectionEvent` model.

## Connection States

```python
class WhatsAppConnectionState(str, Enum):
    DISCONNECTED = "disconnected"      # Not connected, no session
    CONNECTING = "connecting"          # Attempting connection
    QR_REQUIRED = "qr_required"        # Waiting for QR scan
    PAIRING_CODE = "pairing_code"      # Waiting for pairing code entry
    CONNECTED = "connected"            # Authenticated, ready
    RECONNECTING = "reconnecting"      # Lost connection, retrying
    FAILED = "failed"                  # Permanent error
    LOGGED_OUT = "logged_out"          # Session invalidated by WhatsApp
```

## Normalized State Transitions

```
                    ┌─────────────────┐
                    │   DISCONNECTED  │
                    └────────┬────────┘
                             │ start()
                             ▼
                    ┌─────────────────┐
                    │   CONNECTING    │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
       ┌─────────────┐ ┌──────────────┐ ┌─────────┐
       │ QR_REQUIRED │ │ PAIRING_CODE │ │ FAILED  │
       └──────┬──────┘ └──────┬───────┘ └────┬────┘
              │               │               │
         QR scanned      Code entered       │
              │               │               │
              ▼               ▼               │
       ┌─────────────────────────────┐       │
       │         CONNECTED           │◄──────┘
       └──────────────┬──────────────┘
                      │
         ┌────────────┼────────────┐
         ▼            ▼            ▼
   ┌──────────┐ ┌───────────┐ ┌──────────┐
   │RECONNECT-│ │ LOGGED_OUT│ │  FAILED  │
   │  ING     │ │           │ │          │
   └────┬─────┘ └─────┬─────┘ └────┬─────┘
        │             │            │
   Reconnect OK    start()      restart()
        │             │            │
        └─────────────┴────────────┘
                      ▼
                 ┌─────────────┐
                 │  CONNECTED  │
                 └─────────────┘
```

## Provider-Specific Mapping

### Baileys (WebSocket)

| Baileys State | Normalized State |
|---------------|------------------|
| `connection === 'close'` (not logged out) | RECONNECTING |
| `connection === 'close'` (logged out) | LOGGED_OUT |
| `connection === 'open'` | CONNECTED |
| `connection === 'connecting'` | CONNECTING |
| `qr` present in update | QR_REQUIRED |
| `connection === 'close'` (other error) | FAILED |
| Initial (no session) | DISCONNECTED → CONNECTING |

### whatsapp-web.js (Puppeteer)

| whatsapp-web.js Event | Normalized State |
|----------------------|------------------|
| `qr` event | QR_REQUIRED |
| `code` event | PAIRING_CODE |
| `loading_screen` | CONNECTING |
| `authenticated` | CONNECTED (transitional) |
| `ready` | CONNECTED |
| `disconnected` (LOGOUT) | LOGGED_OUT |
| `disconnected` (NAVIGATION/other) | RECONNECTING |
| `auth_failure` | FAILED |

### Meta Cloud API

| Cloud API State | Normalized State |
|-----------------|------------------|
| Webhook verified, no session | DISCONNECTED |
| App configured, webhook active | CONNECTED |
| Webhook verification failed | FAILED |
| Phone number deactivated | LOGGED_OUT |
| Rate limit exceeded | FAILED (temporary) |

## Connection Event Model

```python
@dataclass
class WhatsAppConnectionEvent:
    state: WhatsAppConnectionState
    provider: str
    provider_identity: Optional[WhatsAppContactIdentity] = None
    qr_code: Optional[str] = None
    pairing_code: Optional[str] = None
    error_message: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
```

## Personal Alpha Operation

### Local Bridge Setup

```
┌─────────────────────────────────────────────────────────┐
│  Developer Machine                                       │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────┐  │
│  │  Beru API    │◄───│  Baileys     │◄───│  WhatsApp│  │
│  │  (FastAPI)   │    │  Bridge      │    │  Mobile  │  │
│  │  Port 8000   │    │  Node.js     │    │  (QR)    │  │
│  └──────────────┘    └──────────────┘    └──────────┘  │
│         │                    │                          │
│         │ SQLite/PostgreSQL  │                          │
│         │ Session Store      │                          │
│         └────────────────────┘                          │
└─────────────────────────────────────────────────────────┘
```

### Session Persistence

**Baileys Session Data:**
```
auth_info_baileys/
├── creds.json                    # Authentication credentials
├── app-state-sync-key-*.json     # Signal protocol keys
└── (other key files)
```

**Beru Database Storage:**
- `students` table — user account
- `whatsapp_identities` table — link between Student and WhatsApp identity
- Session keys stored in database (not filesystem) for production

### Reconnection Behavior

| Scenario | Behavior |
|----------|----------|
| Network blip (< 30s) | Baileys auto-reconnects, no event |
| Network down (> 30s) | RECONNECTING → CONNECTED (auto) |
| WhatsApp logs out session | LOGGED_OUT → requires manual QR |
| Bridge process crash | On restart: DISCONNECTED → CONNECTING → CONNECTED (auto) |
| WhatsApp Web protocol change | FAILED → manual intervention |

### Session Expiry

| Event | Result |
|-------|--------|
| WhatsApp forces re-auth (rare) | LOGGED_OUT → QR_REQUIRED |
| Session data corrupted | FAILED → manual cleanup + QR |
| Device unlinked from WhatsApp | LOGGED_OUT → QR_REQUIRED |
| 30+ days inactive | May require re-auth (WhatsApp policy) |

### Crash Recovery

1. **Bridge process dies**: Systemd/Docker restarts it → loads session from DB → CONNECTED
2. **Database unavailable**: Bridge fails to start → FAILED → alert
3. **Session keys out of sync**: Message send fails → Baileys triggers key update → auto-recover
4. **QR code expired**: New QR generated automatically on reconnection attempt

## Data That MUST Be Persisted

| Data | Where | Why |
|------|-------|-----|
| `AuthenticationCreds` | Database (encrypted) | Re-authenticate without QR |
| Signal protocol keys | Database | Message encryption/decryption |
| `WhatsAppIdentity` link | Database | Student ↔ WhatsApp mapping |
| Idempotency keys | Database | Duplicate detection |

## Data That MUST NEVER Be Persisted

| Data | Reason |
|------|--------|
| Raw QR code images | Security risk |
| Access tokens (Cloud API) | Use system user tokens only |
| Raw message content in logs | Privacy |
| Session cookies (whatsapp-web.js) | Security |
| Phone numbers in plain text logs | PII protection |

## Health Check Endpoint

```python
@router.get("/whatsapp/health")
async def whatsapp_health() -> dict:
    state = await provider.get_connection_state()
    return {
        "provider": "baileys",
        "state": state.value,
        "connected": state == WhatsAppConnectionState.CONNECTED,
        "uptime_seconds": provider.get_uptime(),
    }
```

## Monitoring Alerts

| Alert | Condition | Severity |
|-------|-----------|----------|
| WhatsApp disconnected | state != CONNECTED for > 5 min | Warning |
| Session logged out | state == LOGGED_OUT | Critical |
| Reconnection failed | state == RECONNECTING for > 10 min | Warning |
| Auth failure | state == FAILED | Critical |
| Message queue backing up | pending > 100 | Warning |