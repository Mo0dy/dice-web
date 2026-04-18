#!/usr/bin/env python3
"""Interactive interpreter for the dice language"""

import argparse
import os
import sys

from diagnostics import DEFAULT_SOURCE_NAME, DiagnosticError, format_diagnostic
try:
    import timeout_decorator
except ImportError:
    class _TimeoutFallback(object):
        @staticmethod
        def timeout(_seconds):
            def decorator(function):
                return function
            return decorator

    timeout_decorator = _TimeoutFallback()

try:
    import readline
except ImportError:  # pragma: no cover - platform-specific
    readline = None

from interpreter import Interpreter
from executor import D, dicefunction
from diceengine import (
    Distributions,
    Distribution,
    FiniteMeasure,
    TupleValue,
    RecordValue,
    RenderConfig,
    wait_for_rendered_figures,
)
from diceparser import DiceParser, ParserError
from lexer import Lexer, LexerError
from resultjson import (
    format_result_json as _format_result_json,
    is_numeric as _is_numeric,
    resolve_probability_mode as _resolve_probability_mode,
    round_numeric as _round_numeric,
    serialize_embedded_value as _serialize_embedded_value,
    serialize_measure as _serialize_measure,
    serialize_result as _serialize_result,
)


timeout_seconds = 5
DEFAULT_ROUNDLEVEL = 2
REPL_HISTORY_LENGTH = 1000
NON_BLOCKING_RENDER_CONFIG = RenderConfig.from_mode("nonblocking")
DEFERRED_RENDER_CONFIG = RenderConfig.from_mode("deferred")
REPL_COMPLETER_DELIMS = " \t\n\"'`(){}[];,|&<>!=+*"


class InteractiveCommandError(Exception):
    """Raised for invalid REPL-only commands."""


def _is_deterministic_distribution(distrib):
    items = list(distrib.items())
    return len(items) == 1 and items[0][1] == 1


def _deterministic_outcome(distrib):
    return next(iter(distrib.keys()))


def _all_scalar(result):
    return all(_is_deterministic_distribution(distrib) for distrib in result.cells.values())


def _ordered_labels(values):
    def sort_key(value):
        if isinstance(value, (int, float)):
            return (0, value)
        if isinstance(value, str):
            return (1, value)
        if isinstance(value, TupleValue):
            return (2, str(value))
        if isinstance(value, RecordValue):
            return (3, str(value))
        return (4, str(value))

    return list(sorted(values, key=sort_key))


def _format_rounded_numeric(value, roundlevel=0):
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not roundlevel:
            return str(value)
        rounded = _round_numeric(value, roundlevel)
        if rounded.is_integer():
            return str(int(rounded))
        return f"{rounded:.{roundlevel}f}"
    return str(value)


def _format_scalar(value, roundlevel=0):
    if _is_numeric(value):
        return _format_rounded_numeric(value, roundlevel)
    return str(value)


def _format_label(value, roundlevel=0):
    if _is_numeric(value):
        return _format_rounded_numeric(value, roundlevel)
    return str(value)


def _format_probability(value, roundlevel=0, probability_mode="percent"):
    if probability_mode == "percent":
        return "{}%".format(_format_rounded_numeric(value * 100, roundlevel))
    return _format_rounded_numeric(value, roundlevel)


def _axis_header(name):
    return f"/{name}" if name else ""


def _corner_label(row_name, col_name):
    return "{}/{}".format(row_name or "", col_name or "")


def _string_table(rows):
    if not rows:
        return ""
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    return "\n".join(
        "  ".join(cell.rjust(widths[index]) for index, cell in enumerate(row))
        for row in rows
    )


def _format_key_value_lines(entries):
    if not entries:
        return ""
    label_width = max(len(label) for label, _ in entries)
    return "\n".join("{}: {}".format(label.rjust(label_width), value) for label, value in entries)


def _distribution_mean(distrib):
    outcomes = list(distrib.keys())
    if not outcomes or not all(_is_numeric(outcome) for outcome in outcomes):
        return None
    return distrib.average()


