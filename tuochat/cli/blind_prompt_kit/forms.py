"""Linear forms and wizards built from reusable components."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Callable

from .core import Component, InteractionContext
from .exceptions import StepBack, StepSkip
from .models import SummaryField

Renderer = Callable[[Any], str]


@dataclass
class FormField:
    """One field in a form."""

    name: str
    component: Component[Any]
    label: str | None = None
    optional: bool = False
    renderer: Renderer | None = None

    def render(self, value: Any) -> str:
        """Render a field value for summaries."""
        if value is None or value == "":
            return "blank"
        if self.renderer is not None:
            return self.renderer(value)
        return str(value)


@dataclass
class SequentialForm:
    """Ask a list of fields in order and review the result."""

    title: str
    fields: Sequence[FormField]
    confirm: bool = True

    def run(self, context: InteractionContext) -> dict[str, Any]:
        """Run the form."""
        context.say(f"{self.title}. {len(self.fields)} fields.")
        values: dict[str, Any] = {}
        index = 0
        while True:
            while index < len(self.fields):
                field = self.fields[index]
                label = field.label or field.name.replace("_", " ").title()
                context.say(f"{index + 1} of {len(self.fields)}. {label}")
                try:
                    values[field.name] = field.component.run(context)
                except StepBack:
                    if index == 0:
                        context.fail("Already at the first field.")
                        continue
                    index -= 1
                    continue
                except StepSkip:
                    if not field.optional:
                        context.fail("This field cannot be blank.")
                        continue
                    values[field.name] = None
                index += 1
            if not self.confirm:
                return values
            while True:
                context.say(self.summary_text(values))
                if context.ask_yes_no("Confirm?", default=True):
                    return values
                choice = context.ask("Say change 2, change destination, or back.")
                text, command = context.parse_raw_input(choice)
                if command is not None and command.name == "change" and command.argument:
                    target = self.resolve_field(command.argument)
                    if target is None:
                        context.fail("Choose a listed field.")
                        continue
                    index = target
                    break
                if text.strip().lower() == "back":
                    index = max(len(self.fields) - 1, 0)
                    break
                context.fail("Say change and a field number or name.")

    def resolve_field(self, token: str) -> int | None:
        """Resolve a field by number or name."""
        stripped = token.strip()
        if stripped.isdigit():
            index = int(stripped) - 1
            if 0 <= index < len(self.fields):
                return index
            return None
        normalized = stripped.lower()
        for index, form_field in enumerate(self.fields):
            label = (form_field.label or form_field.name).lower()
            if normalized == label:
                return index
        return None

    def summary_text(self, values: dict[str, Any]) -> str:
        """Render a compact summary."""
        lines = ["Summary."]
        for form_field in self.fields:
            label = form_field.label or form_field.name.replace("_", " ").title()
            lines.append(
                SummaryField(name=label, value=values.get(form_field.name), renderer=form_field.renderer).render()
            )
        return "\n".join(lines)


@dataclass
class NonlinearForm:
    """Allow the user to jump between fields."""

    title: str
    fields: Sequence[FormField]

    def run(self, context: InteractionContext) -> dict[str, Any]:
        """Run the nonlinear form."""
        values: dict[str, Any] = {}
        while True:
            context.say(self.menu_text(values))
            raw = context.io.prompt(context.prompt_token)
            text, command = context.parse_raw_input(raw)
            if command is not None:
                if context.apply_common_command(command, status=lambda: self.menu_text(values)):
                    continue
                if command.name == "done":
                    return values
                if command.name == "field" and command.argument:
                    target = self.resolve_field(command.argument)
                    if target is None:
                        context.fail("Choose a listed field.")
                        continue
                    field = self.fields[target]
                    values[field.name] = field.component.run(context)
                    continue
            if text.strip().lower() == "done":
                return values
            target = self.resolve_field(text)
            if target is None:
                context.fail("Say a field number, field name, summary, or done.")
                continue
            field = self.fields[target]
            values[field.name] = field.component.run(context)

    def resolve_field(self, token: str) -> int | None:
        """Resolve a field by number or name."""
        stripped = token.strip()
        if stripped.isdigit():
            index = int(stripped) - 1
            if 0 <= index < len(self.fields):
                return index
            return None
        normalized = stripped.lower()
        for index, form_field in enumerate(self.fields):
            if normalized == (form_field.label or form_field.name).lower():
                return index
        return None

    def menu_text(self, values: dict[str, Any]) -> str:
        """Render the field menu."""
        lines = [f"{self.title}."]
        for index, form_field in enumerate(self.fields, start=1):
            label = form_field.label or form_field.name.replace("_", " ").title()
            lines.append(f"{index}. {label}: {form_field.render(values.get(form_field.name))}")
        lines.append("Say field number, field name, summary, or done.")
        return "\n".join(lines)


@dataclass
class WizardSection:
    """One section of a wizard."""

    title: str
    form: SequentialForm


@dataclass
class Wizard:
    """Group several sequential forms into checkpointed sections."""

    title: str
    sections: Sequence[WizardSection] = field(default_factory=list)

    def run(self, context: InteractionContext) -> dict[str, Any]:
        """Run each section in order."""
        context.say(self.title)
        result: dict[str, Any] = {}
        for section in self.sections:
            values = section.form.run(context)
            result.update(values)
            context.say(f"Section complete: {section.title}.")
            context.say(section.form.summary_text(values))
        return result
