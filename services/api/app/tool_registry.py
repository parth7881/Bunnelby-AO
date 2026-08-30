from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Final, Mapping


ToolExecutor = Callable[[str, Mapping[str, object]], object]


@dataclass(frozen=True)
class ToolSpec:
    """Typed metadata for one Bunnelby tool exposed to the planner/executor."""

    name: str
    description: str
    risk_level: str
    requires_approval: bool
    executor: ToolExecutor


class ToolRegistryError(RuntimeError):
    """Raised when a tool cannot be registered or resolved safely."""


class ToolRegistry:
    """Small in-process registry that keeps orchestration independent from tool modules."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        name = spec.name.strip()
        if not name:
            raise ToolRegistryError("Tool name cannot be empty.")
        if name in self._tools:
            raise ToolRegistryError(f"Tool is already registered: {name}")
        self._tools[name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolRegistryError(f"Unknown Bunnelby tool: {name}") from exc

    def execute(
        self,
        name: str,
        instruction: str,
        context: Mapping[str, object] | None = None,
    ) -> object:
        spec = self.get(name)
        return spec.executor(instruction, context or {})

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def metadata(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "name": spec.name,
                "description": spec.description,
                "risk_level": spec.risk_level,
                "requires_approval": spec.requires_approval,
            }
            for spec in self._tools.values()
        )


READ_TOOL_NAMES: Final[tuple[str, ...]] = ("gmail.read", "calendar.read")
