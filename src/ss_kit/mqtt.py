"""MQTT client settings with TLS and mTLS, and the contract topic builder (`mqtt` extra).

Settings come from the environment under a service prefix (`COOP_MQTT_`, `MQTT_`, ...):

| Variable | Meaning |
| --- | --- |
| `<P>HOST`, `<P>PORT` | Broker address; the port defaults to 8883 with TLS, else 1883 |
| `<P>USER`, `<P>PASSWORD` | Username and password (optional) |
| `<P>CLIENT_ID` | Client identifier (optional) |
| `<P>TLS` | `true` enables TLS (system trust store unless a CA file is given) |
| `<P>TLS_CA_FILE` | PEM bundle that signs the broker certificate |
| `<P>TLS_CERT_FILE`, `<P>TLS_KEY_FILE` | Client certificate and key: set both for mTLS |
| `<P>TLS_KEY_PASSWORD` | Passphrase of an encrypted client key |
| `<P>TLS_INSECURE` | `true` skips the broker host-name check (the chain is still verified) |

`MqttSettings.client_kwargs()` returns keyword arguments for `aiomqtt.Client`, with a prepared
`ssl.SSLContext`, so the settings themselves import no MQTT library. `TopicBuilder` builds and
resolves `ss/v1/...` topics from the committed contract topic map.
"""

import os
import ssl
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from ss_contracts.topics import TopicEntry, TopicMap, committed_topic_map, topic_map_from_document
from ss_kit.env import env_bool, env_int, env_str
from ss_kit.settings import mask_secret

MQTT_PORT = 1883
MQTTS_PORT = 8883
DEFAULT_KEEPALIVE_SEC = 60
MIN_TLS_VERSION = ssl.TLSVersion.TLSv1_2


class MqttConfigError(ValueError):
    """The TLS configuration is incomplete or points at missing files."""


@dataclass(frozen=True)
class MqttTlsConfig:
    enabled: bool = False
    ca_file: str = ""
    cert_file: str = ""
    key_file: str = ""
    key_password: str = field(default="", repr=False)
    verify_hostname: bool = True

    @property
    def mutual(self) -> bool:
        """True when a client certificate is presented (mTLS)."""
        return bool(self.cert_file)

    @classmethod
    def from_env(cls, prefix: str) -> "MqttTlsConfig":
        return cls(
            enabled=env_bool(f"{prefix}TLS", False),
            ca_file=env_str(f"{prefix}TLS_CA_FILE", "").strip(),
            cert_file=env_str(f"{prefix}TLS_CERT_FILE", "").strip(),
            key_file=env_str(f"{prefix}TLS_KEY_FILE", "").strip(),
            key_password=env_str(f"{prefix}TLS_KEY_PASSWORD", ""),
            verify_hostname=not env_bool(f"{prefix}TLS_INSECURE", False),
        )

    def errors(self) -> list[str]:
        """Configuration findings; empty when the settings can build a context."""
        if not self.enabled:
            return []
        found: list[str] = []
        if bool(self.cert_file) != bool(self.key_file):
            found.append("mTLS needs both a client certificate and a key file")
        for label, value in (
            ("CA", self.ca_file),
            ("cert", self.cert_file),
            ("key", self.key_file),
        ):
            if value and not Path(value).is_file():
                found.append(f"TLS {label} file {value} does not exist")
        return found

    def ssl_context(self) -> ssl.SSLContext | None:
        """A client context (TLS 1.2 or newer, certificate required), or None when disabled."""
        if not self.enabled:
            return None
        problems = self.errors()
        if problems:
            raise MqttConfigError("; ".join(problems))
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=self.ca_file or None)
        context.minimum_version = MIN_TLS_VERSION
        context.check_hostname = self.verify_hostname
        if self.mutual:
            context.load_cert_chain(
                self.cert_file, self.key_file, password=self.key_password or None
            )
        return context


@dataclass(frozen=True)
class MqttSettings:
    host: str = "localhost"
    port: int = MQTT_PORT
    username: str = ""
    password: str = field(default="", repr=False)
    client_id: str = ""
    keepalive_sec: int = DEFAULT_KEEPALIVE_SEC
    tls: MqttTlsConfig = field(default_factory=MqttTlsConfig)

    @classmethod
    def from_env(cls, prefix: str = "MQTT_") -> "MqttSettings":
        tls = MqttTlsConfig.from_env(prefix)
        return cls(
            host=env_str(f"{prefix}HOST", "localhost"),
            port=env_int(f"{prefix}PORT", MQTTS_PORT if tls.enabled else MQTT_PORT),
            username=env_str(f"{prefix}USER", ""),
            password=env_str(f"{prefix}PASSWORD", ""),
            client_id=env_str(f"{prefix}CLIENT_ID", ""),
            keepalive_sec=env_int(f"{prefix}KEEPALIVE_SEC", DEFAULT_KEEPALIVE_SEC),
            tls=tls,
        )

    def with_tls(self, tls: MqttTlsConfig) -> "MqttSettings":
        return replace(self, tls=tls)

    def client_kwargs(self) -> dict[str, Any]:
        """Keyword arguments for `aiomqtt.Client(**kwargs)`."""
        kwargs: dict[str, Any] = {
            "hostname": self.host,
            "port": self.port,
            "username": self.username or None,
            "password": self.password or None,
            "keepalive": self.keepalive_sec,
        }
        context = self.tls.ssl_context()
        if context is not None:
            kwargs["tls_context"] = context
        if self.client_id:
            kwargs["identifier"] = self.client_id
        return kwargs

    def describe(self) -> str:
        """One log-safe line: broker, user, and TLS mode (never the password)."""
        mode = "off"
        if self.tls.enabled:
            mode = "mtls" if self.tls.mutual else "tls"
        user = self.username or "-"
        return (
            f"{self.host}:{self.port} user={user} password={mask_secret(self.password)} tls={mode}"
        )


class TopicBuilder:
    """Build and resolve contract topics (`contract id` -> concrete `ss/v1/...` topic)."""

    def __init__(self, topic_map: TopicMap | None = None) -> None:
        self.topic_map = topic_map if topic_map is not None else committed_topic_map()

    @classmethod
    def from_yaml(cls, path: str | os.PathLike[str]) -> "TopicBuilder":
        """A builder over another `topics.yaml` (for example a site override)."""
        import yaml

        source = Path(path)
        doc = yaml.safe_load(source.read_text(encoding="utf-8"))
        return cls(topic_map_from_document(doc, source))

    def entry(self, contract_id: str) -> TopicEntry:
        """The single topic entry of a contract; `KeyError` when unmapped or ambiguous."""
        entries = self.topic_map.for_contract(contract_id)
        if len(entries) != 1:
            raise KeyError(f"contract '{contract_id}' has {len(entries)} topics, expected one")
        return entries[0]

    def build(self, contract_id: str, **params: str) -> str:
        return self.entry(contract_id).build(**params)

    def subscription(self, contract_id: str) -> str:
        """The `+`-wildcard filter that subscribes to every topic of a contract."""
        return self.entry(contract_id).subscription()

    def resolve(self, topic: str) -> tuple[str, dict[str, str]] | None:
        """(contract id, placeholder values) for a concrete topic, or None."""
        found = self.topic_map.resolve(topic)
        if found is None:
            return None
        entry, params = found
        return entry.contract, params
