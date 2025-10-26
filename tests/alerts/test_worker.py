from __future__ import annotations

from pathlib import Path

import worker_telegram_bot as worker


def _write_curva(path: Path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("timestamp,value\n")
        for idx, value in enumerate(values):
            handle.write(f"2024-01-01T00:{idx:02d}:00,{value}\n")


def test_run_alert_cycle_triggers_and_logs(tmp_path, monkeypatch):
    data_file = tmp_path / "curva.csv"
    log_file = tmp_path / "alerts.csv"
    _write_curva(data_file, [1.0, 3.0, 4.0, 5.0])

    sent = []

    def fake_send(token, chat_id, text, **kwargs):  # noqa: ANN001
        sent.append((token, chat_id, text))
        return True

    monkeypatch.setattr(worker, "send_telegram_alert", fake_send)

    success = worker.run_alert_cycle(
        bot_token="token",
        chat_ids=["123"],
        data_file=data_file,
        window=3,
        threshold=3.0,
        log_file=log_file,
    )

    assert success is True
    assert sent

    contents = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert contents[0].startswith("timestamp,event,chat_id")
    assert any("alert_sent" in line for line in contents[1:])


def test_run_alert_cycle_no_trigger(tmp_path, monkeypatch):
    data_file = tmp_path / "curva.csv"
    log_file = tmp_path / "alerts.csv"
    _write_curva(data_file, [1.0, 1.1, 1.2])

    monkeypatch.setattr(worker, "send_telegram_alert", lambda *args, **kwargs: True)

    success = worker.run_alert_cycle(
        bot_token="token",
        chat_ids=["123"],
        data_file=data_file,
        window=3,
        threshold=5.0,
        log_file=log_file,
    )

    assert success is False
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert any("no_alert" in line for line in lines[1:])


def test_run_alert_cycle_missing_chat_ids(tmp_path):
    data_file = tmp_path / "curva.csv"
    log_file = tmp_path / "alerts.csv"
    _write_curva(data_file, [4.0, 5.0, 6.0])

    success = worker.run_alert_cycle(
        bot_token="token",
        chat_ids=[],
        data_file=data_file,
        window=2,
        threshold=1.0,
        log_file=log_file,
    )

    assert success is False
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert any("missing_chat_ids" in line for line in lines[1:])
