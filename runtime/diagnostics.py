#!/usr/bin/env python3

"""Shared diagnostic types and pretty formatting for dice language errors."""

from dataclasses import dataclass


DEFAULT_SOURCE_NAME = "<input>"


@dataclass(frozen=True)
class SourceDocument:
    """Named source text for diagnostic rendering."""

    name: str
    text: str

    def line_text(self, line_number):
        lines = self.text.splitlines()
        if not lines:
            return ""
        if line_number < 1 or line_number > len(lines):
            return ""
        return lines[line_number - 1]


@dataclass(frozen=True)
class SourceSpan:
    """A concrete source range within a document."""

    document: SourceDocument
    start_index: int
    end_index: int
    start_line: int
    start_column: int
    end_line: int
    end_column: int

    @property
    def line_text(self):
        return self.document.line_text(self.start_line)


class DiagnosticError(Exception):
    """Base error carrying optional location and hint metadata."""

    def __init__(self, message, *, title="error", span=None, hint=None):
        super().__init__(message)
        self.message = message
        self.title = title
        self.span = span
        self.hint = hint

    def attach_span(self, span):
        if self.span is None and span is not None:
            self.span = span
        return self

    def attach_hint(self, hint):
        if self.hint is None and hint:
            self.hint = hint
        return self

    def __str__(self):
        return format_diagnostic(self)


class LexerError(DiagnosticError):
    """Raised when tokenization fails."""

    def __init__(self, message, *, span=None, hint=None):
        super().__init__(message, title="syntax error", span=span, hint=hint)


class ParserError(DiagnosticError):
    """Raised when parsing fails."""

    def __init__(self, message, *, span=None, hint=None):
        super().__init__(message, title="syntax error", span=span, hint=hint)


class RuntimeError(DiagnosticError):
    """Raised when runtime evaluation fails."""

    def __init__(self, message, *, span=None, hint=None):
        super().__init__(message, title="error", span=span, hint=hint)


class DiagnosticWarning(object):
    """Non-fatal warning carrying optional location and hint metadata."""

    def __init__(self, message, *, span=None, hint=None):
        self.message = message
        self.title = "warning"
        self.span = span
        self.hint = hint


def _caret_line(span):
    line_text = span.line_text
    caret_start = max(span.start_column - 1, 0)
    if span.start_line == span.end_line:
        caret_width = max(span.end_column - span.start_column, 1)
    else:
        caret_width = max(len(line_text) - caret_start, 1)
    return "{}{}".format(" " * caret_start, "^" * caret_width)


def format_diagnostic(error):
    """Render a readable multi-line diagnostic."""

    lines = ["{}: {}".format(error.title, error.message)]
    if error.span is not None:
        span = error.span
        line_number = span.start_line
        lines.append("  --> {}:{}:{}".format(span.document.name, span.start_line, span.start_column))
        lines.append("   |")
        lines.append("{:>2} | {}".format(line_number, span.line_text))
        lines.append("   | {}".format(_caret_line(span)))
    if error.hint:
        lines.append("   = hint: {}".format(error.hint))
    return "\n".join(lines)
