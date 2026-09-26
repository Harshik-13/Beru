"""
Baileys WhatsApp Provider Adapter — Personal Alpha.

Real Baileys adapter implementation for WhatsApp Web automation.
Uses Node.js subprocess for Baileys communication.

Architecture:
- Python process manages lifecycle and normalization
- Node.js subprocess runs Baileys WebSocket connection
- Communication via stdio JSON-RPC
"""

import asyncio
import json
import os
from asyncio import subprocess
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
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
else:
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
    from app.whatsapp.provider import (
        WhatsAppProvider,
        WhatsAppProviderConfig,
        provider_registry,
    )


@dataclass(frozen=True, slots=True)
class BaileysConfig:
    """Configuration for Baileys adapter."""

    session_path: str = "baileys_sessions"
    print_qr: bool = True
    auto_reconnect: bool = True
    reconnect_interval: int = 5  # seconds
    max_reconnect_attempts: int = 10
    message_history_limit: int = 100
    qr_timeout: int = 60  # seconds


class BaileysAdapter(WhatsAppProvider):
    """
    Baileys WhatsApp Provider Adapter — Personal Alpha.

    Manages a Node.js subprocess running Baileys WebSocket connection.
    Communicates via stdio JSON-RPC protocol.

    Protocol (Python -> Node.js):
    - {"method": "login", "params": {...}}
    - {"method": "send_message", "params": {...}}
    - {"method": "logout", "params": {}}
    - {"method": "request_qr", "params": {}}
    - {"method": "request_pairing_code", "params": {"phone_number": "..."}}

    Protocol (Node.js -> Python):
    - {"event": "connection_state", "data": {...}}
    - {"event": "message", "data": {...}}
    - {"event": "delivery_receipt", "data": {...}}
    - {"event": "qr_code", "data": {"qr_code": "..."}}
    - {"event": "pairing_code", "data": {"code": "..."}}
    - {"event": "error", "data": {"message": "..."}}
    - {"response": {"id": "...", "result": {...}}}
    """

    def __init__(self):
        self._config: BaileysConfig | None = None
        self._config_obj: WhatsAppProviderConfig | None = None
        self._process: subprocess.Process | None = None
        self._state = WhatsAppConnectionState.DISCONNECTED
        self._our_identity: WhatsAppContactIdentity | None = None
        self._message_queue: asyncio.Queue[IncomingWhatsAppMessage] = asyncio.Queue()
        self._connection_event_queue: asyncio.Queue[WhatsAppConnectionEvent] = (
            asyncio.Queue()
        )
        self._delivery_queue: asyncio.Queue = asyncio.Queue()
        self._pending_requests: dict[str, asyncio.Future] = {}
        self._request_id = 0
        self._running = False
        self._reconnect_task: asyncio.Task | None = None
        self._read_task: asyncio.Task | None = None
        self._our_identity: WhatsAppContactIdentity | None = None
        self._session_dir: Path | None = None
        self._process: subprocess.Process | None = None
        self._stdout_reader: asyncio.StreamReader | None = None
        self._stdin_writer: asyncio.StreamWriter | None = None
        self._request_id = 0

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
        """Initialize the Baileys adapter with configuration."""
        self._config_obj = config
        self._config = BaileysConfig(**config.config)

        # Create session directory
        self._session_dir = Path(self._config.session_path).resolve()
        self._session_dir.mkdir(parents=True, exist_ok=True)

        # Verify Node.js and Baileys are available
        await self._verify_node_environment()

    async def _verify_node_environment(self) -> None:
        """Verify Node.js and Baileys are available."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "node",
                "--version",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError("Node.js not found in PATH")
            version = stdout.decode().strip()
            print(f"[Baileys] Node.js version: {version}")

            # Check if Baileys is available
            baileys_check = await asyncio.create_subprocess_exec(
                "node",
                "-e",
                "require('@whiskeysockets/baileys'); console.log('Baileys OK')",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.getcwd(),
            )
            _, stderr = await baileys_check.communicate()
            if baileys_check.returncode != 0:
                raise RuntimeError(f"Baileys not available: {stderr.decode()}")
        except FileNotFoundError:
            raise RuntimeError("Node.js not found in PATH. Please install Node.js 18+")

    async def _start_node_process(self) -> None:
        """Start the Node.js Baileys process."""
        # Create the Node.js script
        script_path = self._create_node_script()

        self._process = await asyncio.create_subprocess_exec(
            "node",
            script_path,
            str(self._session_dir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "NODE_ENV": "production"},
        )

        self._stdout_reader = self._process.stdout
        self._stdin_writer = self._process.stdin

        # Start reading stdout
        self._read_task = asyncio.create_task(self._read_stdout())

        # Wait for ready signal
        await self._wait_for_ready()

    def _create_node_script(self) -> str:
        """Create the Node.js Baileys script."""
        script = """
