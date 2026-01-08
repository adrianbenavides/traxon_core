from unittest.mock import MagicMock

from traxon_core.logs import notifiers
from traxon_core.logs.logger import Logger


def test_logger_configure_agnostic() -> None:
    """Verify Logger.configure accepts a PushNotifier protocol instance."""
    mock_notifier = MagicMock(spec=notifiers.PushNotifier)

    # This should work with the new signature
    Logger.configure(service_name="test-service", log_level="INFO", notifier=mock_notifier)

    # Verify global notifier was updated
    assert notifiers.notifier == mock_notifier
