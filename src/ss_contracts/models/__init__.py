"""Generated contract models; do not edit. Regenerate with `make contracts-gen`."""

from ss_contracts.base import ContractModel

from .acoustic_observation import AcousticObservation
from .camera_event import CameraEvent
from .event_envelope import EventEnvelope
from .mission_bundle import MissionBundle
from .model_artifact import ModelArtifact
from .scene_caption import SceneCaption
from .sensor_event import SensorEvent
from .sensor_reading import SensorReading
from .sensor_state import SensorState
from .threat_event import ThreatEvent

CONTRACTS: dict[str, type[ContractModel]] = {
    "acoustic-observation": AcousticObservation,
    "camera-event": CameraEvent,
    "event-envelope": EventEnvelope,
    "mission-bundle": MissionBundle,
    "model-artifact": ModelArtifact,
    "scene-caption": SceneCaption,
    "sensor-event": SensorEvent,
    "sensor-reading": SensorReading,
    "sensor-state": SensorState,
    "threat-event": ThreatEvent,
}

__all__ = [
    "CONTRACTS",
    "AcousticObservation",
    "CameraEvent",
    "ContractModel",
    "EventEnvelope",
    "MissionBundle",
    "ModelArtifact",
    "SceneCaption",
    "SensorEvent",
    "SensorReading",
    "SensorState",
    "ThreatEvent",
]
