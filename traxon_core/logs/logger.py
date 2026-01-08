from typing import Any

import structlog

from traxon_core.config.notification import TelegramConfig
from traxon_core.logs.push import PushNotifier, TelegramNotifier


class Logger:
    @classmethod
    def configure(cls, service_name: str, log_level: str, notifier_config: TelegramConfig) -> None:
        src.logs.structlog.configure(service_name, log_level)
        src.logs.push.notifier = TelegramNotifier().configure(notifier_config)
