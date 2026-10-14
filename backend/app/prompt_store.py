from __future__ import annotations

from typing import TYPE_CHECKING

from jinja2 import (
    Environment,
    FileSystemLoader,
    StrictUndefined,
    Template,
    TemplateError,
    TemplateNotFound,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


class PromptTemplateError(ValueError):
    """Raised when a configured agent prompt template cannot be used."""


class PromptStore:
    """Loads trusted agent prompt templates from one dedicated directory."""

    def __init__(self, prompt_dir: Path) -> None:
        self._prompt_dir = prompt_dir
        self._system_overrides: dict[tuple[str, str], str] = {}
        self._sources: dict[tuple[str, str], str] = {}
        self._environment = Environment(
            loader=FileSystemLoader(prompt_dir),
            autoescape=False,
            undefined=StrictUndefined,
            keep_trailing_newline=True,
        )

    def set_system_override(self, agent_name: str, target: str, prompt: str | None) -> None:
        """Set or remove an agent's application-level system prompt override."""
        key = (target, agent_name)
        if prompt is None:
            self._system_overrides.pop(key, None)
        else:
            self._system_overrides[key] = prompt

    def set_source(self, agent_name: str, target: str, source_name: str | None) -> None:
        """Set or remove the built-in prompt profile used by an agent."""
        key = (target, agent_name)
        if source_name is None:
            self._sources.pop(key, None)
        else:
            self._sources[key] = source_name

    def clear_overrides(self) -> None:
        """Clear prompt overrides and source mappings before reloading settings."""
        self._system_overrides.clear()
        self._sources.clear()

    def system_prompt(self, agent_name: str, target: str) -> str:
        """Render the system prompt for an agent without request-specific values."""
        return self._render(agent_name, target, "system", {})

    def validate(self, agent_name: str, target: str) -> None:
        self._template(agent_name, target, "system")
        self._template(agent_name, target, "user")

    def validate_messages(self, agent_name: str, target: str, purpose: str) -> None:
        self._template(agent_name, target, f"{purpose}_system")
        self._template(agent_name, target, f"{purpose}_user")

    def render_messages(
        self, agent_name: str, target: str, values: Mapping[str, object]
    ) -> tuple[str, str]:
        return (
            self._render(agent_name, target, "system", values),
            self._render(agent_name, target, "user", values),
        )

    def render_messages_for(
        self, agent_name: str, target: str, purpose: str, values: Mapping[str, object]
    ) -> tuple[str, str]:
        return (
            self._render(agent_name, target, f"{purpose}_system", values),
            self._render(agent_name, target, f"{purpose}_user", values),
        )

    def _template(self, agent_name: str, target: str, message_type: str) -> Template:
        try:
            source_name = self._sources.get((target, agent_name), agent_name)
            return self._environment.get_template(f"{target}/{source_name}/{message_type}.jinja")
        except TemplateNotFound as exc:
            raise PromptTemplateError(
                f"No {message_type} prompt was found for agent_name '{agent_name}' "
                f"in {self._prompt_dir}."
            ) from exc
        except TemplateError as exc:
            raise PromptTemplateError(
                f"Prompt template '{target}/{agent_name}/{message_type}.jinja' is invalid: {exc}."
            ) from exc

    def _render(
        self, agent_name: str, target: str, message_type: str, values: Mapping[str, object]
    ) -> str:
        if message_type == "system":
            override = self._system_overrides.get((target, agent_name))
            if override is not None:
                return override.strip()
        template = self._template(agent_name, target, message_type)
        try:
            return template.render(dict(values)).strip()
        except TemplateError as exc:
            raise PromptTemplateError(
                f"Could not render prompt template '{template.name}': {exc}."
            ) from exc
