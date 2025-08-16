from alerts.notifier import send_telegram_alert

def test_send_telegram_alert_mock():
    assert send_telegram_alert("token", "123", "ciao") is True
    assert send_telegram_alert("", "123", "ciao") is False
    assert send_telegram_alert("token", "", "ciao") is False
