# Integrations — Beru

All external integrations are behind abstraction interfaces. The core application depends on the interface, not the concrete provider.

## WhatsApp

- **Status:** Not implemented. Abstraction layer planned.
- **Direction:** WhatsApp-first student experience.
- **Constraint:** Provider/bridge must be replaceable. Do not hard-code core around one provider.
- **Personal Alpha:** Self-hosted WhatsApp Web bridge may be used.
- **Replacement Path:** Core communicates through interface; bridge can be swapped.

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
