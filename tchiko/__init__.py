"""Tchiko Assistant — Autonomous Linux Systems Engineer & Parametric Cairo Desktop Companion.

Public Package Exports:
- `ConfigManager`: Thread-safe RBAC permission store and `antigravity.yaml` synchronizer.
- `LinuxSystemToolkit` & `ToolResult`: Host execution layer (`/proc` telemetry, file view/grep/patch, Crash Doctor).
- `TchikoAgentEngine`: 5-Tier autonomous dispatch engine, `agy` NDJSON stream bridge & 8-step ReAct loop.
- `SvgGhostRenderer`: 60 FPS procedural Cairo cubic Bézier vector & Hooke's law spring-jelly physics engine.
"""

from __future__ import annotations

from .agent_engine import TchikoAgentEngine
from .config_manager import ConfigManager, PROJECT_ROOT
from .system_tools import LinuxSystemToolkit, ToolResult

__version__ = "2.0.0"
__app_name__ = "Tchiko Assistant"

__all__ = [
    "__app_name__",
    "__version__",
    "ConfigManager",
    "EMOTION_LIST",
    "LinuxSystemToolkit",
    "PROJECT_ROOT",
    "SvgGhostRenderer",
    "THEMES",
    "TchikoAgentEngine",
    "ToolResult",
]

# The Cairo renderer is loaded lazily so headless servers (`main.py --remote`, the container
# image) can import the package without pycairo installed.
_LAZY_RENDERER_EXPORTS = ("EMOTION_LIST", "SvgGhostRenderer", "THEMES")


def __getattr__(name: str):
    if name in _LAZY_RENDERER_EXPORTS:
        from . import svg_ghost_renderer

        return getattr(svg_ghost_renderer, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
