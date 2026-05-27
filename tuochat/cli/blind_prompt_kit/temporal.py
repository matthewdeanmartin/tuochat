"""Date, time, datetime, and duration prompt components."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from .core import InteractionContext
from .models import DateRange
from .numbers import IntegerInput

weekday_names = {name.lower(): index for index, name in enumerate(calendar.day_name)}
weekday_abbreviations = {name.lower(): index for index, name in enumerate(calendar.day_abbr)}
month_names = {name.lower(): index for index, name in enumerate(calendar.month_name) if name}
month_abbreviations = {name.lower(): index for index, name in enumerate(calendar.month_abbr) if name}


def render_date(value: date) -> str:
    """Render a spoken date."""
    return f"{value.strftime('%B')} {value.day}, {value.year}"


def render_time(value: time) -> str:
    """Render a spoken time."""
    hour = value.hour
    minute = value.minute
    suffix = "AM" if hour < 12 else "PM"
    display_hour = hour % 12 or 12
    if minute == 0:
        return f"{display_hour} {suffix}"
    return f"{display_hour}:{minute:02d} {suffix}"


def resolve_weekday(name: str) -> int | None:
    """Resolve a weekday name or abbreviation."""
    normalized = name.strip().lower()
    return weekday_names.get(normalized, weekday_abbreviations.get(normalized))


def parse_month(name: str) -> int | None:
    """Resolve a month name or abbreviation."""
    normalized = name.strip().lower()
    return month_names.get(normalized, month_abbreviations.get(normalized))


def parse_date_text(text: str, *, reference: date | None = None) -> tuple[date | None, str | None]:
    """Parse supported date formats and return (value, error)."""
    reference = reference or date.today()
    normalized = text.strip()
    lowered = normalized.lower()
    if lowered == "today":
        return reference, None
    if lowered == "tomorrow":
        return reference + timedelta(days=1), None
    relative_match = re.fullmatch(r"(next|this)\s+([a-zA-Z]+)", lowered)
    if relative_match:
        qualifier, weekday_text = relative_match.groups()
        weekday = resolve_weekday(weekday_text)
        if weekday is None:
            return None, "Enter a date like April 5 2026, today, or next Friday."
        delta = (weekday - reference.weekday()) % 7
        if qualifier == "next":
            delta = 7 if delta == 0 else delta
        return reference + timedelta(days=delta), None
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d %Y", "%b %d %Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            value = datetime.strptime(normalized, pattern).date()
        except ValueError:
            continue
        if pattern in {"%m/%d/%Y", "%m/%d/%y"}:
            month_str, day_str, _year_str = normalized.split("/")
            if int(month_str) <= 12 and int(day_str) <= 12:
                return None, f"{normalized} is ambiguous. Type the month name."
        return value, None
    month_name_match = re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2})(?:,\s*|\s+)?(\d{4})?", normalized)
    if month_name_match:
        month_text, day_text, year_text = month_name_match.groups()
        month_num = parse_month(month_text)
        if month_num is None:
            return None, "Enter a date like April 5 2026, today, or next Friday."
        year = int(year_text) if year_text else reference.year
        try:
            return date(year, month_num, int(day_text)), None
        except ValueError:
            return None, "Enter a valid calendar date."
    return None, "Enter a date like April 5 2026, today, or next Friday."


def parse_time_text(text: str) -> tuple[time | None, str | None]:
    """Parse supported time formats."""
    normalized = text.strip().lower()
    collapsed = normalized.replace(" ", "")
    if normalized == "noon":
        return time(hour=12), None
    if normalized == "midnight":
        return time(hour=0), None
    for candidate, pattern in (
        (normalized, "%H:%M"),
        (collapsed, "%I%p"),
        (collapsed, "%I:%M%p"),
        (normalized, "%I %p"),
    ):
        try:
            parsed = datetime.strptime(candidate, pattern)
        except ValueError:
            continue
        return parsed.time().replace(second=0, microsecond=0), None
    return None, "Enter a time like 3pm, 15:00, noon, or midnight."


def parse_duration_text(text: str) -> tuple[timedelta | None, str | None]:
    """Parse supported duration formats."""
    normalized = text.strip().lower()
    shorthand = re.fullmatch(r"(?:(\d+)h)?\s*(?:(\d+)m)?", normalized)
    if shorthand and (shorthand.group(1) or shorthand.group(2)):
        hours = int(shorthand.group(1) or 0)
        minutes = int(shorthand.group(2) or 0)
        return timedelta(hours=hours, minutes=minutes), None
    verbose_match = re.fullmatch(r"(?:(\d+)\s*hours?)?\s*(?:(\d+)\s*minutes?)?", normalized)
    if verbose_match and (verbose_match.group(1) or verbose_match.group(2)):
        hours = int(verbose_match.group(1) or 0)
        minutes = int(verbose_match.group(2) or 0)
        return timedelta(hours=hours, minutes=minutes), None
    return None, "Enter a duration like 30 minutes, 2h, or 1 hour 15 minutes."


@dataclass
class DateInput:
    """Prompt for a date."""

    prompt: str
    reference_date: date = field(default_factory=date.today)
    help_text: str | None = None

    def run(self, context: InteractionContext) -> date:
        """Collect a date."""
        while True:
            raw = context.ask(
                self.prompt,
                hint="Enter a full date, today, tomorrow, or type step.",
                help_text=self.help_text,
            )
            text, command = context.parse_raw_input(raw)
            if command is not None and context.apply_common_command(command, help_text=self.help_text):
                continue
            if text.strip().lower() == "step":
                return self.run_step_mode(context)
            value, error = parse_date_text(text, reference=self.reference_date)
            if value is None:
                context.fail(error or "Enter a valid date.")
                continue
            context.say(f"{self.prompt.rstrip('?')}: {render_date(value)}.")
            return value

    def run_step_mode(self, context: InteractionContext) -> date:
        """Collect a date in three steps."""
        while True:
            month_raw = context.ask("Month?", help_text=self.help_text)
            month_text, command = context.parse_raw_input(month_raw)
            if command is not None and context.apply_common_command(command, help_text=self.help_text):
                continue
            month = parse_month(month_text)
            if month is None:
                context.fail("Say the month name, like April.")
                continue
            day = IntegerInput("Day?", minimum=1, maximum=31).run(context)
            year = IntegerInput("Year?", minimum=1).run(context)
            try:
                value = date(year, month, day)
            except ValueError:
                context.fail("Enter a valid calendar date.")
                continue
            context.say(f"Date: {render_date(value)}.")
            return value


@dataclass
class TimeInput:
    """Prompt for a time."""

    prompt: str
    help_text: str | None = None

    def run(self, context: InteractionContext) -> time:
        """Collect a time."""
        while True:
            raw = context.ask(self.prompt, hint="Enter a time like 3pm, 15:00, or type step.", help_text=self.help_text)
            text, command = context.parse_raw_input(raw)
            if command is not None and context.apply_common_command(command, help_text=self.help_text):
                continue
            if text.strip().lower() == "step":
                return self.run_step_mode(context)
            value, error = parse_time_text(text)
            if value is None:
                context.fail(error or "Enter a valid time.")
                continue
            context.say(f"{self.prompt.rstrip('?')}: {render_time(value)}.")
            return value

    def run_step_mode(self, context: InteractionContext) -> time:
        """Collect a time step by step."""
        hour = IntegerInput("Hour?", minimum=1, maximum=12).run(context)
        minute = IntegerInput("Minute?", minimum=0, maximum=59).run(context)
        meridiem = context.ask("AM or PM?", help_text=self.help_text)
        answer = meridiem.strip().lower()
        if answer not in {"am", "pm"}:
            context.fail("Answer AM or PM.")
            return self.run_step_mode(context)
        hour_24 = hour % 12
        if answer == "pm":
            hour_24 += 12
        value = time(hour=hour_24, minute=minute)
        context.say(f"Time: {render_time(value)}.")
        return value


@dataclass
class DateTimeInput:
    """Prompt for a datetime."""

    prompt: str
    help_text: str | None = None

    def run(self, context: InteractionContext) -> datetime:
        """Collect a datetime by composing date and time components."""
        context.say(self.prompt)
        date_value = DateInput("Date?", help_text=self.help_text).run(context)
        time_value = TimeInput("Time?", help_text=self.help_text).run(context)
        result = datetime.combine(date_value, time_value)
        context.say(f"{render_date(date_value)} at {render_time(time_value)}.")
        return result


@dataclass
class DurationInput:
    """Prompt for a duration."""

    prompt: str
    help_text: str | None = None

    def run(self, context: InteractionContext) -> timedelta:
        """Collect a duration."""
        while True:
            raw = context.ask(
                self.prompt,
                hint="Enter a duration like 30 minutes, 2h, or type step.",
                help_text=self.help_text,
            )
            text, command = context.parse_raw_input(raw)
            if command is not None and context.apply_common_command(command, help_text=self.help_text):
                continue
            if text.strip().lower() == "step":
                hours = IntegerInput("Hours?", minimum=0).run(context)
                minutes = IntegerInput("Minutes?", minimum=0, maximum=59).run(context)
                stepped = timedelta(hours=hours, minutes=minutes)
                context.say(f"Duration: {self.render_duration(stepped)}.")
                return stepped
            parsed, error = parse_duration_text(text)
            if parsed is None:
                context.fail(error or "Enter a valid duration.")
                continue
            context.say(f"Duration: {self.render_duration(parsed)}.")
            return parsed

    def render_duration(self, value: timedelta) -> str:
        """Render a duration for spoken output."""
        total_minutes = int(value.total_seconds() // 60)
        hours, minutes = divmod(total_minutes, 60)
        if hours and minutes:
            return f"{hours} hours {minutes} minutes"
        if hours:
            noun = "hour" if hours == 1 else "hours"
            return f"{hours} {noun}"
        noun = "minute" if minutes == 1 else "minutes"
        return f"{minutes} {noun}"


@dataclass
class DateRangeInput:
    """Prompt for a date range."""

    prompt: str
    reference_date: date = field(default_factory=date.today)
    help_text: str | None = None
    allow_open_end: bool = False
    allow_open_start: bool = False

    def run(self, context: InteractionContext) -> DateRange:
        """Collect a date range."""
        while True:
            raw = context.ask(
                self.prompt,
                hint="Enter both dates like April 5 to April 9, or type step.",
                help_text=self.help_text,
            )
            text, command = context.parse_raw_input(raw)
            if command is not None and context.apply_common_command(command, help_text=self.help_text):
                continue
            lowered = text.strip().lower()
            if lowered == "step":
                return self.run_step_mode(context)
            parsed = self.parse_direct(text)
            if parsed is None:
                context.fail("Enter both dates like April 5 to April 9, or type step.")
                continue
            if parsed.start and parsed.end and parsed.end < parsed.start:
                context.fail("End date must be after start date.")
                continue
            context.say(f"Range: {parsed.render()}")
            return parsed

    def run_step_mode(self, context: InteractionContext) -> DateRange:
        """Collect the range one side at a time."""
        start = DateInput("Start date?", reference_date=self.reference_date, help_text=self.help_text).run(context)
        while True:
            end = DateInput("End date?", reference_date=self.reference_date, help_text=self.help_text).run(context)
            if end < start:
                context.fail("End date must be after start date.")
                continue
            result = DateRange(start, end)
            context.say(f"Range: {result.render()}")
            return result

    def parse_direct(self, text: str) -> DateRange | None:
        """Parse a direct-entry date range."""
        lowered = text.strip().lower()
        if self.allow_open_end and lowered == "open end":
            return DateRange(self.reference_date, None)
        if self.allow_open_start and lowered == "open start":
            return DateRange(None, self.reference_date)
        for separator in (" to ", " through "):
            if separator not in lowered:
                continue
            left, right = lowered.split(separator, 1)
            start, start_error = parse_date_text(left, reference=self.reference_date)
            end, end_error = parse_date_text(right, reference=self.reference_date)
            if start is None or end is None:
                return None if start_error or end_error else None
            return DateRange(start, end)
        return None
