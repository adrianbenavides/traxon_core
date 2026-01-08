from traxon_core.logs.notifiers import BasePushNotifier
from traxon_core.logs.notifiers.telegram import TelegramNotifier


def test_telegram_notifier_moved() -> None:
    """Verify TelegramNotifier is in the new module and inherits from BasePushNotifier."""
    notifier = TelegramNotifier()
    assert isinstance(notifier, BasePushNotifier)
