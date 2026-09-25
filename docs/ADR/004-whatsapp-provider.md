# WhatsApp Provider Assessment — Beru

## Executive Summary

This document compares three WhatsApp integration options for Beru's personal alpha:
- **Baileys** (WebSocket-based TypeScript library)
- **whatsapp-web.js** (Puppeteer-based Node.js library)
- **Meta WhatsApp Cloud API** (Official REST API)

**Recommendation for Personal Alpha: Baileys** — Best balance of self-hosted control, feature completeness, and migration path.

---

## 1. Baileys Assessment

### Overview
- **Type**: WebSocket-based TypeScript library
- **Protocol**: Direct WhatsApp Web binary protocol (Noise/protobuf)
- **Architecture**: Lightweight Node.js process, no browser required
- **Repository**: `github.com/whiskeysockets/baileys`
- **License**: MIT

### Architecture & Authentication
```
Connection Flow:
1. makeWASocket() → WebSocket to wss://web.whatsapp.com/ws/chat
2. Auth via QR code (terminal) OR Pairing Code (phone number)
3. Session state: creds.json + Signal keys (per-user folder)
4. Event-driven: connection.update, messages.upsert, creds.update
```

### Key Features
| Feature | Support |
|---------|---------|
| Text messages | ✅ |
| Media (images, audio, video, documents) | ✅ |
| Stickers, contacts, location | ✅ |
| Groups (create, manage, participants) | ✅ |
| Reactions, replies, polls | ✅ |
| Presence (typing, online) | ✅ |
| QR + Pairing Code auth | ✅ |
| Session persistence | ✅ (file-based or custom DB) |
| Multi-device | ✅ |
| Interactive messages (lists/buttons) | ✅ |

### Session & Persistence
- **Auth state**: `AuthenticationCreds` + `SignalKeyStore`
- **Default**: `useMultiFileAuthState()` → folder with `creds.json` + key files
- **Production**: Custom `AuthenticationState` with database backend
- **Critical**: Must save on `creds.update` event (fires on every message)
- **Key serialization**: Requires `BufferJSON` for Buffer/Uint8Array

### Connection Lifecycle
```
States: DISCONNECTED → CONNECTING → QR_REQUIRED → CONNECTED → RECONNECTING → FAILED/LOGGED_OUT
Events: connection.update (close, open, qr)
Reconnection: Automatic on non-logged-out disconnects
```

### Operational Complexity
| Factor | Assessment |
|--------|------------|
| Infrastructure | Node.js process only (no browser) |
| Memory | ~50-100MB (lightweight) |
| Dependencies | Node.js, @whiskeysockets/baileys |
| Session storage | File-based or DB (PostgreSQL ready) |
| QR pairing | Terminal or programmatic |
| Reconnection | Built-in with backoff |
| Rate limits | Self-managed (WhatsApp-side) |

### Maintenance Risk
| Risk | Level | Mitigation |
|------|-------|------------|
| WhatsApp protocol changes | Medium | Active maintenance, community forks |
| Breaking changes (v7+) | Medium | Migration guide available |
| Key management complexity | High | Use `makeCacheableSignalKeyStore` |
| Session corruption | Medium | Backup `creds.json` + keys folder |

### Personal Alpha Suitability
✅ **Excellent** — Self-hosted, no browser, full feature set, PostgreSQL-compatible session storage

### Migration Path
- Provider abstraction allows swap to Cloud API later
- Session export possible (creds + keys)

---

## 2. whatsapp-web.js Assessment

### Overview
- **Type**: Puppeteer-based Node.js library
- **Architecture**: Managed Chrome/Chromium browser instance
- **Repository**: `github.com/pedroslopez/whatsapp-web.js`
- **License**: MIT

### Architecture & Authentication
```
Connection Flow:
1. Client.initialize() → Puppeteer launches Chrome
2. Navigate to web.whatsapp.com
3. Inject JavaScript to hook internal WhatsApp Web functions
3. Auth via QR code (terminal) OR Pairing Code
4. Session: LocalAuth (file) or RemoteAuth (custom store)
5. Event-driven: qr, authenticated, ready, message, etc.
```