def _format_unswept_distribution(distrib, roundlevel=0, probability_mode="percent"):
    if _is_deterministic_distribution(distrib):
        return _format_scalar(_deterministic_outcome(distrib), roundlevel)
    entries = [
        (
            _format_label(outcome, roundlevel),
            _format_probability(distrib[outcome], roundlevel, probability_mode=probability_mode),
        )
        for outcome in _ordered_labels(distrib.keys())
    ]
    mean = _distribution_mean(distrib)
    if mean is not None:
        entries.append(("(E)", _format_scalar(mean, roundlevel)))
    return _format_key_value_lines(entries)


def _format_scalar_sweep(result, roundlevel=0):
    axis = result.axes[0]
    lines = []
    if axis.name:
        lines.append(_axis_header(axis.name))
    lines.append(
        _format_key_value_lines(
            [
                (
                    _format_label(value, roundlevel),
                    _format_scalar(_deterministic_outcome(result.cells[(value,)]), roundlevel),
                )
                for value in axis.values
            ]
        )
    )
    return "\n".join(lines)


def _format_distribution_sweep(result, roundlevel=0, probability_mode="percent"):
    axis = result.axes[0]
    outcomes = []
    seen = set()
    means = []
    for axis_value in axis.values:
        distrib = result.cells[(axis_value,)]
        means.append(_distribution_mean(distrib))
        for outcome in _ordered_labels(result.cells[(axis_value,)].keys()):
            if outcome not in seen:
                outcomes.append(outcome)
                seen.add(outcome)

    rows = [[_axis_header(axis.name)] + [_format_label(value, roundlevel) for value in axis.values]]
    for outcome in outcomes:
        rows.append(
            [_format_label(outcome, roundlevel)]
            + [
                _format_probability(
                    result.cells[(value,)][outcome],
                    roundlevel,
                    probability_mode=probability_mode,
                )
                for value in axis.values
            ]
        )
    if all(mean is not None for mean in means):
        rows.append(["(E)"] + [_format_scalar(mean, roundlevel) for mean in means])
    return _string_table(rows)


def _format_scalar_heatmap(result, roundlevel=0):
    row_axis, col_axis = result.axes
    rows = [[_corner_label(row_axis.name, col_axis.name)] + [_format_label(value, roundlevel) for value in col_axis.values]]
    for row_value in row_axis.values:
        row = [_format_label(row_value, roundlevel)]
        for col_value in col_axis.values:
            scalar = _deterministic_outcome(result.cells[(row_value, col_value)])
            row.append(_format_scalar(scalar, roundlevel))
        rows.append(row)
    return _string_table(rows)


def _format_result_text(result, roundlevel=0, probability_mode="percent"):
    if isinstance(result, Distributions):
        if result.is_unswept() and isinstance(result.only_distribution(), FiniteMeasure) and not isinstance(result.only_distribution(), Distribution):
            return str(result.only_distribution())
        if result.is_unswept():
            return _format_unswept_distribution(
                result.only_distribution(),
                roundlevel,
                probability_mode=probability_mode,
            )
        if len(result.axes) == 1:
            if _all_scalar(result):
                return _format_scalar_sweep(result, roundlevel)
            return _format_distribution_sweep(
                result,
                roundlevel,
                probability_mode=probability_mode,
            )
        if len(result.axes) == 2 and _all_scalar(result):
            return _format_scalar_heatmap(result, roundlevel)
    if isinstance(result, float) and roundlevel:
        return _format_scalar(result, roundlevel)
    return str(result)


def _build_render_config(mode, render_backend="matplotlib"):
    return RenderConfig.from_mode(mode).with_backend(render_backend)


def _history_file_path():
    state_home = os.environ.get("XDG_STATE_HOME")
    if not state_home:
        state_home = os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(state_home, "dice", "history")


def _setup_repl_history(readline_module=None):
    readline_module = readline if readline_module is None else readline_module
    if readline_module is None:
        return None
    history_path = _history_file_path()
    try:
        os.makedirs(os.path.dirname(history_path), exist_ok=True)
    except OSError:
        return None
    try:
        readline_module.read_history_file(history_path)
    except (FileNotFoundError, OSError):
        pass
    readline_module.set_history_length(REPL_HISTORY_LENGTH)
    return history_path


def _save_repl_history(history_path, readline_module=None):
    readline_module = readline if readline_module is None else readline_module
    if readline_module is None or history_path is None:
        return
    try:
        readline_module.write_history_file(history_path)
    except OSError:
        pass


