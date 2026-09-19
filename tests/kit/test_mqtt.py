import ssl
from pathlib import Path

import pytest

from ss_contracts.topics import committed_topic_map
from ss_kit.mqtt import (
    MQTT_PORT,
    MQTTS_PORT,
    MqttConfigError,
    MqttSettings,
    MqttTlsConfig,
    TopicBuilder,
)

READING = "sensor-reading"
READING_TOPIC = "ss/v1/site/alpha/sensor/deadbeef/reading"


def test_settings_from_env_default_port_follows_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COOP_MQTT_HOST", "broker.example")
    monkeypatch.setenv("COOP_MQTT_USER", "mesh")
    monkeypatch.setenv("COOP_MQTT_PASSWORD", "secret-pass")
    monkeypatch.setenv("COOP_MQTT_CLIENT_ID", "ss-sens-1")
    monkeypatch.setenv("COOP_MQTT_TLS", "true")
    monkeypatch.delenv("COOP_MQTT_PORT", raising=False)

    settings = MqttSettings.from_env("COOP_MQTT_")

    assert settings.host == "broker.example"
    assert settings.port == MQTTS_PORT
    assert settings.tls.enabled
    assert "secret-pass" not in settings.describe()
    assert "tls=tls" in settings.describe()
    kwargs = settings.client_kwargs()
    assert kwargs["hostname"] == "broker.example"
    assert kwargs["identifier"] == "ss-sens-1"
    assert kwargs["username"] == "mesh"
    assert isinstance(kwargs["tls_context"], ssl.SSLContext)
    assert kwargs["tls_context"].minimum_version is ssl.TLSVersion.TLSv1_2


def test_settings_without_tls_omit_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MQTT_HOST", "localhost")
    monkeypatch.setenv("MQTT_TLS", "false")
    monkeypatch.delenv("MQTT_PORT", raising=False)
    settings = MqttSettings.from_env()
    assert settings.port == MQTT_PORT
    assert "tls_context" not in settings.client_kwargs()
    assert settings.tls.ssl_context() is None


def test_mtls_needs_both_files_and_existing_paths(tmp_path: Path) -> None:
    missing = tmp_path / "gone.pem"
    only_cert = MqttTlsConfig(enabled=True, cert_file=str(tmp_path / "client.pem"))
    assert "mTLS needs both a client certificate and a key file" in only_cert.errors()
    with pytest.raises(MqttConfigError, match="mTLS"):
        only_cert.ssl_context()

    present = tmp_path / "ca.pem"
    present.write_text("not a cert", encoding="utf-8")
    broken = MqttTlsConfig(enabled=True, ca_file=str(missing))
    assert any("does not exist" in item for item in broken.errors())
    insecure = MqttTlsConfig(enabled=True, verify_hostname=False)
    context = insecure.ssl_context()
    assert context is not None
    assert context.check_hostname is False


def test_topic_builder_round_trip() -> None:
    builder = TopicBuilder()
    topic = builder.build(READING, site_id="alpha", dev_eui="deadbeef")
    assert topic == READING_TOPIC
    assert builder.subscription(READING) == "ss/v1/site/+/sensor/+/reading"
    assert builder.resolve(topic) == (READING, {"site_id": "alpha", "dev_eui": "deadbeef"})
    assert builder.resolve("ss/v1/unknown") is None
    with pytest.raises(KeyError, match="mission-bundle"):
        builder.entry("mission-bundle")
    with pytest.raises(ValueError, match="missing"):
        builder.build(READING, site_id="alpha")
    with pytest.raises(ValueError, match="not a single topic level"):
        builder.build(READING, site_id="a/b", dev_eui="deadbeef")


def test_topic_builder_from_yaml(tmp_path: Path) -> None:
    source = tmp_path / "topics.yaml"
    source.write_text(
        "topicsVersion: 1\n"
        "topics:\n"
        "  - pattern: ss/v1/x/{id}\n"
        "    contract: sample\n"
        "    qos: 0\n"
        "    retain: false\n",
        encoding="utf-8",
    )
    builder = TopicBuilder.from_yaml(source)
    assert builder.build("sample", id="n1") == "ss/v1/x/n1"
    assert committed_topic_map().for_contract(READING)


def test_password_is_not_in_repr() -> None:
    settings = MqttSettings(password="super-secret", tls=MqttTlsConfig(key_password="kpass"))
    assert "super-secret" not in repr(settings)
    assert "kpass" not in repr(settings)