### Key Features
| Feature | Support |
|---------|---------|
| Text messages | ✅ |
| Media (images, audio, video, documents) | ✅ |
| Stickers, contacts, location | ✅ |
| Groups | ✅ |
| Reactions, replies, polls | ✅ |
| Presence | ✅ |
| QR + Pairing Code auth | ✅ |
| Session persistence | ✅ (LocalAuth/RemoteAuth) |
| Multi-device | ✅ |
| Interactive messages | ⚠️ (DEPRECATED - buttons/lists) |

### Session & Persistence
- **AuthStrategy**: `NoAuth`, `LocalAuth` (file), `RemoteAuth` (custom store)
- **LocalAuth**: Saves session to `dataPath/clientId` folder
- **RemoteAuth**: Custom `Store` interface (sessionExists, save, extract, delete)
- **Session data**: `WABrowserId`, `WASecretBundle`, `WAToken1`, `WAToken2`

### Connection Lifecycle
```
States: INITIALIZING → QR_RECEIVED → LOADING_SCREEN → AUTHENTICATED → READY → DISCONNECTED
Events: qr, code, authenticated, ready, disconnected, loading_screen
Reconnection: Auto on navigation/refresh (via re-injection)
```

### Operational Complexity
| Factor | Assessment |
|--------|------------|
| Infrastructure | Node.js + Chrome/Chromium (Puppeteer) |
| Memory | 300-500MB+ (browser process) |
| Dependencies | Node.js, puppeteer, whatsapp-web.js |
| Docker/Headless | Required for servers (--no-sandbox, etc.) |
| Session storage | File or custom Store interface |
| QR pairing | Terminal or programmatic |
| Reconnection | Re-injection on navigation/refresh |

### Maintenance Risk
| Risk | Level | Mitigation |
|------|-------|------------|
| WhatsApp Web UI changes | High | Puppeteer injection breaks on UI updates |
| Chrome version drift | Medium | Pin Puppeteer/Chrome versions |
| Webpack → non-Webpack migration | High | Recent PR #2816 "webpack-exodus" |
| Memory leaks | Medium | Restart policies, session cleanup |
| Resource heavy | High | Not suitable for low-resource environments |

### Personal Alpha Suitability
⚠️ **Adequate but heavy** — Requires Chrome, more fragile due to DOM injection, higher resource usage

### Migration Path
- Provider abstraction allows swap
- Session export: LocalAuth/RemoteAuth data

---

## 3. Meta WhatsApp Cloud API Assessment

### Overview
- **Type**: Official REST API + Webhooks
- **Architecture**: Cloud-hosted by Meta, HTTPS + Webhooks
- **Provider**: Meta (Facebook)
- **Cost**: Per-message pricing (free tier: 1,000 conversations/month)

### Architecture & Authentication
```
Flow:
1. Create Meta Developer App → WhatsApp Product
2. Create WABA (WhatsApp Business Account) → Test or Production
3. Phone number verification (business verification for production)
4. Access Token (System User + permanent token)
5. Webhook endpoint for inbound messages
6. Send via REST API, receive via Webhooks
```

### Key Features
| Feature | Support |
|---------|---------|
| Text messages | ✅ |
| Media (images, audio, video, documents) | ✅ |
| Templates (marketing, utility, auth) | ✅ (required for out-of-window) |
| Interactive (buttons, lists, flows) | ✅ |
| Groups | ✅ (limited) |
| Calling | ✅ |
| Webhooks | ✅ (messages, status, account updates) |

### Authentication & Authorization
- **OAuth** (not OAuth 2.0) — System User + Permanent Access Token
- **Permissions**: `whatsapp_business_messaging`, `whatsapp_business_management`
- **App Review** required for production (advanced access)
- **Webhook verification** — `hub.challenge` + signature validation

### Pricing (2024/2025)
| Category | Free? | Notes |
|----------|-------|-------|
| Service messages (in 24h window) | ✅ Free (since Nov 2024) | |
| Utility templates (in window) | ✅ Free (since Jul 2025) | |
| Marketing templates | ❌ Paid | Per-message, by country |
| Authentication templates | ❌ Paid | Per-message, by country |
| Free tier | 1,000 conversations/month | Per business phone number |

