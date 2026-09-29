"""Tests for Telegram message handler and conversation routing."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.models.student import Student
from app.security.context import (
    AuthenticatedIdentity,
    AuthenticationMethod,
    UnauthenticatedIdentity,
)
from app.telegram.bot_adapter import TelegramBotAdapter, TelegramBotConfig
from app.telegram.message_handler import TelegramMessageHandler
from app.telegram.models import (
    IncomingTelegramMessage,
    OutgoingTelegramMessage,
    TelegramContactIdentity,
    TelegramMessageType,
)


def _make_incoming_message(
    text: str,
    user_id: str = "12345",
    chat_id: str = "67890",
    event_id: str = "1:1",
) -> IncomingTelegramMessage:
    from_contact = TelegramContactIdentity(
        provider="telegram_bot",
        provider_user_id=user_id,
        normalized_identifier="@testuser",
        display_name="Test User",
    )
    to_contact = TelegramContactIdentity(
        provider="telegram_bot",
        provider_user_id="bot123",
        normalized_identifier="@berubot",
        display_name="Beru",
        is_bot=True,
    )
    return IncomingTelegramMessage(
        event_id=event_id,
        provider="telegram_bot",
        provider_timestamp=int(datetime.now(UTC).timestamp()),
        from_contact=from_contact,
        to_contact=to_contact,
        message_type=TelegramMessageType.TEXT,
        text=text,
        chat_id=chat_id,
    )


class TestTelegramMessageHandler:
    """Test suite for Telegram message handler."""

    @pytest.mark.asyncio
    async def test_handle_start_command_creates_challenge(self):
        """Test /start triggers linking challenge and sends onboarding message."""
        adapter = MagicMock(spec=TelegramBotAdapter)
        adapter.send_message = AsyncMock(return_value="msg_101")
        adapter._our_identity = None

        mock_session = AsyncMock()
        mock_challenge = MagicMock()
        mock_challenge.challenge_token = "secure_token_123"  # noqa: S105

        @asynccontextmanager
        async def session_factory():
            yield mock_session

        handler = TelegramMessageHandler(
            adapter=adapter,
            session_factory=session_factory,
        )

        msg = _make_incoming_message(
            text="/start", user_id="user_999", chat_id="chat_999"
        )

        # Mock TelegramLinkingService create_linking_challenge
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "app.telegram.message_handler.TelegramLinkingService.create_linking_challenge",
                AsyncMock(return_value="secure_token_123"),
            )
            await handler._handle_message(msg)

        assert adapter.send_message.called
        call_arg = adapter.send_message.call_args[0][0]
        assert isinstance(call_arg, OutgoingTelegramMessage)
        assert call_arg.chat_id == "chat_999"
        assert "secure_token_123" in call_arg.text
        assert call_arg.parse_mode == "HTML"

    @pytest.mark.asyncio
    async def test_handle_unlinked_user_message(self):
        """Test message from unlinked user receives unlinked prompt."""
        adapter = MagicMock(spec=TelegramBotAdapter)
        adapter.send_message = AsyncMock(return_value="msg_102")
        adapter._our_identity = None

        mock_session = AsyncMock()

        @asynccontextmanager
        async def session_factory():
            yield mock_session

        mock_identity_resolver = MagicMock()
        mock_identity_resolver.resolve = AsyncMock(
            return_value=UnauthenticatedIdentity(
                provider="telegram_bot",
                external_identity_id="user_unlinked",
                reason="Identity not found in database",
            )
        )

        handler = TelegramMessageHandler(
            adapter=adapter,
            session_factory=session_factory,
            identity_resolver=mock_identity_resolver,
        )

        msg = _make_incoming_message(
            text="Hello Beru", user_id="user_unlinked", chat_id="chat_1"
        )
        await handler._handle_message(msg)

        assert adapter.send_message.called
        call_arg = adapter.send_message.call_args[0][0]
        assert "I don't recognize this Telegram account" in call_arg.text

    @pytest.mark.asyncio
    async def test_handle_authenticated_conversation_message(self):
        """Test authenticated user message routed to conversation pipeline."""
        student_id = uuid4()
        adapter = MagicMock(spec=TelegramBotAdapter)
        adapter.send_message = AsyncMock(return_value="msg_103")
        adapter._our_identity = None

        mock_session = AsyncMock()

        @asynccontextmanager
        async def session_factory():
            yield mock_session

        mock_identity_resolver = MagicMock()
        mock_identity_resolver.resolve = AsyncMock(
            return_value=AuthenticatedIdentity(
                provider="telegram_bot",
                external_identity_id="user_linked",
                student_id=student_id,
                authentication_method=AuthenticationMethod.TELEGRAM_BOT,
            )
        )

        mock_student_repo = MagicMock()
        mock_student = Student(id=student_id, name="Harshik", attendance_target=80.0)
        mock_student_repo.get_or_create = AsyncMock(return_value=mock_student)

        mock_conversation_service = MagicMock()
        mock_conversation_service.process_message = AsyncMock(
            return_value=("Your attendance is 85%", None)
        )

        handler = TelegramMessageHandler(
            adapter=adapter,
            session_factory=session_factory,
            identity_resolver=mock_identity_resolver,
            conversation_service=mock_conversation_service,
            student_repo=mock_student_repo,
        )

        msg = _make_incoming_message(
            text="What is my attendance?", user_id="user_linked", chat_id="chat_1"
        )
        await handler._handle_message(msg)

        assert mock_conversation_service.process_message.called
        ctx, text = mock_conversation_service.process_message.call_args[0]
        assert text == "What is my attendance?"
        assert ctx.student_id == student_id
        assert ctx.profile.name == "Harshik"
        assert ctx.profile.attendance_target == 80.0

        assert adapter.send_message.called
        call_arg = adapter.send_message.call_args[0][0]
        assert call_arg.text == "Your attendance is 85%"

    @pytest.mark.asyncio
    async def test_duplicate_message_is_skipped(self):
        """Test that duplicate messages are skipped via idempotency check."""
        adapter = MagicMock(spec=TelegramBotAdapter)
        adapter.send_message = AsyncMock()

        mock_session = AsyncMock()

        @asynccontextmanager
        async def session_factory():
            yield mock_session

        handler = TelegramMessageHandler(
            adapter=adapter,
            session_factory=session_factory,
        )

        msg = _make_incoming_message(text="/start", event_id="dup:1")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "app.telegram.message_handler.TelegramLinkingService.create_linking_challenge",
                AsyncMock(return_value="tok_1"),
            )
            # First delivery
            await handler._handle_message(msg)
            assert adapter.send_message.call_count == 1

            # Duplicate delivery
            await handler._handle_message(msg)
            # Should still be 1 (second call was skipped)
            assert adapter.send_message.call_count == 1


class TestTelegramBotAdapterEnhancements:
    """Test updated adapter behavior: drop pending updates & parse_mode."""

    @pytest.mark.asyncio
    async def test_drop_pending_updates_acknowledges_latest(self):
        adapter = TelegramBotAdapter()
        adapter._config = TelegramBotConfig(
            bot_token="test_token",  # noqa: S106
            poll_timeout=30,
            drop_pending_updates=True,
        )

        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json = AsyncMock(
            return_value={
                "ok": True,
                "result": [{"update_id": 555}],
            }
        )
        mock_session.get.return_value.__aenter__.return_value = mock_resp
        adapter._session = mock_session

        await adapter._drop_pending_updates()

        # Should have called get twice: once with offset=-1, once with offset=556
        assert mock_session.get.call_count == 2
        calls = mock_session.get.call_args_list
        assert calls[0][1]["params"] == {"offset": -1}
        assert calls[1][1]["params"] == {"offset": 556}
        assert adapter._last_update_id == 555

    @pytest.mark.asyncio
    async def test_send_message_includes_parse_mode(self):
        adapter = TelegramBotAdapter()
        adapter._config = TelegramBotConfig(bot_token="test_token")  # noqa: S106

        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json = AsyncMock(
            return_value={"ok": True, "result": {"message_id": 1234}}
        )
        mock_session.post.return_value.__aenter__.return_value = mock_resp
        adapter._session = mock_session

        outgoing = OutgoingTelegramMessage(
            to_contact=TelegramContactIdentity(
                provider="telegram_bot", provider_user_id="user1"
            ),
            from_contact=TelegramContactIdentity(
                provider="telegram_bot", provider_user_id="bot1"
            ),
            message_type=TelegramMessageType.TEXT,
            text="Hello <b>World</b>",
            chat_id="user1",
            parse_mode="HTML",
        )

        msg_id = await adapter.send_message(outgoing)
        assert msg_id == "1234"

        post_kwargs = mock_session.post.call_args[1]
        assert post_kwargs["json"]["parse_mode"] == "HTML"
        assert post_kwargs["json"]["text"] == "Hello <b>World</b>"

    @pytest.mark.asyncio
    async def test_download_file(self, tmp_path):
        adapter = TelegramBotAdapter()
        adapter._config = TelegramBotConfig(bot_token="test_token")  # noqa: S106

        mock_session = MagicMock()
        get_file_resp = MagicMock()
        get_file_resp.json = AsyncMock(
            return_value={
                "ok": True,
                "result": {
                    "file_id": "file_123",
                    "file_path": "documents/timetable.pdf",
                },
            }
        )
        file_download_resp = MagicMock()
        file_download_resp.status = 200

        # Simulate chunk streaming
        async def mock_read(chunk_size):
            if not hasattr(mock_read, "called"):
                mock_read.called = True
                return b"%PDF-1.4 test content"
            return b""

        file_download_resp.content.read = mock_read

        # Return get_file_resp first, then file_download_resp
        mock_session.get.return_value.__aenter__.side_effect = [
            get_file_resp,
            file_download_resp,
        ]
        adapter._session = mock_session

        dest_file = str(tmp_path / "downloaded.pdf")
        saved_path = await adapter.download_file("file_123", dest_file)
        assert saved_path == dest_file
        with open(dest_file, "rb") as f:
            assert f.read() == b"%PDF-1.4 test content"


class TestTelegramMessageMediaAndContext:
    """Test suite for media ingestion and multi-turn context."""

    @pytest.mark.asyncio
    async def test_multi_turn_conversation_context_persistence(self):
        """Test conversation history persists across multiple turns."""
        from app.intelligence.models.context import StudentContext

        student_id = uuid4()
        adapter = MagicMock(spec=TelegramBotAdapter)
        adapter.send_message = AsyncMock(return_value="msg_1")
        adapter._our_identity = None

        mock_session = AsyncMock()

        @asynccontextmanager
        async def session_factory():
            yield mock_session

        mock_identity_resolver = MagicMock()
        mock_identity_resolver.resolve = AsyncMock(
            return_value=AuthenticatedIdentity(
                provider="telegram_bot",
                external_identity_id="user_linked",
                student_id=student_id,
                authentication_method=AuthenticationMethod.TELEGRAM_BOT,
            )
        )

        mock_student_repo = MagicMock()
        mock_student = Student(id=student_id, name="Harshik")
        mock_student_repo.get_or_create = AsyncMock(return_value=mock_student)

        # Mock conversation service that updates conversation history
        async def mock_process(ctx: StudentContext, message_text: str):
            conv = ctx.conversation.add_message("user", message_text)
            conv = conv.add_message("assistant", f"Reply to: {message_text}")
            return f"Reply to: {message_text}", StudentContext(
                student_id=ctx.student_id,
                profile=ctx.profile,
                conversation=conv,
            )

        mock_conversation_service = MagicMock()
        mock_conversation_service.process_message = AsyncMock(side_effect=mock_process)

        handler = TelegramMessageHandler(
            adapter=adapter,
            session_factory=session_factory,
            identity_resolver=mock_identity_resolver,
            conversation_service=mock_conversation_service,
            student_repo=mock_student_repo,
        )

        # Turn 1
        msg1 = _make_incoming_message(
            text="Hello Beru", user_id="user_linked", event_id="ev_1"
        )
        await handler._handle_message(msg1)

        # Verify context now has turn 1
        saved_conv = handler._conversation_contexts.get(student_id)
        assert saved_conv is not None
        assert len(saved_conv.recent_messages) == 2

        # Turn 2
        msg2 = _make_incoming_message(
            text="What classes tomorrow?", user_id="user_linked", event_id="ev_2"
        )
        await handler._handle_message(msg2)

        # Verify context now has turn 1 and turn 2 (4 messages total)
        saved_conv = handler._conversation_contexts.get(student_id)
        assert saved_conv is not None
        assert len(saved_conv.recent_messages) == 4
        assert saved_conv.recent_messages[0]["content"] == "Hello Beru"
        assert saved_conv.recent_messages[2]["content"] == "What classes tomorrow?"

    @pytest.mark.asyncio
    async def test_handle_media_photo_message(self):
        """Test photo message returns prompt requesting official PDF."""
        from app.telegram.models import TelegramMessageAttachment

        student_id = uuid4()
        adapter = MagicMock(spec=TelegramBotAdapter)
        adapter.send_message = AsyncMock(return_value="msg_photo")
        adapter.download_file = AsyncMock(return_value="storage/timetables/test.jpg")
        adapter._our_identity = None

        mock_session = AsyncMock()

        @asynccontextmanager
        async def session_factory():
            yield mock_session

        mock_identity_resolver = MagicMock()
        mock_identity_resolver.resolve = AsyncMock(
            return_value=AuthenticatedIdentity(
                provider="telegram_bot",
                external_identity_id="user_linked",
                student_id=student_id,
                authentication_method=AuthenticationMethod.TELEGRAM_BOT,
            )
        )

        mock_student_repo = MagicMock()
        mock_student = Student(id=student_id, name="Harshik")
        mock_student_repo.get_or_create = AsyncMock(return_value=mock_student)

        handler = TelegramMessageHandler(
            adapter=adapter,
            session_factory=session_factory,
            identity_resolver=mock_identity_resolver,
            student_repo=mock_student_repo,
        )

        from_contact = TelegramContactIdentity(
            provider="telegram_bot", provider_user_id="user_linked"
        )
        to_contact = TelegramContactIdentity(
            provider="telegram_bot", provider_user_id="bot123"
        )
        attachment = TelegramMessageAttachment(
            media_type=TelegramMessageType.PHOTO,
            file_id="photo_file_id",
            file_unique_id="unique_photo_1",
        )
        photo_msg = IncomingTelegramMessage(
            event_id="photo:1",
            provider="telegram_bot",
            provider_timestamp=int(datetime.now(UTC).timestamp()),
            from_contact=from_contact,
            to_contact=to_contact,
            message_type=TelegramMessageType.PHOTO,
            chat_id="chat_1",
            attachment=attachment,
        )

        await handler._handle_message(photo_msg)

        assert adapter.send_message.called
        call_arg = adapter.send_message.call_args[0][0]
        assert "Received your timetable photo" in call_arg.text
        assert "PDF document" in call_arg.text
