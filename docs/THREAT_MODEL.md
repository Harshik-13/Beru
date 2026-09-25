# Threat Model — Beru

## Trust Boundaries

1. **External → Backend:** All inbound data (WhatsApp, portal, OCR, LLM) is untrusted.
2. **LLM → Backend:** LLM output is treated as untrusted input. Backend validates and authorizes.
3. **Backend → Database:** Backend is the security boundary. Authorization enforced here.
4. **Client → Backend:** Never trust client-supplied owner IDs or roles.

## Key Threats

| Threat | Mitigation |
|---|---|
| LLM manipulation (prompt injection) | LLM only selects from allowlisted typed tools. Backend authorizes every call. |
| Unauthorized resource access | Every resource access requires authorization against authenticated owner_id. |
| Data leakage between users | Multi-user isolation via owner_id on all resources. |
| Credential exposure | Never commit or log secrets. Use environment variables. |
| Duplicate message processing | Idempotent inbound event processing. |
| Attendance tampering via simulation | Simulations never mutate actual attendance records. |
| Portal scraping abuse | Read-only integration. No credential storage. No bypass of access controls. |
| WhatsApp account compromise | Bridge is replaceable. Core does not depend on single provider. |
