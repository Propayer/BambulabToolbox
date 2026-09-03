"""Compatibility seam used by the existing MQTT command flow."""

from ..core.api import optimize_project


def optimize_project_from_mqtt(source, output, options, mqtt):
    return optimize_project(
        source, options, output,
        preview_callback=mqtt.publish_preview if options.preview else None,
    )
