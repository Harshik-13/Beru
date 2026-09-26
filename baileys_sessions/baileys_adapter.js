/**
 * Baileys WhatsApp Provider Adapter — Node.js Entrypoint
 *
 * This is the standalone Node.js process that runs Baileys and communicates
 * with the Python backend via stdio JSON-RPC.
 *
 * Communication Protocol (JSON lines over stdio):
 *
 * Python -> Node.js (stdin):
 *   {"id": "req-1", "method": "login", "params": {"roll_number": "...", "password": "..."}}
 *   {"id": "req-2", "method": "send_message", "params": {"to": "...", "text": "..."}}
 *   {"id": "req-3", "method": "get_semesters", "params": {}}
 *   {"id": "req-4", "method": "get_attendance", "params": {"semester_id": "..."}}
 *   {"id": "req-5", "method": "logout", "params": {}}
 *   {"id": "req-6", "method": "request_qr", "params": {}}
 *   {"id": "req-7", "method": "request_pairing_code", "params": {"phone_number": "..."}}
 *
 * Node.js -> Python (stdout, JSON lines):
 *   {"event": "ready"}
 *   {"event": "connection_state", "data": {"state": "connected"}}
 *   {"event": "qr_code", "data": {"qr_code": "..."}}
 *   {"event": "pairing_code", "data": {"code": "..."}}
 *   {"event": "message", "data": {...}}
 *   {"event": "delivery_receipt", "data": {...}}
 *   {"event": "error", "data": {"message": "..."}}
 *   {"response": {"id": "req-1", "result": {...}}}
 */

/**
 * Baileys WhatsApp Provider Adapter — Node.js Entrypoint
 *
 * This is the standalone Node.js process that runs Baileys and communicates
 * with the Python backend via stdio JSON-RPC.
 *
 * Communication Protocol (JSON lines over stdio):
 *
 * Python -> Node.js (stdin):
 *   {"id": "req-1", "method": "login", "params": {"roll_number": "...", "password": "..."}}
 *   {"id": "req-2", "method": "send_message", "params": {"to": "...", "text": "..."}}
 *   {"id": "req-3", "method": "get_semesters", "params": {}}
 *   {"id": "req-4", "method": "get_attendance", "params": {"semester_id": "..."}}
 *   {"id": "req-5", "method": "logout", "params": {}}
 *   {"id": "req-6", "method": "request_qr", "params": {}}
 *   {"id": "req-7", "method": "request_pairing_code", "params": {"phone_number": "..."}}
 *
 * Node.js -> Python (stdout, JSON lines):
 *   {"event": "ready"}
 *   {"event": "connection_state", "data": {"state": "connected"}}
 *   {"event": "qr_code", "data": {"qr_code": "..."}}
 *   {"event": "pairing_code", "data": {"code": "..."}}
 *   {"event": "message", "data": {...}}
 *   {"event": "delivery_receipt", "data": {...}}
 *   {"event": "error", "data": {"message": "..."}}
 *   {"response": {"id": "req-1", "result": {...}}}
 */

const fs = require('fs');
const path = require('path');
const qrcode = require('qrcode-terminal');

const {
    default: makeWASocket,
    useMultiFileAuthState,
    DisconnectReason,
} = require('@whiskeysockets/baileys');

async function main() {
    // Send ready signal
    function sendToPython(obj) {
        process.stdout.write(JSON.stringify(obj) + '\n');
    }

    sendToPython({ event: 'ready' });

    const SESSION_DIR = process.argv[2] || './baileys_sessions';
    const AUTH_DIR = path.join(SESSION_DIR, 'auth');

    if (!fs.existsSync(AUTH_DIR)) {
        fs.mkdirSync(AUTH_DIR, { recursive: true });
    }

    const { default: makeWASocket, useMultiFileAuthState, DisconnectReason } = require('@whiskeysockets/baileys');

    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);

    const sock = makeWASocket({
        auth: state,
        printQRInTerminal: true,
        markOnlineOnConnect: true,
        syncFullHistory: false,
        markOnlineOnConnect: true,
    });

    let isReady = false;

    sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect, qr } = update;
        if (qr) {
            // Render QR code in terminal for user to scan
            qrcode.generate(qr, { small: true }, (qrCode) => {
                console.log('\n=== Scan this QR code with WhatsApp ===');
                console.log(qrCode);
                console.log('========================================\n');
            });
            sendToPython({ event: 'qr_code', data: { qr_code: qr } });
        }
        if (connection === 'open') {
            sendToPython({ event: 'connection_state', data: { state: 'connected' } });
        } else if (connection === 'close') {
            const reason = lastDisconnect?.error;
            const statusCode = reason?.output?.statusCode;
            if (statusCode === 401) { // DisconnectReason.loggedOut
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
        const fromMe = msg.key.fromMe;
        const remoteJid = msg.key.remoteJid;

        const message = {
            event_id: msg.key.id,
            provider: 'baileys',
            provider_timestamp: Math.floor(msg.messageTimestamp || Date.now() / 1000),
            from_contact: {
                provider: 'baileys',
                provider_user_id: fromMe ? sock.user.id : msg.key.remoteJid,
                normalized_identifier: fromMe
                    ? undefined
                    : msg.key.remoteJid.replace('@s.whatsapp.net', ''),
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
        const status = receipt.type === 'DELIVERY'
            ? 'delivered'
            : receipt.type === 'READ'
                ? 'read'
                : 'pending';
        return {
            message_id: receipt.key.id,
            provider_message_id: receipt.key.id,
            status,
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

        const mediaTypes = [
            'imageMessage',
            'videoMessage',
            'audioMessage',
            'documentMessage',
            'stickerMessage',
        ];
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
        process.stdout.write(JSON.stringify(obj) + '\n');
    }

    // Signal handling
    process.on('SIGINT', () => process.exit(0));
    process.on('SIGTERM', () => process.exit(0));

    console.log('Baileys adapter ready');
}

main().catch((err) => {
    console.error('Fatal error:', err);
    process.exit(1);
});