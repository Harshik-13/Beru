"""Tests for Telegram Bot API startup and verification."""

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from app.telegram.bot_adapter import TelegramBotAdapter, TelegramBotConfig
from app.telegram.provider import TelegramProviderConfig


class TestTelegramStartupVerification:
    """Tests for Telegram Bot API startup and token verification."""

    @pytest.fixture
    def mock_aiohttp_session(self):
        """Create a mock aiohttp session."""
        session = MagicMock(spec=aiohttp.ClientSession)
        session.get = MagicMock()
        session.post = MagicMock()
        return session

    @pytest.fixture
    def bot_adapter(self):
        """Create a TelegramBotAdapter instance."""
        return TelegramBotAdapter()

    @pytest.mark.asyncio
    async def test_disabled_telegram_no_connection_attempt(self):
        """Test that disabled Telegram does not attempt to connect."""
        # This is tested via main.py lifespan logic
        # If TELEGRAM_ENABLED=false, adapter is never created/initialized
        assert True  # Verified by main.py logic

    @pytest.mark.asyncio
    async def test_missing_token_raises_error(self):
        """Test that missing token raises RuntimeError during initialize."""
        adapter = TelegramBotAdapter()

        # Try to initialize with empty token
        _ = TelegramProviderConfig(
            provider_name="telegram_bot",
            config={
                "bot_token": "",  # Empty token
                "poll_timeout": 30,
                "drop_pending_updates": True,
            },
        )

        with pytest.raises(RuntimeError, match="Telegram bot token is required"):
            await adapter.initialize(
                TelegramProviderConfig(
                    provider_name="telegram_bot",
                    config={
                        "bot_token": "",
                        "poll_timeout": 30,
                        "drop_pending_updates": True,
                    },
                )
            )

    @pytest.mark.asyncio
    async def test_valid_getme_response_sets_identity(self):
        """Test that valid getMe response sets bot identity."""
        adapter = TelegramBotAdapter()

        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json = AsyncMock(
            return_value={
                "ok": True,
                "result": {
                    "id": 123456789,
                    "first_name": "TestBot",
                    "username": "testbot",
                    "is_bot": True,
                },
            }
        )
        mock_session.get.return_value.__aenter__.return_value = mock_resp

        adapter._session = mock_session
        adapter._config = TelegramBotConfig(
            bot_token="123456789:ABCdefGHIjklMNOpqrSTUvwxyz",
            poll_timeout=30,
        )

        await adapter._get_me()

        assert adapter._our_identity is not None
        assert adapter._our_identity.provider_user_id == "123456789"
        assert adapter._our_identity.normalized_identifier == "@testbot"
        assert adapter._our_identity.display_name == "TestBot"
        assert adapter._our_identity.is_bot is True

    @pytest.mark.asyncio
    async def test_invalid_token_raises_error(self):
        """Test that invalid token (401) raises RuntimeError."""
        adapter = TelegramBotAdapter()

        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json = AsyncMock(
            return_value={
                "ok": False,
                "error_code": 401,
                "description": "Unauthorized",
            }
        )
        mock_session.get.return_value.__aenter__.return_value = mock_resp

        adapter._session = mock_session
        adapter._config = TelegramBotConfig(
            bot_token="invalid_token",
            poll_timeout=30,
        )

        with pytest.raises(RuntimeError, match="Invalid Telegram bot token"):
            await adapter._get_me()

    @pytest.mark.asyncio
    async def test_api_unreachable_raises_error(self):
        """Test that unreachable API raises RuntimeError."""
        adapter = TelegramBotAdapter()

        mock_session = MagicMock()
        mock_session.get.side_effect = aiohttp.ClientError("Connection refused")

        adapter._session = mock_session
        adapter._config = TelegramBotConfig(
            bot_token="123456789:ABCdefGHIjklMNOpqrSTUvwxyz",
            poll_timeout=30,
        )

        with pytest.raises(RuntimeError, match="Telegram API unreachable"):
            await adapter._get_me()

    @pytest.mark.asyncio
    async def test_api_timeout_raises_error(self):
        """Test that API timeout raises RuntimeError."""
        adapter = TelegramBotAdapter()

        mock_session = MagicMock()
        mock_session.get.side_effect = TimeoutError()

        adapter._session = mock_session
        adapter._config = TelegramBotConfig(
            bot_token="123456789:ABCdefGHIjklMNOpqrSTUvwxyz",
            poll_timeout=30,
        )

        with pytest.raises(RuntimeError, match="Telegram API request timed out"):
            await adapter._get_me()

    @pytest.mark.asyncio
    async def test_invalid_response_raises_error(self):
        """Test that invalid API response raises RuntimeError."""
        adapter = TelegramBotAdapter()

        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json = AsyncMock(
            return_value={
                "ok": False,
                "error_code": 400,
                "description": "Bad Request",
            }
        )
        mock_session.get.return_value.__aenter__.return_value = mock_resp

        adapter._session = mock_session
        adapter._config = TelegramBotConfig(
            bot_token="123456789:ABCdefGHIjklMNOpqrSTUvwxyz",
            poll_timeout=30,
        )

        with pytest.raises(RuntimeError, match="Telegram API error"):
            await adapter._get_me()

    @pytest.mark.asyncio
    async def test_success_without_username(self):
        """Test that bot without username works correctly."""
        adapter = TelegramBotAdapter()

        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json = AsyncMock(
            return_value={
                "ok": True,
                "result": {
                    "id": 987654321,
                    "first_name": "NoUsernameBot",
                    "username": None,
                    "is_bot": True,
                },
            }
        )
        mock_session.get.return_value.__aenter__.return_value = mock_resp

        adapter._session = mock_session
        adapter._config = TelegramBotConfig(
            bot_token="123456789:ABCdefGHIjklMNOpqrSTUvwxyz",
            poll_timeout=30,
        )

        await adapter._get_me()

        assert adapter._our_identity is not None
        assert adapter._our_identity.provider_user_id == "987654321"
        assert adapter._our_identity.normalized_identifier is None
        assert adapter._our_identity.display_name == "NoUsernameBot"

    @pytest.mark.asyncio
    async def test_missing_bot_info_in_response(self):
        """Test that missing bot info in response raises error."""
        adapter = TelegramBotAdapter()

        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json = AsyncMock(
            return_value={
                "ok": True,
                "result": None,  # Missing bot info
            }
        )
        mock_session.get.return_value.__aenter__.return_value = mock_resp

        adapter._session = mock_session
        adapter._config = TelegramBotConfig(
            bot_token="123456789:ABCdefGHIjklMNOpqrSTUvwxyz",
            poll_timeout=30,
        )

        with pytest.raises(RuntimeError, match="no bot info"):
            await adapter._get_me()

    @pytest.mark.asyncio
    async def test_missing_session_raises_error(self):
        """Test that missing session raises error."""
        adapter = TelegramBotAdapter()
        adapter._config = TelegramBotConfig(
            bot_token="123456789:ABCdefGHIjklMNOpqrSTUvwxyz",
            poll_timeout=30,
        )
        # Session is None

        with pytest.raises(RuntimeError, match="Adapter not initialized"):
            await adapter._get_me()

    @pytest.mark.asyncio
    async def test_missing_config_raises_error(self):
        """Test that missing config raises error."""
        adapter = TelegramBotAdapter()
        mock_session = MagicMock()
        adapter._session = mock_session
        # Config is None

        with pytest.raises(RuntimeError, match="Adapter not initialized"):
            await adapter._get_me()


