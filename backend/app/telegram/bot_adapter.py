"""
Telegram Bot API Adapter — Personal Alpha.

Real Telegram adapter implementation using Bot API long polling.
Communicates directly with Telegram Bot API over HTTPS.
"""

import asyncio
import contextlib
import json
import logging
import secrets
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import aiohttp

if TYPE_CHECKING:
    from app.repositories.telegram_linking_challenge import (
        TelegramLinkingChallengeRepository,
    )
    from app.telegram.models import (
        IncomingTelegramMessage,
        OutgoingTelegramMessage,
        TelegramConnectionEvent,
        TelegramContactIdentity,
        TelegramInteractiveReply,
        TelegramMessageAttachment,
        TelegramMessageDeliveryReceipt,
        TelegramMessageType,
    )
    from app.telegram.provider import TelegramProvider, TelegramProviderConfig
else:
    from app.telegram.models import (
        IncomingTelegramMessage,
        OutgoingTelegramMessage,
        TelegramConnectionEvent,
        TelegramContactIdentity,
        TelegramInteractiveReply,
        TelegramMessageAttachment,
        TelegramMessageDeliveryReceipt,
        TelegramMessageType,
    )
    from app.telegram.provider import (
        TelegramProvider,
        TelegramProviderConfig,
        telegram_provider_registry,
    )

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TelegramBotConfig:
    """Configuration for Telegram Bot adapter."""

    bot_token: str
    poll_timeout: int = 30
    allowed_updates: list[str] | None = None
    drop_pending_updates: bool = True