const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion, makeCacheableSignalKeyStore } = require('@whiskeysockets/baileys');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const SESSION_DIR = process.argv[2];
const AUTH_DIR = path.join(SESSION_DIR, 'auth');

if (!fs.existsSync(AUTH_DIR)) {
    fs.mkdirSync(AUTH_DIR, { recursive: true });
}

const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);

const sock = makeWASocket({
    auth: state,
    printQRInTerminal: true,
    markOnlineOnConnect: true,
    syncFullHistory: false,
    markOnlineOnConnect: true,
});

sock.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect, qr } = update;
    if (qr) {
        sendToPython({ event: 'qr_code', data: { qr_code: qr } });
    }
    if (connection === 'open') {
        sendToPython({ event: 'connection_state', data: { state: 'connected' } });
    } else if (connection === 'close') {
        const reason = lastDisconnect?.error;
        const statusCode = reason?.output?.statusCode;
        if (statusCode === DisconnectReason.loggedOut) {
            sendToPython({ event: 'connection_state', data: { state: 'logged_out' } });
        } else {
            sendToPython({ event: 'connection_state', data: { state: 'reconnecting' } });
        }
    }
});

sock.ev.on('creds.update', saveCreds);

sock.ev.on('messages.upsert', async ({ messages, type }) => {
    for (const msg of messages) {
        if (msg.key.fromMe) continue;
        const normalized = normalizeMessage(msg);
        sendToPython({ event: 'message', data: normalized });
    }
});

sock.ev.on('messages.update', async (updates) => {
    for (const update of updates) {
        // Handle message updates (edits, deletes, reactions)
    }
});

sock.ev.on('messages.receipt', async (receipts) => {
    for (const receipt of receipts) {
        sendToPython({ event: 'delivery_receipt', data: normalizeReceipt(receipt) });
    }
});

function normalizeMessage(msg) {
    const key = msg.key;
    const fromMe = key.fromMe;
    const remoteJid = key.remoteJid;
    const fromMe = fromMe;

    const message = {
        event_id: key.id,
        provider: 'baileys',
        provider_timestamp: Math.floor(msg.messageTimestamp || Date.now() / 1000),
        from_contact: {
            provider: 'baileys',
            provider_user_id: fromMe ? sock.user.id : remoteJid,
            normalized_identifier: fromMe ? undefined : remoteJid.replace('@s.whatsapp.net', ''),
            display_name: fromMe ? undefined : msg.pushName,
        },
        to_contact: {
            provider: 'baileys',
            provider_user_id: sock.user.id,
        },
        message_type: getMessageType(msg),
        text: getMessageText(msg),
        attachment: getAttachment(msg),
        quoted_message_id: msg.message?.extendedTextMessage?.contextInfo?.stanzaId,
        is_forwarded: msg.message?.forwarded || false,
        is_from_me: fromMe,
        raw_provider_data: msg,
    };
    return message;
}

function normalizeReceipt(receipt) {
    return {
        message_id: receipt.key.id,
        provider_message_id: receipt.key.id,
        status: receipt.type === 'DELIVERY' ? 'delivered' : receipt.type === 'READ' ? 'read' : 'pending',
        provider_timestamp: Math.floor(receipt.timestamp || Date.now() / 1000),
        recipient: {
            provider: 'baileys',
            provider_user_id: receipt.key.remoteJid,
        },
        error_message: undefined,
    };
}