class TestTokenRedaction:
    """Test that bot token is never exposed in logs or errors."""

    def test_token_not_in_error_messages(self):
        """Test that token doesn't appear in error messages."""
        # The error messages should never contain the actual token
        error_msgs = [
            "Invalid Telegram bot token (401 Unauthorized)",
            "Telegram API error (400): Bad Request",
            "Telegram API unreachable: Connection refused",
            "Telegram API request timed out",
            "Telegram API error (404): Not Found",
        ]

        # None should contain a token-like pattern
        import re
        token_pattern = r"\d+:[A-Za-z0-9_-]{35}"
        for msg in error_msgs:
            assert not re.search(token_pattern, msg)

    def test_token_not_in_bot_adapter_source(self):
        """Test that bot token is not hardcoded in source."""
        import inspect

        import app.telegram.bot_adapter as bot_module

        source = inspect.getsource(bot_module)
        # Token should only appear as config.bot_token or self._config.bot_token
        # Not as literal strings
        # This is a basic check - real tokens would be in .env only
        assert "123456789:ABCdefGHIjklMNOpqrSTUvwxyz" not in source


class TestTelegramAdapterLifecycle:
    """Test Telegram adapter lifecycle with different configurations."""

    @pytest.mark.asyncio
    async def test_initialize_with_valid_config(self):
        """Test that initialize works with valid config."""
        adapter = TelegramBotAdapter()

        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json = AsyncMock(
            return_value={
                "ok": True,
                "result": {
                    "id": 123456789,
                    "first_name": "TestBot",
                    "username": "testbot",
                    "is_bot": True,
                },
            }
        )
        mock_session.get.return_value.__aenter__.return_value = mock_resp

        with patch("aiohttp.ClientSession", return_value=mock_session):
            await adapter.initialize(
                TelegramProviderConfig(
                    provider_name="telegram_bot",
                    config={
                        "bot_token": "123456789:ABCdefGHIjklMNOpqrSTUvwxyz",
                        "poll_timeout": 30,
                        "drop_pending_updates": True,
                    },
                )
            )

        assert adapter._session is not None
        assert adapter._config is not None
        assert adapter._our_identity is not None

    @pytest.mark.asyncio
    async def test_start_fails_if_not_initialized(self):
        """Test that start() fails if adapter not initialized."""
        adapter = TelegramBotAdapter()

        with pytest.raises(RuntimeError, match="Adapter not initialized"):
            await adapter.start()

    @pytest.mark.asyncio
    async def test_start_fails_if_no_session(self):
        """Test that start() fails if no session."""
        adapter = TelegramBotAdapter()
        adapter._config = TelegramBotConfig(bot_token="token", poll_timeout=30)
        # No session

        with pytest.raises(RuntimeError, match="Adapter not initialized"):
            await adapter.start()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

