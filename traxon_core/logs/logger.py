from traxon_core.logs import notifiers, structlog
from traxon_core.logs.notifiers import PushNotifier


class Logger:
    @classmethod
    def configure(cls, service_name: str, log_level: str, notifier: PushNotifier) -> None:
        structlog.configure(service_name, log_level)
        notifiers.notifier = notifier