class TelegramBotAdapter(TelegramProvider):
    """
    Telegram Bot API Adapter — Personal Alpha.

    Uses long polling to receive updates from Telegram Bot API.
    Normalizes Telegram updates into the existing application boundary.
    """

    def __init__(self):
        self._config: TelegramBotConfig | None = None
        self._config_obj: TelegramProviderConfig | None = None
        self._session: aiohttp.ClientSession | None = None
        self._state = "disconnected"
        self._our_identity: TelegramContactIdentity | None = None
        self._message_queue: asyncio.Queue[IncomingTelegramMessage] = asyncio.Queue()
        self._connection_event_queue: asyncio.Queue[TelegramConnectionEvent] = (
            asyncio.Queue()
        )
        self._delivery_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._poll_task: asyncio.Task | None = None
        self._last_update_id: int = 0
        self._processed_updates: set[int] = set()
        self._challenge_repo: TelegramLinkingChallengeRepository | None = None

    @property
    def provider_name(self) -> str:
        return "telegram_bot"

    @property
    def supported_message_types(self) -> set[str]:
        return {
            "text",
            "photo",
            "audio",
            "video",
            "document",
            "sticker",
            "contact",
            "location",
            "voice",
            "video_note",
            "animation",
            "poll",
        }

    async def initialize(self, config: TelegramProviderConfig) -> None:
        """Initialize the Telegram Bot adapter with configuration."""
        self._config_obj = config
        bot_config = TelegramBotConfig(
            bot_token=config.config["bot_token"],
            poll_timeout=config.config.get("poll_timeout", 30),
            allowed_updates=config.config.get("allowed_updates"),
            drop_pending_updates=config.config.get("drop_pending_updates", True),
        )
        self._config = bot_config

        # Create aiohttp session
        timeout = aiohttp.ClientTimeout(total=60)
        self._session = aiohttp.ClientSession(timeout=timeout)

        # Get bot info
        await self._get_me()

    def set_challenge_repository(
        self, repo: "TelegramLinkingChallengeRepository"
    ) -> None:
        """Set the challenge repository for handling /start linking flow."""
        self._challenge_repo = repo

    async def _get_me(self) -> None:
        """Get bot information from Telegram API.

        Raises:
            RuntimeError: If token is invalid, API is unreachable,
            or response is invalid.
        """
        if not self._session or not self._config:
            raise RuntimeError("Adapter not initialized: session or config missing")

        if not self._config.bot_token:
            raise RuntimeError("Telegram bot token is required")

        url = f"https://api.telegram.org/bot{self._config.bot_token}/getMe"

        try:
            async with self._session.get(url) as resp:
                data = await resp.json()
        except aiohttp.ClientError as e:
            raise RuntimeError(f"Telegram API unreachable: {e}") from e
        except TimeoutError as e:
            raise RuntimeError("Telegram API request timed out") from e

        if not data.get("ok"):
            error_code = data.get("error_code")
            description = data.get("description", "Unknown error")

            # Handle specific error codes
            if error_code == 401:
                raise RuntimeError("Invalid Telegram bot token (401 Unauthorized)")
            elif error_code == 404:
                raise RuntimeError("Telegram API endpoint not found")
            else:
                raise RuntimeError(f"Telegram API error ({error_code}): {description}")

        bot_info = data.get("result")
        if not bot_info:
            raise RuntimeError("Telegram API returned success but no bot info")

        self._our_identity = TelegramContactIdentity(
            provider=self.provider_name,
            provider_user_id=str(bot_info["id"]),
            normalized_identifier=f"@{bot_info.get('username', '')}"
            if bot_info.get("username")
            else None,
            display_name=bot_info.get("first_name"),
            is_bot=bot_info.get("is_bot", True),
        )

    async def start(self) -> None:
        """Start the provider (begin long polling)."""
        if self._running:
            logger.debug("Telegram adapter already running")
            return

        if not self._config or not self._session:
            raise RuntimeError("Adapter not initialized")

        logger.info("Starting Telegram long polling...")

        # Drop pending updates if configured
        if self._config.drop_pending_updates:
            await self._drop_pending_updates()

        self._running = True
        self._state = "polling"
        await self._emit_connection_event("polling")

        # Start polling task
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("Telegram long polling task started")

    async def _drop_pending_updates(self) -> None:
        """Drop pending updates on start."""
        if not self._session or not self._config:
            return
        url = f"https://api.telegram.org/bot{self._config.bot_token}/getUpdates"
        params = {"offset": -1}
        await self._session.post(url, json=params)

    async def stop(self) -> None:
        """Stop the provider gracefully."""
        logger.info("Stopping Telegram adapter...")
        self._running = False
        self._state = "disconnected"

        if self._poll_task:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task

        if self._session:
            await self._session.close()
            self._session = None

        await self._emit_connection_event("disconnected")
        logger.info("Telegram adapter stopped")

    async def _emit_connection_event(
        self, state: str, error: str | None = None
    ) -> None:
        """Emit a connection state change event."""
        event = TelegramConnectionEvent(
            state=state,
            provider=self.provider_name,
            provider_identity=self._our_identity,
            error_message=error,
        )
        await self._connection_event_queue.put(event)

    async def get_connection_state(self) -> str:
        """Get current connection state."""
        return self._state

    async def connection_events(self) -> AsyncGenerator[TelegramConnectionEvent, None]:
        """Async generator yielding connection state changes."""
        while self._running:
            try:
                event = await asyncio.wait_for(
                    self._connection_event_queue.get(), timeout=1.0
                )
                yield event
            except TimeoutError:
                continue

    async def get_our_identity(self) -> TelegramContactIdentity | None:
        """Get our own Telegram identity."""
        return self._our_identity

    async def send_message(self, message: OutgoingTelegramMessage) -> str:
        """
        Send a message via Telegram Bot API.

        Returns:
            Telegram message ID
        """
        if not self._session or not self._config:
            raise RuntimeError("Adapter not initialized")

        if message.message_type != "text":
            raise NotImplementedError(
                f"Message type {message.message_type} not yet supported"
            )

        url = f"https://api.telegram.org/bot{self._config.bot_token}/sendMessage"
        payload = {
            "chat_id": message.chat_id,
            "text": message.text,
        }
        if message.reply_to_message_id:
            payload["reply_to_message_id"] = int(message.reply_to_message_id)

        async with self._session.post(url, json=payload) as resp:
            data = await resp.json()
            if data.get("ok"):
                return str(data["result"]["message_id"])
            else:
                raise RuntimeError(f"Telegram API error: {data}")

    async def incoming_messages(self) -> AsyncGenerator[IncomingTelegramMessage, None]:
        """Async generator yielding normalized inbound messages."""
        while self._running:
            try:
                msg = await asyncio.wait_for(self._message_queue.get(), timeout=1.0)
                yield msg
            except TimeoutError:
                continue

    async def delivery_receipts(
        self,
    ) -> AsyncGenerator[TelegramMessageDeliveryReceipt, None]:
        """Async generator yielding delivery status updates."""
        while self._running:
            try:
                receipt = await asyncio.wait_for(
                    self._delivery_queue.get(), timeout=1.0
                )
                yield receipt
            except TimeoutError:
                continue

    async def _poll_loop(self) -> None:
        """Main long polling loop."""
        while self._running:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logging.error(f"Telegram poll error: {e}")
                await asyncio.sleep(5)

    async def _poll_once(self) -> None:
        """Perform a single long poll request."""
        if not self._session or not self._config:
            return

        url = f"https://api.telegram.org/bot{self._config.bot_token}/getUpdates"
        params = {
            "timeout": self._config.poll_timeout,
            "offset": self._last_update_id + 1,
        }
        if self._config.allowed_updates:
            params["allowed_updates"] = json.dumps(self._config.allowed_updates)

        try:
            async with self._session.get(url, params=params) as resp:
                data = await resp.json()
        except Exception as e:
            logging.error(f"Telegram API request failed: {e}")
            return

        if not data.get("ok"):
            logging.error(f"Telegram API error: {data}")
            return

        for update in data.get("result", []):
            await self._process_update(update)

    async def _process_update(self, update: dict) -> None:
        """Process a single Telegram update."""
        update_id = update.get("update_id", 0)

        # Idempotency check
        if update_id in self._processed_updates:
            return
        self._processed_updates.add(update_id)

        # Keep only last 10000 processed IDs to prevent memory growth
        if len(self._processed_updates) > 10000:
            # Remove oldest half
            sorted_ids = sorted(self._processed_updates)
            to_remove = sorted_ids[:5000]
            for id_ in to_remove:
                self._processed_updates.discard(id_)

        self._last_update_id = max(self._last_update_id, update_id)

        # Handle different update types
        if "message" in update:
            await self._handle_message(update["message"], update_id)
        elif "callback_query" in update:
            await self._handle_callback_query(update["callback_query"])
        # Other update types (edited_message, channel_post, etc.) ignored for now

    async def _handle_message(self, message: dict, update_id: int) -> None:
        """Handle an incoming message."""
        message_id = str(message.get("message_id", 0))
        chat = message.get("chat", {})
        chat_id = str(chat.get("id", 0))
        from_user = message.get("from", {})
        date_ts = message.get("date", int(datetime.now(UTC).timestamp()))

        from_contact = TelegramContactIdentity(
            provider=self.provider_name,
            provider_user_id=str(from_user.get("id", 0)),
            normalized_identifier=f"@{from_user.get('username')}"
            if from_user.get("username")
            else None,
            display_name=" ".join(
                filter(
                    None,
                    [
                        from_user.get("first_name"),
                        from_user.get("last_name"),
                    ],
                )
            )
            or None,
            is_bot=from_user.get("is_bot", False),
            is_premium=from_user.get("is_premium", False),
            language_code=from_user.get("language_code"),
        )

        to_contact = self._our_identity or TelegramContactIdentity(
            provider=self.provider_name,
            provider_user_id="",
        )

        reply_to = None
        if "reply_to_message" in message:
            reply_to = str(message["reply_to_message"].get("message_id", 0))

        # Determine message type and content
        message_type = "text"
        text = message.get("text")
        attachment = None

        if "photo" in message:
            message_type = "photo"
            photo = message["photo"][-1]  # Largest size
            attachment = TelegramMessageAttachment(
                media_type=TelegramMessageType.PHOTO,
                mime_type="image/jpeg",
                file_size=photo.get("file_size"),
                file_id=photo.get("file_id"),
                file_unique_id=photo.get("file_unique_id"),
                caption=message.get("caption"),
            )
            text = message.get("caption")
        elif "audio" in message:
            message_type = "audio"
            audio = message["audio"]
            attachment = TelegramMessageAttachment(
                media_type=TelegramMessageType.AUDIO,
                mime_type=audio.get("mime_type"),
                file_name=audio.get("file_name"),
                file_size=audio.get("file_size"),
                file_id=audio.get("file_id"),
                file_unique_id=audio.get("file_unique_id"),
                caption=message.get("caption"),
            )
        elif "video" in message:
            message_type = "video"
            video = message["video"]
            attachment = TelegramMessageAttachment(
                media_type=TelegramMessageType.VIDEO,
                mime_type=video.get("mime_type"),
                file_name=video.get("file_name"),
                file_size=video.get("file_size"),
                file_id=video.get("file_id"),
                file_unique_id=video.get("file_unique_id"),
                caption=message.get("caption"),
            )
        elif "document" in message:
            message_type = "document"
            doc = message["document"]
            attachment = TelegramMessageAttachment(
                media_type=TelegramMessageType.DOCUMENT,
                mime_type=doc.get("mime_type"),
                file_name=doc.get("file_name"),
                file_size=doc.get("file_size"),
                file_id=doc.get("file_id"),
                file_unique_id=doc.get("file_unique_id"),
                caption=message.get("caption"),
            )
        elif "sticker" in message:
            message_type = "sticker"
            sticker = message["sticker"]
            attachment = TelegramMessageAttachment(
                media_type=TelegramMessageType.STICKER,
                mime_type="image/webp",
                file_size=sticker.get("file_size"),
                file_id=sticker.get("file_id"),
                file_unique_id=sticker.get("file_unique_id"),
            )
        elif "voice" in message:
            message_type = "voice"
            voice = message["voice"]
            attachment = TelegramMessageAttachment(
                media_type=TelegramMessageType.VOICE,
                mime_type=voice.get("mime_type"),
                file_size=voice.get("file_size"),
                file_id=voice.get("file_id"),
                file_unique_id=voice.get("file_unique_id"),
            )
        elif "video_note" in message:
            message_type = "video_note"
            vn = message["video_note"]
            attachment = TelegramMessageAttachment(
                media_type=TelegramMessageType.VIDEO_NOTE,
                mime_type="video/mp4",
                file_size=vn.get("file_size"),
                file_id=vn.get("file_id"),
                file_unique_id=vn.get("file_unique_id"),
            )
        elif "contact" in message:
            message_type = "contact"
            # Contact handled as text with structured data
            contact = message["contact"]
            text = (
                f"Contact: {contact.get('first_name', '')} "
                f"{contact.get('last_name', '')} - {contact.get('phone_number', '')}"
            )
        elif "location" in message:
            message_type = "location"
            loc = message["location"]
            text = f"Location: {loc.get('latitude')}, {loc.get('longitude')}"
        elif "animation" in message:
            message_type = "animation"
            anim = message["animation"]
            attachment = TelegramMessageAttachment(
                media_type=TelegramMessageType.ANIMATION,
                mime_type=anim.get("mime_type"),
                file_name=anim.get("file_name"),
                file_size=anim.get("file_size"),
                file_id=anim.get("file_id"),
                file_unique_id=anim.get("file_unique_id"),
                caption=message.get("caption"),
            )

        # Handle /start command for Telegram identity linking
        if text and text.strip() == "/start":
            await self._handle_start_command(chat_id, from_contact)
            # Still queue the message for any other handlers
            # but don't process further for /start

        # Build normalized message
        normalized = IncomingTelegramMessage(
            event_id=f"{update_id}:{message_id}",
            provider=self.provider_name,
            provider_timestamp=date_ts,
            from_contact=from_contact,
            to_contact=to_contact,
            message_type=TelegramMessageType(message_type),
            text=text,
            attachment=attachment,
            reply_to_message_id=reply_to,
            is_forwarded=message.get("forward_date") is not None,
            is_from_me=False,
            chat_id=chat_id,
            raw_provider_data=message,
        )

        await self._message_queue.put(normalized)

    async def _handle_start_command(
        self, chat_id: str, from_contact: TelegramContactIdentity
    ) -> None:
        """Handle /start: generate linking challenge and send onboarding message."""
        if not self._challenge_repo:
            # Challenge repo not configured, send basic welcome
            await self._send_onboarding_message(
                chat_id,
                "Welcome to Beru! To link your Telegram account to your "
                "student profile, please visit the Beru app and use the "
                "Telegram linking feature.",
            )
            return

        telegram_user_id = from_contact.provider_user_id

        # Check for existing pending challenge
        existing = await self._challenge_repo.get_pending_by_telegram_user_id(
            telegram_user_id
        )
        if existing:
            challenge_token = existing.challenge_token
        else:
            # Generate new challenge
            challenge_token = secrets.token_urlsafe(32)
            expires_at = datetime.now(UTC) + timedelta(minutes=10)
            await self._challenge_repo.create(
                telegram_user_id=telegram_user_id,
                challenge_token=challenge_token,
                expires_at=expires_at.isoformat(),
            )

        # Send onboarding message with challenge token
        onboarding_text = (
            f"Welcome to Beru! 🎓\n\n"
            f"To link your Telegram account to your student profile:\n\n"
            f"1. Open the Beru app and log in\n"
            f"2. Go to Settings → Telegram Linking\n"
            f"3. Enter this challenge code: <code>{challenge_token}</code>\n\n"
            f"This code expires in 10 minutes and can only be used once.\n\n"
            f"Once linked, you'll receive timetable updates, attendance alerts, "
            f"and more directly here."
        )
        await self._send_onboarding_message(chat_id, onboarding_text)

    async def _send_onboarding_message(self, chat_id: str, text: str) -> None:
        """Send an onboarding message with HTML formatting."""
        if not self._session or not self._config:
            return
        url = f"https://api.telegram.org/bot{self._config.bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        try:
            async with self._session.post(url, json=payload) as resp:
                await resp.json()
        except Exception:
            # Log error but don't fail the message processing
            logging.exception("Failed to send onboarding message")

    async def _handle_callback_query(self, callback: dict) -> None:
        """Handle callback query (inline button press)."""
        query_id = callback.get("id")
        from_user = callback.get("from", {})
        data = callback.get("data")
        message = callback.get("message")

        if not message:
            return

        chat_id = str(message.get("chat", {}).get("id", 0))

        from_contact = TelegramContactIdentity(
            provider=self.provider_name,
            provider_user_id=str(from_user.get("id", 0)),
            normalized_identifier=f"@{from_user.get('username')}"
            if from_user.get("username")
            else None,
            display_name=" ".join(
                filter(
                    None,
                    [
                        from_user.get("first_name"),
                        from_user.get("last_name"),
                    ],
                )
            )
            or None,
            is_bot=from_user.get("is_bot", False),
        )

        to_contact = self._our_identity or TelegramContactIdentity(
            provider=self.provider_name,
            provider_user_id="",
        )

        # Build normalized message for callback
        normalized = IncomingTelegramMessage(
            event_id=f"callback:{query_id}",
            provider=self.provider_name,
            provider_timestamp=int(datetime.now(UTC).timestamp()),
            from_contact=from_contact,
            to_contact=to_contact,
            message_type=TelegramMessageType.UNKNOWN,
            text=None,
            interactive_reply=TelegramInteractiveReply(
                reply_id=query_id,
                data=data,
                message_text=message.get("text"),
            ),
            chat_id=chat_id,
            raw_provider_data=callback,
        )

        await self._message_queue.put(normalized)

        # Answer callback query to remove loading state
        await self._answer_callback_query(query_id)

    async def _answer_callback_query(self, query_id: str) -> None:
        """Answer callback query to remove loading state."""
        if not self._session or not self._config:
            return
        url = f"https://api.telegram.org/bot{self._config.bot_token}/answerCallbackQuery"
        await self._session.post(url, json={"callback_query_id": query_id})


def register_telegram_provider():
    """Register the Telegram Bot provider with the global registry."""
    telegram_provider_registry.register(TelegramBotAdapter)
