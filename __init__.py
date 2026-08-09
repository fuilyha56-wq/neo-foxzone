"""Neo FoxZone 插件公共常量。"""

PLUGIN_NAME = "neo-foxzone"
BACKEND_SERVICE_SIGNATURE = "onebot_expand:service:qzone_service"
SERVICE_NAME = "neo_foxzone_service"
SERVICE_SIGNATURE = f"{PLUGIN_NAME}:service:{SERVICE_NAME}"

__all__ = [
    "BACKEND_SERVICE_SIGNATURE",
    "PLUGIN_NAME",
    "SERVICE_NAME",
    "SERVICE_SIGNATURE",
]