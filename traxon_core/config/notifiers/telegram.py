from dataclasses import dataclass


@dataclass
class TelegramConfig:
    enabled: bool
    bot_token: str
    chat_id: str
    rate_limit_seconds: int
    max_messages_per_minute: int
