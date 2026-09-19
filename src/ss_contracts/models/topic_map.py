"""Generated from contracts/topics.yaml; do not edit. Regenerate with `make contracts-gen`."""

TOPICS_VERSION = 1

# (pattern, contract, qos, retain)
TOPICS: tuple[tuple[str, str, int, bool], ...] = (
    ("ss/v1/site/{site_id}/sensor/{dev_eui}/reading", "sensor-reading", 1, False),
    ("ss/v1/site/{site_id}/sensor/{dev_eui}/state", "sensor-state", 1, True),
    ("ss/v1/site/{site_id}/camera/{camera}/event", "camera-event", 1, False),
    ("ss/v1/site/{site_id}/camera/{camera}/acoustic", "acoustic-observation", 1, False),
    ("ss/v1/site/{site_id}/node/{node_id}/sensor-event", "sensor-event", 1, False),
    ("ss/v1/site/{site_id}/sector/{sector_id}/threat", "threat-event", 1, False),
    ("ss/v1/site/{site_id}/zone/{zone_id}/event/{modality}", "event-envelope", 1, False),
    ("ss/v1/site/{site_id}/mission/{mission_id}/scene-caption", "scene-caption", 1, False),
)
