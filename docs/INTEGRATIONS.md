# Integrations — Beru

All external integrations are behind abstraction interfaces. The core application depends on the interface, not the concrete provider.

## Telegram

### Status
- **Bot Adapter:** ✅ Implemented (`app/telegram/bot_adapter.py`)
- **Identity Linking:** ✅ Implemented (`app/telegram/linking_service.py`)
- **Message Handler:** ✅ Implemented (`app/telegram/message_handler.py`)
- **Provider Abstraction:** ✅ Implemented (`app/telegram/provider.py`)
- **Normalized Models:** ✅ Implemented (`app/telegram/models.py`)

### Architecture

```
Telegram Bot API
      ↓
TelegramBotAdapter (long polling)
      ↓
Normalized Messages (IncomingTelegramMessage, OutgoingTelegramMessage)
      ↓
TelegramMessageHandler
      ↓
Identity Resolution → Conversation Pipeline
```

### Provider Abstraction

**Interface**: `app/telegram/provider.py` — `TelegramProvider` abstract base class

```python
class TelegramProvider(ABC):
    @property
    def provider_name(self) -> str: ...
    @property
    def supported_message_types(self) -> set[str]: ...
    async def initialize(self, config: TelegramProviderConfig) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def get_connection_state(self) -> str: ...
    async def connection_events(self) -> AsyncGenerator[TelegramConnectionEvent, None]: ...
    async def get_our_identity(self) -> TelegramContactIdentity | None: ...
    async def send_message(self, message: OutgoingTelegramMessage) -> str: ...
    async def incoming_messages(self) -> AsyncGenerator[IncomingTelegramMessage, None]: ...
```

**Registry**: `telegram_provider_registry` — Global registry for provider implementations

### Identity Linking Flow

```
/start → Challenge creation → Student enters challenge → Verify → TelegramIdentity created
```

- Challenge: 10-minute TTL, single-use, 256-bit token
- Audit logging for all linking events
- Ownership enforced server-side

### Security Constraints

- Core never receives raw provider objects
- Provider-specific data stays in adapter
- No credentials in logs
- Bot token from environment only

---

## LLM

### Status
- **Provider Abstraction:** ✅ Implemented (`app/intelligence/providers/base.py`)
- **OpenAI-Compatible Provider:** ✅ Implemented (`app/intelligence/providers/openai_compatible.py`)
- **Mock Provider:** ✅ Implemented (`app/intelligence/providers/mock.py`)
- **Provider Registry:** ✅ Implemented
- **Real LLM Integration:** ✅ Wired in lifespan (`app/main.py`)

### Architecture

```
ConversationService
      ↓
LLMProvider (ABC)
      ↓
OpenAICompatibleLLMProvider / MockLLMProvider
```

### Provider Selection

Configured via environment:
- `LLM_PROVIDER` — Provider name (default: `mock`)
- `LLM_MODEL` — Model name
- `LLM_API_KEY` — API key
- `LLM_BASE_URL` — API base URL

`create_llm_provider()` factory in `app/intelligence/providers/__init__.py` creates and initializes the provider from settings.

### Security Constraints

- LLM is NOT a security boundary
- LLM can only request allowlisted, typed tools
- Backend authorizes every tool call
- LLM never performs attendance arithmetic
- Rate limiting per student

---

## College Portal (Doctus)

### Status
- **Adapter:** ✅ Implemented (`app/integrations/portal/doctus.py`)
- **Parser:** ✅ Implemented (`app/integrations/portal/parser.py`)
- **Sync Service:** ✅ Implemented (`app/integrations/portal/sync_service.py`)
- **Credential Store:** ✅ Implemented (`app/integrations/portal/credential_store.py`)
- **Live Verification:** NOT RUNTIME VERIFIED

### Architecture

```
DoctusAdapter
  ├── login(roll_number, password) → DoctusSession
  ├── get_semesters() → list[SemesterOption]
  └── get_attendance(semester_id) → PortalAttendance
```

### Known Contract

- `POST /Login` — Authenticate, receive session cookie `relic_VNRVJIET`
- `GET /Academic/Shared/GetStdAttPer` — Attendance data
- `studentId` is protected/session-derived
- `semesterId` is required

### Security Constraints

- Read-only integration
- No credential storage in plain text
- No bypass of access controls
- Session cookies never logged
- Timeout: 30 seconds
- No infinite retries

---

## OCR/Vision

### Status
- **Timetable Extraction:** ✅ Implemented (`app/intelligence/services/timetable_extraction.py`)
- **PDF Extraction:** ✅ Implemented (pdfplumber)

### Security Constraints

- OCR output is untrusted
- Extracted data validated before use
- No raw OCR output stored