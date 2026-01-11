import abc
from typing import Any, Protocol, runtime_checkable

import polars as pl
from beartype import beartype
from typing_extensions import TypeGuard


@runtime_checkable
class PushNotifier(Protocol):
    """
    Protocol defining the interface for push notification services.
    """

    async def start(self) -> None:
        """Start the notifier background task."""
        ...

    async def stop(self) -> None:
        """Stop the notifier background task."""
        ...

    async def send(self, message: object) -> None:
        """Send a simple message without level or data."""
        ...

    async def send_error(
        self,
        error_message: object,
        exception: Exception | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Send error notification with exception details if available."""
        ...

    async def notify(
        self,
        message: object,
    ) -> None:
        """Send a notification (processed)."""
        ...


class BasePushNotifier(abc.ABC, PushNotifier):
    """
    Abstract base class for push notification services.

    Implements common logic for all notification implementations.
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
        pass

    @abc.abstractmethod
    @beartype
    async def send_error(
        self,
        error_message: object,
        exception: Exception | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        pass

    @staticmethod
    @beartype
    def _is_dataframe(message: object) -> TypeGuard[pl.DataFrame]:
        return isinstance(message, pl.DataFrame)

    @staticmethod
    @beartype
    def _process_notification(message: object) -> str:
        if BasePushNotifier._is_dataframe(message):

            def _format_value(v: object, n: int) -> str:
                if isinstance(v, float) or hasattr(v, "__float__"):
                    return f"{float(v):.{n}f}"
                return str(v)

            decimal_places: int = 4

            # Get column names and their string representations
            cols: list[str] = [str(col) for col in message.columns]
            rows: list[list[Any]] = [list(row) for row in message.rows()]

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


class NoOpNotifier(BasePushNotifier):
    """
    Notifier that does nothing. Used as a default.
    """

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send(self, message: object) -> None:
        pass

    async def send_error(
        self,
        error_message: object,
        exception: Exception | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        pass


# Global notifier instance, defaulting to NoOpNotifier
notifier: PushNotifier = NoOpNotifier()
