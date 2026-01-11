from typing import Any

import polars as pl
import pytest

from traxon_core.logs.notifiers import BasePushNotifier, NoOpNotifier


class TestNotifier(BasePushNotifier):
    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send(self, message: object) -> None:
        self.sent_message = message

    async def send_error(
        self, error_message: object, exception: Exception | None = None, context: dict[str, Any] | None = None
    ) -> None:
        pass


def test_process_notification_polars():
    df = pl.DataFrame({"a": [1, 2], "b": [3.14159, 4.0]})
    result = BasePushNotifier._process_notification(df)
    assert "a, b" in result
    assert "1.0000, 3.1416" in result
    assert "2.0000, 4.0000" in result


def test_process_notification_string():
    result = BasePushNotifier._process_notification("hello")
    assert result == "hello"
