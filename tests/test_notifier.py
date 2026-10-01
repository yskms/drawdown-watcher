from unittest.mock import patch

import pandas as pd
import pytest

from src.notifier import NotifierConfigError, notify_error, notify_event, notify_heartbeat


def _set_smtp_env(monkeypatch, **overrides):
    env = {
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "587",
        "SMTP_USERNAME": "user@example.com",
        "SMTP_PASSWORD": "secret",
        "NOTIFICATION_EMAIL_FROM": "watcher@example.com",
        "NOTIFICATION_EMAIL_TO": "me@example.com",
    }
    env.update(overrides)
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)


@patch("src.notifier.smtplib.SMTP")
def test_notify_event_sends_email_with_ticker_and_event_details(mock_smtp, monkeypatch):
    _set_smtp_env(monkeypatch)
    smtp_instance = mock_smtp.return_value.__enter__.return_value

    event = {
        "date": pd.Timestamp("2026-03-01"),
        "event": "DRAWDOWN_MODE_ENTER",
        "close": 73.0,
        "reference_high": 100.0,
        "drawdown_pct": -27.0,
        "streak_trading_days": 2,
    }
    notify_event("SPXL", event)

    mock_smtp.assert_called_once_with("smtp.example.com", 587)
    smtp_instance.starttls.assert_called_once()
    smtp_instance.login.assert_called_once_with("user@example.com", "secret")
    sent = smtp_instance.send_message.call_args[0][0]
    assert sent["To"] == "me@example.com"
    assert "SPXL" in sent["Subject"]
    assert "DRAWDOWN_MODE_ENTER" in sent["Subject"]
    assert "DRAWDOWN MODE ENTER" in sent.get_content()


@patch("src.notifier.smtplib.SMTP")
def test_notify_error_sends_email(mock_smtp, monkeypatch):
    _set_smtp_env(monkeypatch)
    smtp_instance = mock_smtp.return_value.__enter__.return_value

    notify_error("VOO", "fetch failed")

    sent = smtp_instance.send_message.call_args[0][0]
    assert "ERROR" in sent["Subject"]
    assert "VOO" in sent["Subject"]
    assert "fetch failed" in sent.get_content()


@patch("src.notifier.smtplib.SMTP")
def test_notify_heartbeat_joins_status_lines(mock_smtp, monkeypatch):
    _set_smtp_env(monkeypatch)
    smtp_instance = mock_smtp.return_value.__enter__.return_value

    notify_heartbeat(["SPXL: NORMAL", "VOO: NORMAL"])

    sent = smtp_instance.send_message.call_args[0][0]
    assert "SPXL: NORMAL" in sent.get_content()
    assert "VOO: NORMAL" in sent.get_content()


@patch("src.notifier.smtplib.SMTP")
def test_no_login_when_username_not_set(mock_smtp, monkeypatch):
    _set_smtp_env(monkeypatch, SMTP_USERNAME=None, SMTP_PASSWORD=None)
    smtp_instance = mock_smtp.return_value.__enter__.return_value

    notify_error(None, "boom")

    smtp_instance.login.assert_not_called()


def test_missing_smtp_host_raises(monkeypatch):
    _set_smtp_env(monkeypatch, SMTP_HOST=None)

    with pytest.raises(NotifierConfigError):
        notify_error(None, "boom")


def test_missing_to_address_raises(monkeypatch):
    _set_smtp_env(monkeypatch, NOTIFICATION_EMAIL_TO=None)

    with pytest.raises(NotifierConfigError):
        notify_error(None, "boom")


def test_missing_from_address_raises(monkeypatch):
    _set_smtp_env(monkeypatch, NOTIFICATION_EMAIL_FROM=None, SMTP_USERNAME=None)

    with pytest.raises(NotifierConfigError):
        notify_error(None, "boom")