def _setup_repl_completion(interpreter, readline_module=None):
    readline_module = readline if readline_module is None else readline_module
    if readline_module is None:
        return None

    def completer(text, state):
        line_buffer = readline_module.get_line_buffer()
        begidx = readline_module.get_begidx()
        endidx = readline_module.get_endidx()
        matches = interpreter.complete(
            text,
            line_buffer=line_buffer,
            begidx=begidx,
            endidx=endidx,
        )
        if state < len(matches):
            return matches[state]
        return None

    if hasattr(readline_module, "parse_and_bind"):
        readline_module.parse_and_bind("tab: complete")
    if hasattr(readline_module, "set_completer_delims"):
        readline_module.set_completer_delims(REPL_COMPLETER_DELIMS)
    if hasattr(readline_module, "set_completer"):
        readline_module.set_completer(completer)
    return completer


def _handle_repl_command(text, state, interpreter):
    stripped = text.strip()
    if not stripped.startswith("$"):
        return False
    parts = stripped[1:].split()
    if not parts:
        raise InteractiveCommandError("Missing interpreter command")
    if parts[0] == "set_round":
        if len(parts) != 2:
            raise InteractiveCommandError("set_round expects exactly one integer argument")
        try:
            roundlevel = int(parts[1])
        except ValueError as error:
            raise InteractiveCommandError("set_round expects an integer argument") from error
        if roundlevel < 0:
            raise InteractiveCommandError("set_round expects a non-negative integer")
        state["roundlevel"] = roundlevel
        return "round = {}".format(roundlevel)
    if parts[0] == "set_render_mode":
        if len(parts) != 2:
            raise InteractiveCommandError(
                "set_render_mode expects exactly one mode argument"
            )
        interpreter.executor.set_render_mode(parts[1])
        mode_name = interpreter.executor.render_config.mode_name()
        state["render_mode"] = mode_name
        return "render_mode = {}".format(mode_name)
    if parts[0] == "set_render_backend":
        if len(parts) != 2:
            raise InteractiveCommandError(
                "set_render_backend expects exactly one backend argument"
            )
        backend_name = interpreter.executor.set_render_backend(parts[1])
        state["render_backend"] = backend_name
        return "render_backend = {}".format(backend_name)
    if parts[0] == "set_render_autoflush":
        if len(parts) != 2:
            raise InteractiveCommandError(
                "set_render_autoflush expects exactly one mode argument"
            )
        autoflush_mode = interpreter.executor.set_render_autoflush(parts[1])
        state["render_autoflush"] = autoflush_mode
        return "render_autoflush = {}".format(autoflush_mode)
    if parts[0] == "set_render_omit_dominant_zero":
        if len(parts) != 2:
            raise InteractiveCommandError(
                "set_render_omit_dominant_zero expects exactly one mode argument"
            )
        zero_mode = interpreter.executor.set_render_omit_dominant_zero(parts[1])
        state["render_omit_dominant_zero"] = zero_mode
        return "render_omit_dominant_zero = {}".format(zero_mode)
    if parts[0] == "set_probability_mode":
        if len(parts) != 2:
            raise InteractiveCommandError(
                "set_probability_mode expects exactly one mode argument"
            )
        probability_mode = interpreter.executor.set_probability_mode(parts[1])
        state["probability_mode"] = probability_mode
        return "probability_mode = {}".format(probability_mode)
    raise InteractiveCommandError("Unknown interpreter command {}".format(parts[0]))


def _interpret_ast(ast, roundlevel=0, executor=None, interpreter=None, current_dir=None, render_config=None):
    if interpreter is None:
        interpreter = Interpreter(
            ast,
            executor=executor,
            current_dir=current_dir,
            render_config=render_config,
        )
    else:
        interpreter.ast = ast
        if current_dir is not None:
            interpreter.current_dir = os.path.abspath(current_dir)
    interpreter.warnings = []
    result = interpreter.interpret()
    return result


def _print_warnings(interpreter):
    for warning in getattr(interpreter, "warnings", []):
        sys.stderr.write(format_diagnostic(warning) + "\n")


@timeout_decorator.timeout(timeout_seconds)
def interpret_statement(
    text,
    roundlevel=0,
    executor=None,
    interpreter=None,
    current_dir=None,
    source_name=DEFAULT_SOURCE_NAME,
    render_config=None,
):
    parser = DiceParser(Lexer(text, source_name=source_name))
    ast = parser.parse() if (";" in text or "\n" in text) else parser.statement()
    return _interpret_ast(
        ast,
        roundlevel,
        executor=executor,
        interpreter=interpreter,
        current_dir=current_dir,
        render_config=render_config,
    )