### Rate Limits
| Limit | Value |
|-------|-------|
| API requests | 200/hr (default), 5,000/hr (active WABA) |
| Business phone | 80 msg/sec default |
| Pair rate | 1 msg/6 sec per user |
| Burst | 45 msgs/6 sec (borrows future quota) |

### Connection Lifecycle
```
No persistent connection — stateless REST API
Webhooks: Meta → Your HTTPS endpoint
Status: sent → delivered → read (separate webhooks)
```

### Operational Complexity
| Factor | Assessment |
|--------|------------|
| Infrastructure | HTTPS server + webhook endpoint |
| Dependencies | Meta Developer Account, Facebook App |
| Verification | Business verification for production |
| App Review | Required for advanced permissions |
| Session | Stateless (no session management) |
| Webhook | HTTPS + mTLS recommended |
| IP allowlist | Meta IPs change periodically (mTLS preferred) |

### Maintenance Risk
| Risk | Level | Mitigation |
|------|-------|------------|
| Policy changes | High | Meta controls platform |
| Pricing changes | High | Quarterly updates |
| App review delays | Medium | Plan ahead |
| Template approval | Medium | Pre-create templates |
| Rate limits | Medium | Implement backoff |

### Personal Alpha Suitability
❌ **Poor** — Requires business verification, Meta account, app review, phone number registration, not self-hosted, per-message costs

### Migration Path
- **Future production target** — but not for personal alpha
- Full feature parity with WhatsApp Web

---

## 4. Comparison Matrix

| Criterion | Baileys | whatsapp-web.js | Meta Cloud API |
|-----------|---------|-----------------|----------------|
| **Self-hosted** | ✅ | ✅ | ❌ |
| **No browser** | ✅ | ❌ (Puppeteer) | ✅ |
| **Memory footprint** | Low (~50MB) | High (~500MB) | N/A (stateless) |
| **Protocol** | Native WebSocket | Browser injection | REST + Webhooks |
| **Multi-device** | ✅ | ✅ | ✅ |
| **QR + Pairing** | ✅ | ✅ | N/A (business setup) |
| **Session persistence** | File/DB | File/DB | Stateless |
| **Media support** | Full | Full | Full |
| **Groups** | Full | Full | Limited |
| **Interactive msgs** | ✅ | ⚠️ Deprecated | ✅ |
| **Production ready** | ✅ (with DB) | ⚠️ Fragile | ✅ |
| **Business verification** | ❌ Not needed | ❌ Not needed | ✅ Required (prod) |
| **Per-message cost** | $0 | $0 | Variable |
| **Rate limits** | Self-managed | Self-managed | Meta-enforced |
| **Provider lock-in** | Low | Low | High |
| **Migration path** | Easy (abstraction) | Easy | N/A (target) |

---

## 5. Recommendation

### Personal Alpha: **Baileys**

**Rationale:**
1. **Self-hosted** — Runs as Node.js process, no external dependencies
2. **Lightweight** — No browser, minimal memory
3. **Full protocol access** — WebSocket native, not browser-injected
4. **PostgreSQL session storage** — Native fit for our architecture
5. **Zero cost** — No per-message fees
6. **Migration path** — Abstraction layer enables future Cloud API swap
7. **Active maintenance** — WhiskeySockets org, regular updates

**Trade-offs accepted:**
- Not "official" Meta API (but uses same multi-device protocol)
- Signal key management complexity (mitigated by `useMultiFileAuthState` + DB)
- WhatsApp protocol change risk (mitigated by abstraction layer)

### Future Production: **Meta Cloud API**

When Beru scales beyond personal alpha:
- Official support, SLA
- No infrastructure management
- Business verification adds trust
- Per-message pricing acceptable at scale

---

## 6. What Was NOT Verified

| Item | Reason |
|------|--------|
| Actual QR scan & connection | No real WhatsApp account used |
| Real message send/receive | No test account connected |
| Session persistence across restarts | Not tested with real session |
| Reconnection behavior under network failure | Not tested |
| Media upload/download | Not tested |
| Group message handling | Not tested |
| Rate limit behavior | Not tested |
| Production Cloud API onboarding | Not attempted |

**All architecture decisions based on documentation review and community reports only.**