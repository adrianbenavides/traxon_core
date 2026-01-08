import abc
import asyncio
from datetime import datetime
from typing import Any

import aiohttp
import pandas as pd
import polars as pl
from beartype import beartype
from src.config.notification import TelegramConfig
from src.logs.structlog import logger
from typing_extensions import TypeGuard


class PushNotifier(abc.ABC):
    """
    Abstract base class for push notification services.

    Defines the interface that all notification implementations should follow.
    """

    def __init__(self) -> None:
        self.is_running: bool = False

    @abc.abstractmethod
    @beartype
    async def start(self) -> None:
        """Start the notifier background task."""
        pass

    @abc.abstractmethod
    @beartype
    async def stop(self) -> None:
        """Stop the notifier background task."""
        pass

    @abc.abstractmethod
    @beartype
    async def send(self, message: object) -> None:
        """Send a simple message without level or data."""
        pass

    @abc.abstractmethod
    @beartype
    async def send_error(
        self,
        error_message: object,
        exception: Exception | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Send error notification with exception details if available."""
        pass

    @staticmethod
    @beartype
    def _is_dataframe(message: object) -> TypeGuard[pd.DataFrame | pl.DataFrame]:
        return isinstance(message, pd.DataFrame) or isinstance(message, pl.DataFrame)

    @staticmethod
    @beartype
    def _process_notification(message: object) -> str:
        if PushNotifier._is_dataframe(message):

            def _format_value(v: object, n: int) -> str:
                if isinstance(v, float) or hasattr(v, "__float__"):
                    return f"{float(v):.{n}f}"
                return str(v)

            decimal_places: int = 4

            # Get column names and their string representations
            cols: list[str]
            rows: list[list[Any]]

            if isinstance(message, pd.DataFrame):
                df_pd: pd.DataFrame = message.copy()
                cols = [str(col) for col in df_pd.columns]
                rows = df_pd.values.tolist()
            else:
                df_pl: pl.DataFrame = message.clone()
                cols = [str(col) for col in df_pl.columns]
                rows = [list(row) for row in df_pl.rows()]

            result: list[str] = []

            # Add header row
            header: str = ", ".join(cols)
            result.append(header)

            # Add separator line
            result.append(f"{'=' * 52}")

            # Add data rows
            for row in rows:
                formatted_values = [_format_value(row[i], decimal_places) for i in range(len(cols))]
                result.append(", ".join(formatted_values))

            # Join all lines with newlines
            return "\n".join(result)
        return str(message)

    @beartype
    async def notify(
        self,
        message: object,
    ) -> None:
        await self.send(self._process_notification(message))


class TelegramNotifier(PushNotifier):
    """
    Handles sending push notifications to Telegram chat.

    Includes different notification levels, rate limiting, and formatting.
    """

    def __init__(self) -> None:
        super().__init__()
        self.enabled: bool = False
        self.bot_token: str = ""
        self.chat_id: str = ""
        self.rate_limit_seconds: int = 0
        self.max_messages_per_minute: int = 0

        # Message queue and rate limiting
        self.message_queue: asyncio.Queue[str | dict[str, Any] | None] = asyncio.Queue()
        self.recent_messages: list[datetime] = []

    @beartype
    def configure(self, config: TelegramConfig) -> "TelegramNotifier":
        self.enabled = config.enabled
        self.bot_token = config.bot_token
        self.chat_id = config.chat_id
        self.rate_limit_seconds = config.rate_limit_seconds
        self.max_messages_per_minute = config.max_messages_per_minute
        return self

    @beartype
    async def start(self) -> None:
        """Start the notifier background task."""
        if not self.enabled:
            logger.info("Telegram notifier is disabled, skipping start")
            return
        self.is_running = True
        await self._process_queue()

    @beartype
    async def stop(self) -> None:
        """Stop the notifier background task."""
        self.is_running = False
        # Add a sentinel to unblock the queue
        await self.message_queue.put(None)

    @beartype
    async def _send_notification(self, chat_id: str, text: str) -> None:
        """Send a notification to a specific Telegram chat."""
        if not text or text == "":
            return None

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        for attempt in range(3):
            try:
                async with aiohttp.ClientSession() as session:
                    timeout = aiohttp.ClientTimeout(total=5)
                    async with session.post(url, params=params, timeout=timeout) as response:
                        response.raise_for_status()
                        return None
            except Exception as _e:
                logger.debug(f"error sending message (attempt {attempt + 1}/3)")

        logger.error(f"failed to send message to chat {chat_id} after 3 attempts")
        return None

    @beartype
    async def _process_queue(self) -> None:
        """Process the message queue in the background."""
        while self.is_running:
            try:
                message = await self.message_queue.get()

                # Check for stop sentinel
                if message is None:
                    break

                # Check rate limiting
                now = datetime.now()
                self.recent_messages = [
                    t for t in self.recent_messages if (now - t).total_seconds() < self.rate_limit_seconds
                ]

                if len(self.recent_messages) >= self.max_messages_per_minute:
                    logger.warning(
                        f"notifications rate limit exceeded: {len(self.recent_messages)} messages in "
                        f"{self.rate_limit_seconds} seconds"
                    )

                    # If this is already a batched message, we need to send it despite rate limit
                    if isinstance(message, dict) and not message.get("is_batched", False):
                        # Queue the message again after a delay
                        await asyncio.sleep(5)
                        await self.message_queue.put(message)
                        continue

                if isinstance(message, dict):
                    text = message.get("text", "")
                else:
                    text = str(message)

                # Send notification
                await self._send_notification(
                    chat_id=self.chat_id,
                    text=text,
                )
                self.recent_messages.append(now)

                # Small delay between messages to avoid hitting Telegram's rate limits
                await asyncio.sleep(0.5)

                # Mark the task as done
                self.message_queue.task_done()

            except Exception as e:
                logger.error(f"Error in telegram notifier process_queue: {e}", exc_info=True)

                # Don't crash the loop
                await asyncio.sleep(1)

    @beartype
    async def _queue_notification(
        self,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """
        Queue a message to be sent.

        Args:
            message: The notification message
            data: Optional data to include in the message
        """
        if not self.is_running:
            return

        formatted_message: str = message

        # Add data details if provided
        if data:
            data_text: str = "\n\n<b>Details:</b>\n"
            for k, v in data.items():
                if isinstance(v, (dict, list)):
                    # Truncate complex values
                    data_text += f"• <b>{k}</b>: [complex data]\n"
                else:
                    # Format numeric values
                    if isinstance(v, float):
                        v = f"{v:.6f}"
                    data_text += f"• <b>{k}</b>: {v}\n"

            formatted_message += data_text

        await self.message_queue.put({"text": formatted_message, "is_batched": False})

    @beartype
    async def send(self, message: object) -> None:
        """Send a simple message without level or data."""
        await self._queue_notification(f"{message}")

    @beartype
    async def send_error(
        self,
        error_message: object,
        exception: Exception | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """
        Send error notification with exception details if available.

        Args:
            error_message: Error description
            exception: Exception object
            context: Context information about when/where error occurred
        """
        message: str = f"<b>ERROR:</b> {error_message}\n"

        details: dict[str, Any] = {}

        if exception:
            error_type: str = type(exception).__name__
            error_details: str = str(exception)

            message += f"<b>Type:</b> {error_type}\n"
            details["error_details"] = error_details

        if context:
            details.update(context)

        await self._queue_notification(message, details)


# Global notifier instance
notifier: PushNotifier = TelegramNotifier()