@timeout_decorator.timeout(timeout_seconds)
def interpret_file(
    text,
    roundlevel=0,
    executor=None,
    interpreter=None,
    current_dir=None,
    source_name=DEFAULT_SOURCE_NAME,
    render_config=None,
):
    """Interpret a semicolon or newline separated program."""
    return _interpret_ast(
        DiceParser(Lexer(text, source_name=source_name)).parse(),
        roundlevel,
        executor=executor,
        interpreter=interpreter,
        current_dir=current_dir,
        render_config=render_config,
    )


class DiceSession(object):
    """Stateful Python-facing wrapper around the dice interpreter."""

    def __init__(self, roundlevel=0, executor=None, current_dir=None, render_config=None):
        self.roundlevel = roundlevel
        self.current_dir = os.path.abspath(current_dir if current_dir is not None else os.getcwd())
        session_render_config = (
            render_config if render_config is not None else NON_BLOCKING_RENDER_CONFIG
        )
        self.interpreter = Interpreter(
            None,
            executor=executor,
            current_dir=self.current_dir,
            render_config=session_render_config,
        )

    def __call__(self, text, current_dir=None):
        call_dir = self.current_dir if current_dir is None else os.path.abspath(current_dir)
        return interpret_statement(
            text,
            roundlevel=self.roundlevel,
            interpreter=self.interpreter,
            current_dir=call_dir,
        )

    def assign(self, name, value):
        if value is None:
            self.interpreter.exception("Unsupported host value type {}".format(type(value)))
        self.interpreter._validate_runtime_value(value)
        self.interpreter.global_scope[name] = value
        return value

    def register_function(self, function, name=None):
        return self.interpreter.register_function(function, name=name)


def dice_interpreter(roundlevel=0, current_dir=None, executor=None, render_config=None):
    return DiceSession(
        roundlevel=roundlevel,
        current_dir=current_dir,
        executor=executor,
        render_config=render_config,
    )


def print_interactive_error(error):
    """Print a user-facing REPL error without a traceback."""
    if isinstance(error, DiagnosticError):
        sys.stderr.write(format_diagnostic(error) + "\n")
        return
    prefix = "syntax error" if isinstance(error, (ParserError, LexerError)) else "error"
    sys.stderr.write("{}: {}\n".format(prefix, error))


def runinteractive(args):
    """Run a simple interactive shell."""
    json_output = getattr(args, "json_output", False)
    render_backend = getattr(args, "render_backend", "matplotlib")

    def emit_result(result):
        print_result(
            result,
            args.verbose,
            json_output=json_output,
            roundlevel=state["roundlevel"],
            probability_mode=interpreter.executor.render_config.probability_mode,
        )

    interpreter = Interpreter(
        None,
        current_dir=os.getcwd(),
        render_config=_build_render_config("nonblocking", render_backend),
        output_callback=emit_result,
    )
    state = {
        "roundlevel": args.roundlevel,
        "render_mode": interpreter.executor.render_config.mode_name(),
        "render_backend": interpreter.executor.render_config.backend,
        "render_autoflush": "on" if interpreter.executor.render_config.auto_render_pending_on_exit else "off",
        "render_omit_dominant_zero": "on" if interpreter.executor.render_config.omit_dominant_zero_outcome else "off",
        "probability_mode": _resolve_probability_mode(
            interpreter.executor.render_config.probability_mode,
            json_output=json_output,
        ),
    }
    history_path = _setup_repl_history()
    _setup_repl_completion(interpreter)
    try:
        while True:
            try:
                text = input("dice> ")
            except EOFError:
                return 0
            except KeyboardInterrupt:
                sys.stderr.write("\n")
                continue
            if text == "exit":
                return 0
            if not text.strip():
                continue
            try:
                command_result = _handle_repl_command(text, state, interpreter)
                if command_result is not False:
                    if command_result is not None:
                        sys.stdout.write(command_result + "\n")
                    continue
                result = interpret_statement(
                    text,
                    state["roundlevel"],
                    interpreter=interpreter,
                    source_name="<repl>",
                )
            except Exception as error:
                print_interactive_error(error)
                continue
            _print_warnings(interpreter)
            if result is not None:
                print_result(
                    result,
                    args.verbose,
                    text,
                    json_output=json_output,
                    roundlevel=state["roundlevel"],
                    probability_mode=interpreter.executor.render_config.probability_mode,
                )
    finally:
        _save_repl_history(history_path)
    return 2


