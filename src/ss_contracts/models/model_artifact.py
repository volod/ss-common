"""Contract model-artifact 1.0.0, generated from odcs/model-artifact.odcs.yaml; do not edit."""

from typing import ClassVar

from pydantic import Field

from ss_contracts.base import ContractModel, ContractRecord, ContractTimestamp


class ArtifactRef(ContractRecord):
    """The checkpoint an export was made from; unset for weights loaded from the hub or trained
    directly.
    """

    path: str = Field(
        description="POSIX path of the source file relative to the manifest directory; may climb out of it with leading ../ segments.",
        pattern="^(\\.\\./)*([^/\\\\.][^/\\\\]*/)*[^/\\\\.][^/\\\\]*$",
    )
    sha256: str = Field(
        description="SHA-256 of the source file.",
        pattern="^[0-9a-f]{64}$",
    )


class TrainingDataRef(ContractRecord):
    """Data the weights were trained on; unset for a plain export of hub weights."""

    kind: str = Field(
        description="Kind of training data: cvat_annotations (annotated frames in the database), cvat_xml (a CVAT export), or mission_frames (self-supervised frames of a mission).",
        pattern="^[a-z][a-z0-9_]*$",
    )
    ref: str = Field(
        description="Reference to the data: a mission id, a CVAT XML path, or the database selection.",
        min_length=1,
    )
    sample_count: int | None = Field(
        default=None,
        description="Annotated frames or training pairs used; unset when unknown.",
        ge=0,
        le=9223372036854775807,
    )


class Metric(ContractRecord):
    """One named metric value."""

    name: str = Field(
        description="Metric name in snake case (best_accuracy, distribution_shift, best_loss, onnx_max_abs_diff, ...).",
        pattern="^[a-z][a-z0-9_]*$",
    )
    value: float = Field(
        description="Metric value.",
    )


class ModelArtifact(ContractModel):
    """One trained or exported model file with its digest, base model, training data, and metrics:
    a fine-tuned PyTorch checkpoint or an ONNX export. ss-fusion publishes it next to the file;
    ss-video pins a version by artifact_id and sha256 before loading it.
    """

    CONTRACT_ID: ClassVar[str] = "model-artifact"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"

    artifact_id: str = Field(
        description="Artifact identifier: the model_checkpoints model_version_id, or the file stem for an export.",
        min_length=1,
    )
    format: str = Field(
        description="File format: pytorch (a torch.save state dict) or onnx.",
        pattern="^(pytorch|onnx)$",
    )
    path: str = Field(
        description="POSIX path of the model file relative to the directory holding the manifest; no absolute paths, backslashes, or segments starting with a dot.",
        pattern="^([^/\\\\.][^/\\\\]*/)*[^/\\\\.][^/\\\\]*$",
    )
    sha256: str = Field(
        description="SHA-256 of the model file, lowercase hex.",
        pattern="^[0-9a-f]{64}$",
    )
    size_bytes: int = Field(
        description="Model file size.",
        ge=0,
        le=9223372036854775807,
        json_schema_extra={
            "x-ss-binding": {
                "unit": "By",
            },
        },
    )
    base_model: str = Field(
        description="Hub name of the pretrained model the weights start from (dinov3_vitb14, dinov2_vits14, efficientvit_b1, ...).",
        min_length=1,
    )
    producer: str = Field(
        description="Code path that wrote the file, as a dotted module name.",
        min_length=1,
    )
    created_at: ContractTimestamp = Field(
        description="Time the file was written or registered.",
        json_schema_extra={
            "x-ss-binding": {
                "timeBase": "utc",
            },
        },
    )
    derived_from: ArtifactRef | None = Field(
        default=None,
        description="The checkpoint an export was made from; unset for weights loaded from the hub or trained directly.",
    )
    training_data: TrainingDataRef | None = Field(
        default=None,
        description="Data the weights were trained on; unset for a plain export of hub weights.",
    )
    metrics: list[Metric] = Field(
        description="Evaluation and training metrics the producer reported; empty when none.",
    )
    image_size: int | None = Field(
        default=None,
        description="Square input size the model expects; unset when not fixed.",
        ge=1,
        le=2147483647,
        json_schema_extra={
            "x-ss-binding": {
                "unit": "{pixel}",
            },
        },
    )
    opset: int | None = Field(
        default=None,
        description="ONNX opset version; ONNX files only.",
        ge=1,
        le=2147483647,
    )
    quantization: str | None = Field(
        default=None,
        description="Weight quantization (int8_static); unset for full-precision weights.",
        pattern="^[a-z0-9_]+$",
    )
