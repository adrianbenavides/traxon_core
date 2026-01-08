from __future__ import annotations

import logging.config
import os

import structlog
from beartype import beartype


class ModuleFilter(logging.Filter):
    def __init__(self, modules_to_log: dict[str, str]) -> None:
        super().__init__()
        self.modules_to_log: dict[str, str] = modules_to_log

    def filter(self, record: logging.LogRecord) -> bool:
        if not self.modules_to_log:
            return True

        for module, level in self.modules_to_log.items():
            if module == "*" or record.name.startswith(module):
                min_log_level = logging.getLevelName(level)
                if not isinstance(min_log_level, int):
                    min_log_level = logging.INFO
                return record.levelno >= min_log_level

        return False


timestamper = structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S")
pre_chain = [
    # Add the log level and a timestamp to the event_dict if the log entry
    # is not from structlog.
    structlog.stdlib.add_log_level,
    # Add extra attributes of LogRecord objects to the event dictionary
    # so that values passed in the extra parameter of log methods pass
    # through to log output.
    structlog.stdlib.ExtraAdder(),
    timestamper,
]


@beartype
def configure(
    service_name: str = "pipemob",
    log_level: str = "DEBUG",
) -> None:
    """
    Configure structlog-based logger.

    Args:
        service_name: Name of the service for logging context
        log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    os.makedirs("./logs", exist_ok=True)
    log_level = log_level.upper()
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "module_filter": {
                    "()": ModuleFilter,
                    "modules_to_log": {service_name: log_level, "*": "INFO"},
                },
            },
            "formatters": {
                "plain": {
                    "()": structlog.stdlib.ProcessorFormatter,
                    "processors": [
                        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                        structlog.dev.ConsoleRenderer(colors=False),
                    ],
                    "foreign_pre_chain": pre_chain,
                },
                "colored": {
                    "()": structlog.stdlib.ProcessorFormatter,
                    "processors": [
                        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                        structlog.dev.ConsoleRenderer(colors=True),
                    ],
                    "foreign_pre_chain": pre_chain,
                },
            },
            "handlers": {
                "default": {
                    "level": log_level,
                    "class": "logging.StreamHandler",
                    "formatter": "colored",
                    "filters": ["module_filter"],
                },
                "file": {
                    "level": log_level,
                    "class": "logging.handlers.TimedRotatingFileHandler",
                    "filename": f"./logs/{service_name}.log",
                    "when": "midnight",
                    "interval": 1,
                    "backupCount": 30,
                    "formatter": "plain",
                    "filters": ["module_filter"],
                },
            },
            "loggers": {
                "": {
                    "handlers": ["default", "file"],
                    "level": log_level,
                    "propagate": True,
                },
            },
        }
    )
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            timestamper,
            structlog.processors.CallsiteParameterAdder(
                parameters=[
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                    structlog.processors.CallsiteParameter.LINENO,
                ]
            ),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    structlog.get_logger().debug("Logger initialized")
    return None


# Global logger instance
logger: structlog.stdlib.BoundLogger = structlog.get_logger()
