from noetrium_platform.capabilities.environment.embodied.api import SensorSpec

def test_sensor_contract_accepts_open_modality_identifiers() -> None:
    sensor = SensorSpec(
        "minecraft-observation",
        "minecraft/voxel-observation",
        "world",
        "json",
        metadata={"schema": "paper.observation.v3"},
    )
    assert sensor.record()["modality"] == "minecraft/voxel-observation"
