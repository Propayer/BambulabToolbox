from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from contextlib import AbstractContextManager


class MqttStatus(AbstractContextManager):
    def __init__(self, config: dict):
        self.config = config
        self.client = None
        self.base = str(config.get("base_topic", "jarvis/bambu_analyzer")).rstrip("/")

    def __enter__(self):
        if not self.config.get("enabled", False):
            return self
        import paho.mqtt.client as mqtt

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        username = str(self.config.get("username", ""))
        password = os.getenv("JARVIS_MQTT_PASSWORD", str(self.config.get("password", "")))
        if username:
            self.client.username_pw_set(username, password)
        self.client.connect(str(self.config["host"]), int(self.config.get("port", 1883)))
        self.client.loop_start()
        self._publish_discovery()
        return self

    def _publish_discovery(self) -> None:
        prefix = str(self.config.get("discovery_prefix", "homeassistant")).rstrip("/")
        device = {
            "identifiers": ["jarvis_bambu_analyzer"],
            "name": "Analizador Bambu de Jarvis",
            "manufacturer": "Proyecto JARVIS",
            "model": "Bambu Analyzer",
        }
        entities = {
            "status": "Estado del analizador Bambu",
            "current_piece": "Pieza actual del analizador Bambu",
            "result": "Resultado del analizador Bambu",
            "workbook": "Excel del analizador Bambu",
            "preview_info": "Información de preview del optimizador Bambu",
            "optimizer_run_config": "Configuración activa del optimizador Bambu",
        }
        for object_id, name in entities.items():
            payload = {
                "name": name,
                "unique_id": f"jarvis_bambu_{object_id}",
                "state_topic": f"{self.base}/{object_id}",
                "device": device,
            }
            self.client.publish(
                f"{prefix}/sensor/jarvis_bambu/{object_id}/config",
                json.dumps(payload, ensure_ascii=False),
                retain=True,
            )
        camera_payload = {
            "name": "Preview del optimizador Bambu",
            "unique_id": "jarvis_bambu_optimizer_preview",
            "default_entity_id": "camera.jarvis_preview_optimizador",
            "topic": f"{self.base}/optimizer_preview/image",
            "encoding": "",
            "device": device,
        }
        self.client.publish(
            f"{prefix}/camera/jarvis_bambu/optimizer_preview/config",
            json.dumps(camera_payload, ensure_ascii=False),
            retain=True,
        )

    def publish(self, key: str, value: str, retain: bool = True) -> None:
        if self.client:
            self.client.publish(f"{self.base}/{key}", value, retain=retain)

    def publish_preview(self, image_path: Path, payload: dict) -> None:
        if not self.client:
            return
        self.client.publish(
            f"{self.base}/optimizer_preview/image",
            image_path.read_bytes(),
            qos=1,
            retain=True,
        )
        self.publish("preview_info", json.dumps(payload, ensure_ascii=False))

    def read_retained(self, key: str, default: str, timeout: float = 1.5) -> str:
        if not self.client:
            return default
        topic = f"{self.base}/{key}"
        received = threading.Event()
        result = {"value": default}

        def on_message(client, userdata, message):
            try:
                result["value"] = message.payload.decode("utf-8").strip() or default
            finally:
                received.set()

        self.client.message_callback_add(topic, on_message)
        try:
            self.client.subscribe(topic)
            received.wait(timeout)
        finally:
            self.client.unsubscribe(topic)
            self.client.message_callback_remove(topic)
        return result["value"]

    def __exit__(self, exc_type, exc, traceback):
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
        return False
