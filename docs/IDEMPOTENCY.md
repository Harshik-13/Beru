# WhatsApp Idempotency Strategy — Beru

## Problem

WhatsApp providers (especially Baileys) may deliver the same message multiple times due to:
- Network retries
- Webhook retries (Meta Cloud API)
- Bridge reconnection and history sync
- Client-side message resend

Beru must process each unique message **at most once**.

## Idempotency Key Design

### For Baileys (WebSocket)
```
Key format: "whatsapp:baileys:<message_key.remoteJid>:<message_key.id>:<message_key.fromMe>"
```

Baileys message key structure:
```typescript
interface WAMessageKey {
  remoteJid: string      // Chat JID (e.g., "919876543210@s.whatsapp.net")
  id: string             // WhatsApp message ID (e.g., "3EB0A123456789")
  fromMe: boolean        // True if sent by us
  participant?: string   // For group messages
}
```

### For Meta Cloud API (Webhook)
```
Key format: "whatsapp:meta:<webhook_entry_id>:<message.id>"
```

Cloud API message structure:
```json
{
  "id": "wamid.HBgLMTY0NjcwNDM1OTUVAgARGBI4MjZGRDA0OUE2OTQ3RkEyMzcA",
  "from": "919876543210",
  "timestamp": "1699900000",
  "type": "text"
}
```

## Implementation Strategy

### 1. Database Table: `whatsapp_message_idempotency`

```sql
CREATE TABLE whatsapp_message_idempotency (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key VARCHAR(500) NOT NULL UNIQUE,
    provider VARCHAR(50) NOT NULL,
    provider_message_id VARCHAR(255) NOT NULL,
    student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    message_type VARCHAR(20) NOT NULL,
    processed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX ix_whatsapp_idempotency_student_processed
    ON whatsapp_message_idempotency (student_id, processed_at DESC);
```

### 2. Repository Interface

```python
class WhatsAppIdempotencyRepository:
    async def check_and_mark(self, idempotency_key: str) -> bool:
        """
        Atomic check-and-mark operation.

        Returns:
            True if this is the first time seeing this key (process it)
            False if already processed (skip)
        """
        # Use INSERT ... ON CONFLICT DO NOTHING
        # Return True if inserted, False if conflict
        ...

    async def is_processed(self, idempotency_key: str) -> bool:
        """Check if key exists (for read-only checks)."""
        ...
```

### 3. Service Integration

```python
class WhatsAppMessageProcessor:
    def __init__(
        self,
        idempotency_repo: WhatsAppIdempotencyRepository,
        auth_resolver: WhatsAppIdentityResolver,
        message_service: "MessageService",
    ):
        self._idempotency = idempotency_repo
        self._auth = auth_resolver
        self._messages = message_service

    async def process_inbound(self, normalized: IncomingWhatsAppMessage) -> None:
        # 1. Generate idempotency key
        key = normalized.get_idempotency_key()

        # 2. Atomic check-and-mark
        if not await self._idempotency.check_and_mark(key):
            return  # Already processed, skip

        # 3. Resolve identity
        incoming_identity = create_whatsapp_incoming_identity(
            provider=normalized.provider,
            provider_user_id=normalized.from_contact.provider_user_id,
            normalized_identifier=normalized.from_contact.normalized_identifier,
        )
        auth_result = await self._auth.resolve(incoming_identity)

        if isinstance(auth_result, UnauthenticatedIdentity):
            # Log but don't process
            await self._audit.log_authentication_failure(...)
            return

        # 4. Process message (business logic)
        await self._messages.handle_inbound(
            student_id=auth_result.student_id,
            message=normalized,
        )
```

## Duplicate Detection Guarantees

| Scenario | Handled? | How |
|----------|----------|-----|
| Baileys history sync on reconnect | ✅ | Same message ID → same idempotency key |
| Meta webhook retries | ✅ | Same webhook message ID → same key |
| Bridge restart + history sync | ✅ | Message IDs stable across sessions |
| Client message resend | ✅ | WhatsApp assigns new ID (different key) |
| Group messages | ✅ | Includes participant in key for group messages |

## Outbound Idempotency

For outbound messages, the client (Beru core) generates an idempotency key:

```python
# In application service
async def send_message(
    self,
    student_id: UUID,
    to: WhatsAppContactIdentity,
    content: OutgoingWhatsAppMessage,
) -> str:
    idempotency_key = content.idempotency_key or generate_idempotency_key()

    # Check if already sent
    if await self._outbound_idempotency.check_and_mark(idempotency_key):
        # First time - actually send
        provider_msg_id = await self._provider.send_message(content)
        await self._outbound_idempotency.mark_sent(idempotency_key, provider_msg_id)
        return provider_msg_id
    else:
        # Already sent - return existing provider message ID
        return await self._outbound_idempotency.get_provider_message_id(idempotency_key)
```

## Cleanup Strategy

| Policy | Implementation |
|--------|----------------|
| TTL | Delete records older than 90 days (configurable) |
| Size limit | Keep max 10M rows per student (partition by student_id) |
| Cleanup job | Daily batch job via background worker |

## Security Considerations

- Idempotency keys **never contain message content**
- Keys include provider + message ID only
- Student isolation enforced via FK to students table
- No PII in idempotency table