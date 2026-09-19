"""Runtime base class of the generated contract models.

Generated models under `ss_contracts.models` subclass `ContractModel`. The configuration is part
of the evolution policy: an added optional field is a minor (backward-compatible) change, so a
consumer built against an older version must accept messages carrying fields it does not know.
Unknown fields are therefore ignored instead of rejected.
"""

import base64
from typing import Annotated, ClassVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, PlainSerializer, WithJsonSchema


def _standard_base64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


# Bytes as standard (RFC 4648 section 4) base64 in JSON, the alphabet the Protobuf JSON mapping
# emits; Pydantic's own `ser_json_bytes="base64"` writes the URL-safe alphabet. Decoding accepts
# both alphabets.
ContractBytes = Annotated[
    bytes,
    PlainSerializer(_standard_base64, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "contentEncoding": "base64"}),
]

# RFC 3339 timestamp with an explicit offset. The JSON Schema spells the offset requirement as a
# pattern because `format: date-time` is only an annotation for most validators.
TIMESTAMP_PATTERN = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$"
)
ContractTimestamp = Annotated[
    AwareDatetime,
    WithJsonSchema({"type": "string", "format": "date-time", "pattern": TIMESTAMP_PATTERN}),
]


class ContractModel(BaseModel):
    """A message whose shape is defined by a registered ODCS contract."""

    model_config = ConfigDict(
        extra="ignore",
        # Bytes cross JSON as base64 (see ContractBytes for the output alphabet).
        ser_json_bytes="base64",
        val_json_bytes="base64",
    )

    CONTRACT_ID: ClassVar[str] = ""
    CONTRACT_VERSION: ClassVar[str] = ""
    # Contract-level ssBinding (time base, frame, unit, modality, MQTT topic); field-level
    # bindings live in each field's JSON Schema under "x-ss-binding".
    SS_BINDING: ClassVar[dict[str, str]] = {}