def print_result(
    result,
    verbose=False,
    line="",
    json_output=False,
    roundlevel=0,
    probability_mode=None,
):
    """Print a result to stdout."""
    effective_probability_mode = _resolve_probability_mode(
        probability_mode,
        json_output=json_output,
    )
    rendered = (
        _format_result_json(
            result,
            roundlevel,
            probability_mode=effective_probability_mode,
        )
        if json_output
        else _format_result_text(
            result,
            roundlevel,
            probability_mode=effective_probability_mode,
        )
    )

    if verbose:
        sys.stdout.write("dice> " + line + "\n" + rendered + "\n")
        return
    sys.stdout.write(rendered + "\n")


def _resolve_cli_roundlevel(roundlevel, json_output=False):
    if roundlevel is not None:
        return roundlevel
    return 0 if json_output else DEFAULT_ROUNDLEVEL


def main():
    parser = argparse.ArgumentParser(description="Process some inputs.")
    parser.add_argument("-R", "--round", "--roundlevel", dest="roundlevel", type=int, default=None, help="Set rounding level")
    parser.add_argument("-i", "--interactive", action="store_true", help="Run in interactive mode")
    parser.add_argument("-f", "--file", dest="file", help="Execute a dice source file")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Print structured JSON output")
    parser.add_argument(
        "--render-backend",
        choices=("matplotlib", "json"),
        default="matplotlib",
        help="Select the render backend",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument("command", nargs="*", help="Command to execute")

    # Parse arguments
    args = parser.parse_args()
    args.roundlevel = _resolve_cli_roundlevel(args.roundlevel, json_output=args.json_output)

    if args.interactive:
        if args.file or args.command:
            parser.error("--interactive cannot be combined with --file or a command")
        return runinteractive(args)

    if args.file:
        if args.command:
            parser.error("--file cannot be combined with a command")

        def emit_result(result):
            print_result(
                result,
                args.verbose,
                args.file,
                json_output=args.json_output,
                roundlevel=args.roundlevel,
                probability_mode=interpreter.executor.render_config.probability_mode,
            )

        interpreter = Interpreter(
            None,
            current_dir=os.path.dirname(os.path.abspath(args.file)),
            render_config=_build_render_config("deferred", args.render_backend),
            output_callback=emit_result,
        )
        with open(args.file) as f:
            try:
                result = interpret_file(
                    f.read(),
                    args.roundlevel,
                    interpreter=interpreter,
                    current_dir=os.path.dirname(os.path.abspath(args.file)),
                    source_name=os.path.abspath(args.file),
                )
            except DiagnosticError as error:
                sys.stderr.write(format_diagnostic(error) + "\n")
                return 1
        _print_warnings(interpreter)
        if result is not None:
            print_result(
                result,
                args.verbose,
                args.file,
                json_output=args.json_output,
                roundlevel=args.roundlevel,
                probability_mode=interpreter.executor.render_config.probability_mode,
            )
        wait_for_rendered_figures(interpreter.executor.render_config)
        return 0

    if not args.command:
        parser.error("expected a dice command, or use --interactive / --file")

    command = " ".join(args.command)
    interpreter = Interpreter(
        None,
        current_dir=os.getcwd(),
        render_config=_build_render_config("deferred", args.render_backend),
        output_callback=lambda result: print_result(
            result,
            args.verbose,
            command,
            json_output=args.json_output,
            roundlevel=args.roundlevel,
            probability_mode=interpreter.executor.render_config.probability_mode,
        ),
    )
    try:
        result = interpret_statement(
            command,
            args.roundlevel,
            interpreter=interpreter,
            source_name="<command>",
        )
    except DiagnosticError as error:
        sys.stderr.write(format_diagnostic(error) + "\n")
        return 1
    _print_warnings(interpreter)
    if result is not None:
        print_result(
            result,
            args.verbose,
            command,
            json_output=args.json_output,
            roundlevel=args.roundlevel,
            probability_mode=interpreter.executor.render_config.probability_mode,
        )
    wait_for_rendered_figures(interpreter.executor.render_config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
