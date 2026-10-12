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
        self._environment = Environment(
            loader=FileSystemLoader(prompt_dir),
            autoescape=False,
            undefined=StrictUndefined,
            keep_trailing_newline=True,
        )

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
            return self._environment.get_template(f"{target}/{agent_name}/{message_type}.jinja")
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
        template = self._template(agent_name, target, message_type)
        try:
            return template.render(dict(values)).strip()
        except TemplateError as exc:
            raise PromptTemplateError(
                f"Could not render prompt template '{template.name}': {exc}."
            ) from exc