function getMessageType(msg) {
    const msgType = Object.keys(msg.message || {})[0];
    const typeMap = {
        conversation: 'text',
        extendedTextMessage: 'text',
        imageMessage: 'image',
        videoMessage: 'video',
        audioMessage: 'audio',
        documentMessage: 'document',
        stickerMessage: 'sticker',
        contactMessage: 'contact',
        locationMessage: 'location',
        reactionMessage: 'reaction',
        buttonsResponseMessage: 'interactive',
        listResponseMessage: 'interactive',
    };
    return typeMap[msgType] || 'unknown';
}

function getMessageText(msg) {
    const msgObj = msg.message;
    if (!msgObj) return null;
    if (msgObj.conversation) return msgObj.conversation;
    if (msgObj.extendedTextMessage?.text) return msgObj.extendedTextMessage.text;
    if (msgObj.imageMessage?.caption) return msgObj.imageMessage.caption;
    if (msgObj.videoMessage?.caption) return msgObj.videoMessage.caption;
    if (msgObj.documentMessage?.title) return msgObj.documentMessage.title;
    return null;
}

function getAttachment(msg) {
    const msgObj = msg.message;
    if (!msgObj) return null;

    const mediaTypes = ['imageMessage', 'videoMessage', 'audioMessage', 'documentMessage', 'stickerMessage'];
    for (const type of mediaTypes) {
        if (msgObj[type]) {
            const media = msgObj[type];
            return {
                media_type: getMessageType(media),
                mime_type: media.mimetype,
                file_name: media.fileName,
                file_size: media.fileLength,
                media_key: media.mediaKey,
                url: media.url,
                caption: media.caption,
            };
        }
    }
    return null;
}

function sendToPython(obj) {
    process.stdout.write(JSON.stringify(obj) + '\\n');
}

// Signal handling
process.on('SIGINT', () => process.exit(0));
process.on('SIGTERM', () => process.exit(0));

