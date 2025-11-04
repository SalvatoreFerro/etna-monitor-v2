import asyncio
from types import SimpleNamespace

import pytest

import worker_telegram_bot as worker


class DummyMessage:
    def __init__(self):
        self.messages: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.messages.append(text)


class DummyUpdate(SimpleNamespace):
    def __init__(self, chat_id: int):
        super().__init__(
            effective_chat=SimpleNamespace(id=chat_id),
            message=DummyMessage(),
        )


def test_cmd_start_replies_with_greeting():
    update = DummyUpdate(chat_id=123)
    asyncio.run(worker.cmd_start(update, None))
    assert update.message.messages == ["Ciao! Sono Etna Bot 👋"]


def test_cmd_help_lists_commands():
    update = DummyUpdate(chat_id=456)
    asyncio.run(worker.cmd_help(update, None))
    assert update.message.messages == ["Comandi disponibili: /start /help"]


def test_main_requires_token(monkeypatch):
    monkeypatch.delenv(worker.TOKEN_ENV, raising=False)

    async def run_main():
        await worker.main()

    with pytest.raises(RuntimeError):
        asyncio.run(run_main())

    monkeypatch.setenv(worker.TOKEN_ENV, "test-token")
