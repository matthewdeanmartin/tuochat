"""Numeric and boolean prompt components."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .commands import parse_yes_no
from .core import InteractionContext
from .models import NumberRange


def render_decimal(value: Decimal) -> str:
    """Render a decimal without scientific notation."""
    normalized = value.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".") or "0"
    return text


@dataclass
class IntegerInput:
    """Prompt for an integer."""

    prompt: str
    minimum: int | None = None
    maximum: int | None = None
    default: int | None = None
    help_text: str | None = None

    def run(self, context: InteractionContext) -> int:
        """Collect an integer."""
        while True:
            raw = context.ask(self.prompt, help_text=self.help_text)
            text, command = context.parse_raw_input(raw)
            if command is not None and context.apply_common_command(command, help_text=self.help_text):
                continue
            if not text.strip() and self.default is not None:
                return self.default
            try:
                value = int(text.strip())
            except ValueError:
                context.fail(self.range_error_message())
                continue
            if self.minimum is not None and value < self.minimum:
                context.fail(self.range_error_message())
                continue
            if self.maximum is not None and value > self.maximum:
                context.fail(self.range_error_message())
                continue
            return value

    def range_error_message(self) -> str:
        """Render the validation message."""
        if self.minimum is not None and self.maximum is not None:
            return f"Enter a whole number from {self.minimum} to {self.maximum}."
        if self.minimum is not None:
            return f"Enter a whole number of at least {self.minimum}."
        if self.maximum is not None:
            return f"Enter a whole number no greater than {self.maximum}."
        return "Enter a whole number."


@dataclass
class DecimalInput:
    """Prompt for a decimal value."""

    prompt: str
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    default: Decimal | None = None
    help_text: str | None = None
    normalize_output: bool = False

    def run(self, context: InteractionContext) -> Decimal:
        """Collect a decimal."""
        while True:
            raw = context.ask(self.prompt, help_text=self.help_text)
            text, command = context.parse_raw_input(raw)
            if command is not None and context.apply_common_command(command, help_text=self.help_text):
                continue
            stripped = text.strip()
            if not stripped and self.default is not None:
                return self.default
            try:
                value = Decimal(stripped)
            except InvalidOperation:
                context.fail(self.range_error_message())
                continue
            if self.minimum is not None and value < self.minimum:
                context.fail(self.range_error_message())
                continue
            if self.maximum is not None and value > self.maximum:
                context.fail(self.range_error_message())
                continue
            if self.normalize_output:
                context.say(f"{self.prompt.rstrip('?')}: {value:.2f}")
            return value

    def range_error_message(self) -> str:
        """Render the validation message."""
        if self.minimum is not None and self.maximum is not None:
            return f"Enter a number from {render_decimal(self.minimum)} to {render_decimal(self.maximum)}."
        if self.minimum is not None:
            return f"Enter a number of at least {render_decimal(self.minimum)}."
        if self.maximum is not None:
            return f"Enter a number no greater than {render_decimal(self.maximum)}."
        return "Enter a number."


@dataclass
class YesNoInput:
    """Prompt for a yes/no answer."""

    prompt: str
    default: bool | None = None
    help_text: str | None = None

    def run(self, context: InteractionContext) -> bool:
        """Collect a yes/no answer."""
        while True:
            raw = context.ask(self.prompt, help_text=self.help_text, hint=self.hint())
            text, command = context.parse_raw_input(raw)
            if command is not None and context.apply_common_command(command, help_text=self.help_text):
                continue
            answer = parse_yes_no(text)
            if answer is not None:
                return answer
            if not text.strip() and self.default is not None:
                return self.default
            context.fail("Answer yes or no.")

    def hint(self) -> str:
        """Render the answer hint."""
        if self.default is None:
            return "Yes or no."
        if self.default:
            return "Yes or no. Default yes."
        return "Yes or no. Default no."


@dataclass
class NumberRangeInput:
    """Prompt for a numeric range."""

    prompt: str
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    help_text: str | None = None

    def run(self, context: InteractionContext) -> NumberRange:
        """Collect a numeric range."""
        while True:
            raw = context.ask(
                self.prompt,
                hint="Enter both bounds like 10 to 25, under 50, or type step.",
                help_text=self.help_text,
            )
            text, command = context.parse_raw_input(raw)
            if command is not None and context.apply_common_command(command, help_text=self.help_text):
                continue
            if text.strip().lower() == "step":
                return self.run_step_mode(context)
            parsed = self.parse_direct(text)
            if parsed is None:
                context.fail("Enter a range like 10 to 25, under 50, or at least 20.")
                continue
            if self.is_valid(parsed):
                context.say(f"Range: {parsed.render()}")
                return parsed
            context.fail("Maximum must be greater than or equal to minimum.")

    def run_step_mode(self, context: InteractionContext) -> NumberRange:
        """Collect a range step by step."""
        minimum_prompt = DecimalInput("Minimum?", minimum=self.minimum)
        maximum_prompt = DecimalInput("Maximum?", maximum=self.maximum)
        lower = minimum_prompt.run(context)
        while True:
            upper = maximum_prompt.run(context)
            result = NumberRange(lower, upper)
            if self.is_valid(result):
                context.say(f"Range: {result.render()}")
                return result
            context.fail("Maximum must be greater than or equal to minimum.")

    def is_valid(self, value: NumberRange) -> bool:
        """Validate the rendered range."""
        if value.minimum is not None and value.maximum is not None and value.maximum < value.minimum:
            return False
        return True

    def parse_direct(self, text: str) -> NumberRange | None:
        """Parse supported direct-entry range formats."""
        normalized = text.strip().lower()
        if " to " in normalized:
            left, right = normalized.split(" to ", 1)
            lower = self.parse_decimal(left)
            upper = self.parse_decimal(right)
            if lower is None or upper is None:
                return None
            return NumberRange(lower, upper)
        if normalized.startswith("under "):
            upper = self.parse_decimal(normalized.removeprefix("under ").strip())
            return NumberRange(None, upper) if upper is not None else None
        if normalized.startswith("at least "):
            lower = self.parse_decimal(normalized.removeprefix("at least ").strip())
            return NumberRange(lower, None) if lower is not None else None
        if normalized.endswith("+"):
            lower = self.parse_decimal(normalized[:-1].strip())
            return NumberRange(lower, None) if lower is not None else None
        return None

    def parse_decimal(self, text: str) -> Decimal | None:
        """Parse a decimal safely."""
        try:
            return Decimal(text)
        except InvalidOperation:
            return None