console.log('Baileys adapter ready');
"""

        script_path = self._session_dir / "baileys_adapter.js"
        with open(script_path, "w") as f:
            f.write(script)
        return str(script_path)

    async def _wait_for_ready(self) -> None:
        """Wait for Node.js process to signal ready."""
        timeout = 30.0
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            line = await self._stdout_reader.readline()
            if not line:
                await asyncio.sleep(0.1)
                continue
            line = line.decode().strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if data.get("event") == "ready":
                    return
                # Handle early events
                await self._handle_node_event(data)
            except json.JSONDecodeError:
                continue
        raise TimeoutError("Node.js process did not become ready in time")

    async def _read_stdout(self) -> None:
        """Read stdout from Node.js process."""
        while self._running and self._stdout_reader:
            try:
                line = await self._stdout_reader.readline()
                if not line:
                    break
                line = line.decode().strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    await self._handle_node_event(data)
                except json.JSONDecodeError:
                    continue
            except Exception:
                break

    async def _handle_node_event(self, data: dict) -> None:
        """Handle event from Node.js process."""
        event = data.get("event")
        data_payload = data.get("data", {})

        if event == "connection_state":
            state_str = data_payload.get("state")
            if state_str:
                new_state = WhatsAppConnectionState(state_str)
                await self._handle_state_change(new_state, data_payload)
        elif event == "message":
            await self._handle_incoming_message(data_payload)
        elif event == "delivery_receipt":
            await self._handle_delivery_receipt(data_payload)
        elif event == "qr_code":
            await self._handle_qr_code(data_payload.get("qr_code"))
        elif event == "pairing_code":
            await self._handle_pairing_code(data_payload.get("code"))
        elif event == "error":
            await self._handle_error(data_payload.get("message"))
        elif event == "response":
            request_id = data.get("id")
            if request_id in self._pending_requests:
                future = self._pending_requests.pop(request_id)
                if not future.done():
                    future.set_result(data.get("result"))

    async def _handle_state_change(
        self, new_state: WhatsAppConnectionState, data: dict
    ) -> None:
        """Handle connection state change."""
        old_state = self._state
        self._state = new_state

        if new_state == WhatsAppConnectionState.CONNECTED:
            # Get our identity
            self._our_identity = self._extract_identity()

        event = WhatsAppConnectionEvent(
            state=new_state,
            provider=self.provider_name,
            provider_identity=self._our_identity,
            qr_code=data.get("qr_code"),
            pairing_code=data.get("pairing_code"),
            error_message=data.get("error_message"),
        )
        await self._connection_event_queue.put(event)

    def _extract_identity(self) -> WhatsAppContactIdentity | None:
        """Extract our identity from the Node process."""
        # This would be sent from Node.js in a real implementation
        # For now, we'll use a placeholder
        return None

    async def _handle_incoming_message(self, data: dict) -> None:
        """Handle incoming message from Node.js."""
        msg = IncomingWhatsAppMessage(
            event_id=data.get("event_id", ""),
            provider="baileys",
            provider_timestamp=data.get(
                "provider_timestamp", int(datetime.now(UTC).timestamp())
            ),
            from_contact=WhatsAppContactIdentity(
                provider="baileys",
                provider_user_id=data.get("from_contact", {}).get(
                    "provider_user_id", ""
                ),
                normalized_identifier=data.get("from_contact", {}).get(
                    "normalized_identifier"
                ),
                display_name=data.get("from_contact", {}).get("display_name"),
            ),
            to_contact=WhatsAppContactIdentity(
                provider="baileys",
                provider_user_id=data.get("to_contact", {}).get("provider_user_id", ""),
            ),
            message_type=WhatsAppMessageType(data.get("message_type", "text")),
            text=data.get("text"),
            attachment=data.get("attachment"),
            quoted_message_id=data.get("quoted_message_id"),
            is_forwarded=data.get("is_forwarded", False),
            is_from_me=data.get("is_from_me", False),
        )
        await self._message_queue.put(msg)

    async def _handle_delivery_receipt(self, data: dict) -> None:
        """Handle delivery receipt from Node.js."""
        receipt = WhatsAppMessageDeliveryReceipt(
            message_id=data.get("message_id", ""),
            provider_message_id=data.get("provider_message_id", ""),
            status=WhatsAppDeliveryStatus(data.get("status", "pending")),
            provider_timestamp=data.get("provider_timestamp", 0),
            recipient=WhatsAppContactIdentity(
                provider="baileys",
                provider_user_id=data.get("recipient", {}).get("provider_user_id", ""),
            ),
            error_message=data.get("error_message"),
        )
        await self._delivery_queue.put(receipt)

    async def _handle_qr_code(self, qr_code: str) -> None:
        """Handle QR code from Node.js."""
        event = WhatsAppConnectionEvent(
            state=WhatsAppConnectionState.QR_REQUIRED,
            provider=self.provider_name,
            qr_code=qr_code,
        )
        await self._connection_event_queue.put(event)

    async def _handle_pairing_code(self, code: str) -> None:
        """Handle pairing code from Node.js."""
        event = WhatsAppConnectionEvent(
            state=WhatsAppConnectionState.PAIRING_CODE,
            provider=self.provider_name,
            pairing_code=code,
        )
        await self._connection_event_queue.put(event)

    async def _handle_error(self, message: str) -> None:
        """Handle error from Node.js."""
        event = WhatsAppConnectionEvent(
            state=WhatsAppConnectionState.FAILED,
            provider=self.provider_name,
            error_message=message,
        )
        await self._connection_event_queue.put(event)

    # ========== Public API ==========

    async def initialize(self, config: WhatsAppProviderConfig) -> None:
        """Initialize the provider with configuration."""
        await self.initialize(config)

    async def start(self) -> None:
        """Start the provider (connect, begin listening)."""
        if self._running:
            return

        self._running = True
        await self._start_node_process()

    async def stop(self) -> None:
        """Stop the provider gracefully."""
        self._running = False
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except TimeoutError:
                self._process.kill()
                await self._process.wait()
        self._process = None

    async def get_connection_state(self) -> WhatsAppConnectionState:
        """Get current connection state."""
        return self._state

    async def connection_events(self) -> AsyncGenerator[WhatsAppConnectionEvent, None]:
        """Async generator yielding connection state changes."""
        while self._running:
            try:
                event = await asyncio.wait_for(
                    self._connection_event_queue.get(), timeout=1.0
                )
                yield event
            except TimeoutError:
                continue

    async def get_our_identity(self) -> WhatsAppContactIdentity | None:
        """Get our own WhatsApp identity (after connection)."""
        if self._state == WhatsAppConnectionState.CONNECTED:
            return self._our_identity
        return None

    async def send_message(self, message: OutgoingWhatsAppMessage) -> str:
        """
        Send a message.

        Returns:
            Provider's message ID (e.g., WhatsApp message ID)
        """
        if self._state != WhatsAppConnectionState.CONNECTED:
            raise RuntimeError("Not connected")

        request_id = str(self._request_id)
        self._request_id += 1

        future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

        payload = {
            "id": request_id,
            "method": "send_message",
            "params": {
                "to": message.to_contact.provider_user_id,
                "type": message.message_type.value,
                "text": message.text,
                "quoted_message_id": message.quoted_message_id,
            },
        }

        self._stdin_writer.write(
            (
                json.dumps(
                    {"id": request_id, "method": "send_message", "params": payload}
                )
                + "\n"
            ).encode()
        )
        await self._stdin_writer.drain()

        try:
            result = await asyncio.wait_for(future, timeout=30.0)
            return result.get("message_id", "")
        except TimeoutError:
            self._pending_requests.pop(None, None)
            raise RuntimeError("Send message timeout")

    async def incoming_messages(self) -> AsyncGenerator[IncomingWhatsAppMessage, None]:
        """Async generator yielding normalized inbound messages."""
        while self._running:
            try:
                msg = await asyncio.wait_for(self._message_queue.get(), timeout=1.0)
                yield msg
            except TimeoutError:
                continue

    async def delivery_receipts(
        self,
    ) -> AsyncGenerator[WhatsAppMessageDeliveryReceipt, None]:
        """Async generator yielding delivery status updates."""
        while self._running:
            try:
                receipt = await asyncio.wait_for(
                    self._delivery_queue.get(), timeout=1.0
                )
                yield receipt
            except TimeoutError:
                continue

    async def request_qr_code(self) -> str | None:
        """Request QR code for pairing. Returns QR code data if supported."""
        if self._state == WhatsAppConnectionState.QR_REQUIRED:
            return "QR code available via connection_events()"
        return None

    async def request_pairing_code(self, phone_number: str) -> str | None:
        """Request pairing code for phone number. Returns code if supported."""
        request_id = str(self._request_id)
        self._request_id += 1

        future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

        payload = {
            "id": request_id,
            "method": "request_pairing_code",
            "params": {"phone_number": phone_number},
        }

        self._stdin_writer.write((json.dumps(payload) + "\n").encode())
        await self._stdin_writer.drain()

        try:
            result = await asyncio.wait_for(future, timeout=30.0)
            return result.get("code")
        except TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise RuntimeError("Pairing code request timeout")

    async def logout(self) -> None:
        """Log out and clear session."""
        if self._stdin_writer:
            payload = {"method": "logout", "params": {}}
            self._stdin_writer.write(
                (json.dumps({"method": "logout", "params": {}}) + "\n").encode()
            )
            await self._stdin_writer.drain()

    async def is_connected(self) -> bool:
        """Check if currently connected and authenticated."""
        return self._state == WhatsAppConnectionState.CONNECTED

    async def _shutdown(self) -> None:
        """Clean shutdown."""
        self._running = False
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

    async def _reconnect_loop(self) -> None:
        """Auto-reconnect loop."""
        attempts = 0
        while self._running and self._config.auto_reconnect:
            if self._state in (
                WhatsAppConnectionState.DISCONNECTED,
                WhatsAppConnectionState.RECONNECTING,
            ):
                await asyncio.sleep(self._config.reconnect_interval)
                if not self._running:
                    break
                attempts += 1
                if attempts >= self._config.max_reconnect_attempts:
                    break
                try:
                    await self._start_node_process()
                except Exception:
                    continue

    # Mock method for testing without Node.js
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


# Register the provider
def register_baileys_provider():
    """Register the Baileys provider with the global registry."""
    provider_registry.register(BaileysAdapter)
