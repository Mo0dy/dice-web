#!/usr/bin/env python3

"""Stable browser-facing bridge for the vendored dice runtime."""

from __future__ import annotations

import json
import os
import sys
import tempfile


def _ensure_dice_imports():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
    candidates = [
        os.path.join(current_dir, "dice"),
        os.path.join(os.path.dirname(current_dir), "dice"),
        current_dir,
    ]
    for candidate in candidates:
        if os.path.isfile(os.path.join(candidate, "interpreter.py")):
            if candidate not in sys.path:
                sys.path.insert(1, candidate)
            return candidate
    raise ImportError("Could not locate dice runtime sources for webbridge")


_ensure_dice_imports()

from diagnostics import DiagnosticError, format_diagnostic
from diceengine import Distribution, Distributions, FiniteMeasure, RenderConfig
from diceparser import DiceParser, ParserError
from executor import ExactExecutor
from interpreter import COMPLETION_KEYWORDS, CallableEntry, Interpreter, STDLIB_ROOT
from lexer import ASSIGN, Lexer, LexerError, SEMI


DEFAULT_SOURCE_PATH = "main.dice"
DEFAULT_ROUNDLEVEL = 6
IMPORT_PATH_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./:-")
SAMPLE_ROOT_CANDIDATES = (
    ("examples", ("00_basic", "01_dnd", "02_python_extensions")),
    ("samples", ("dnd", "sweeps")),
)


def _is_numeric(value):
    return isinstance(value, (int, float))


def _round_numeric(value, digits):
    if digits and isinstance(value, float):
        return round(value, digits)
    return value


def _ordered_labels(values):
    def sort_key(value):
        if isinstance(value, (int, float)):
            return (0, value)
        return (1, str(value))

    return list(sorted(values, key=sort_key))


def _is_deterministic_distribution(distrib):
    items = list(distrib.items())
    return len(items) == 1 and items[0][1] == 1


def _deterministic_outcome(distrib):
    return next(iter(distrib.keys()))


def _is_scalar_cell(cell):
    if isinstance(cell, Distribution):
        return _is_deterministic_distribution(cell)
    return _is_numeric(cell) or isinstance(cell, str)


def _scalar_cell_value(cell):
    if isinstance(cell, Distribution):
        return _deterministic_outcome(cell)
    return cell


def _all_scalar(result):
    return all(_is_scalar_cell(cell) for cell in result.cells.values())


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
                    _format_scalar(_scalar_cell_value(result.cells[(value,)]), roundlevel),
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
            scalar = _scalar_cell_value(result.cells[(row_value, col_value)])
            row.append(_format_scalar(scalar, roundlevel))
        rows.append(row)
    return _string_table(rows)


def _format_result_text(result, roundlevel=0, probability_mode="percent"):
    if isinstance(result, Distributions):
        only_cell = next(iter(result.cells.values()))
        if result.is_unswept() and isinstance(only_cell, FiniteMeasure) and not isinstance(only_cell, Distribution):
            return str(only_cell)
        if result.is_unswept():
            if _is_scalar_cell(only_cell):
                return _format_scalar(_scalar_cell_value(only_cell), roundlevel)
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


def _serialize_distribution(distrib, *, roundlevel=0, probability_mode="raw"):
    scale = 100.0 if probability_mode == "percent" else 1.0
    entries = []
    for outcome in _ordered_labels(distrib.keys()):
        entries.append(
            {
                "outcome": _round_numeric(outcome, roundlevel) if _is_numeric(outcome) else outcome,
                "probability": _round_numeric(distrib[outcome] * scale, roundlevel),
            }
        )
    return entries


def _serialize_measure(measure, *, roundlevel=0):
    entries = []
    for outcome in _ordered_labels(measure.keys()):
        entries.append(
            {
                "outcome": _round_numeric(outcome, roundlevel) if _is_numeric(outcome) else str(outcome),
                "weight": _round_numeric(measure[outcome], roundlevel),
            }
        )
    return entries


def _serialize_result(result, *, roundlevel=0, probability_mode="raw"):
    if isinstance(result, Distributions):
        distribution_only = all(isinstance(distrib, Distribution) for distrib in result.cells.values())
        axes = [
            {
                "key": axis.key,
                "name": axis.name if not axis.name.startswith("sweep_") else None,
                "values": [
                    _round_numeric(value, roundlevel) if _is_numeric(value) else value
                    for value in axis.values
                ],
            }
            for axis in result.axes
        ]
        cells = []
        for coordinates, distrib in result.cells.items():
            coordinate_entries = []
            for axis, value in zip(result.axes, coordinates):
                coordinate_entries.append(
                    {
                        "axis_key": axis.key,
                        "axis_name": axis.name if not axis.name.startswith("sweep_") else None,
                        "value": _round_numeric(value, roundlevel) if _is_numeric(value) else value,
                    }
                )
            if distribution_only:
                cells.append(
                    {
                        "coordinates": coordinate_entries,
                        "distribution": _serialize_distribution(
                            distrib,
                            roundlevel=roundlevel,
                            probability_mode=probability_mode,
                        ),
                    }
                )
            else:
                cells.append(
                    {
                        "coordinates": coordinate_entries,
                        "value": (
                            {
                                "kind": "measure",
                                "measure": _serialize_measure(distrib, roundlevel=roundlevel),
                            }
                            if isinstance(distrib, FiniteMeasure)
                            else {
                                "kind": "scalar" if _is_numeric(distrib) or isinstance(distrib, str) else type(distrib).__name__,
                                "value": _round_numeric(distrib, roundlevel) if _is_numeric(distrib) else str(distrib),
                            }
                        ),
                    }
                )
        return {
            "type": "distributions" if distribution_only else "sweep",
            "axes": axes,
            "cells": cells,
        }
    if isinstance(result, Distribution):
        return {
            "type": "distribution",
            "distribution": _serialize_distribution(
                result,
                roundlevel=roundlevel,
                probability_mode=probability_mode,
            ),
        }
    if isinstance(result, FiniteMeasure):
        return {"type": "measure", "measure": _serialize_measure(result, roundlevel=roundlevel)}
    if isinstance(result, str):
        return {"type": "string", "value": result}
    if _is_numeric(result):
        return {"type": "scalar", "value": _round_numeric(result, roundlevel)}
    return {"type": type(result).__name__, "value": str(result)}


def _normalize_workspace_path(path):
    normalized = os.path.normpath(path.replace("\\", "/")).lstrip("/")
    if normalized in ("", "."):
        return DEFAULT_SOURCE_PATH
    if normalized.startswith("../") or normalized == "..":
        raise ValueError("workspace files must stay within the project root")
    return normalized


def _write_workspace_files(root_dir, source, files=None, source_path=DEFAULT_SOURCE_PATH):
    files = {} if files is None else dict(files)
    normalized_source_path = _normalize_workspace_path(source_path)
    files[normalized_source_path] = source
    for relative_path, contents in files.items():
        destination = os.path.join(root_dir, _normalize_workspace_path(relative_path))
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        with open(destination, "w", encoding="utf-8") as handle:
            handle.write(contents)
    return normalized_source_path


def _discover_sample_root():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    search_roots = [current_dir, os.path.join(current_dir, "dice")]
    for base_dir in search_roots:
        for root_name, runnable_roots in SAMPLE_ROOT_CANDIDATES:
            candidate = os.path.join(base_dir, root_name)
            if os.path.isdir(candidate):
                return candidate, runnable_roots
    return None, ()


SAMPLE_ROOT, RUNNABLE_SAMPLE_ROOTS = _discover_sample_root()
SAMPLE_GROUP_LABEL = "Examples" if SAMPLE_ROOT and os.path.basename(SAMPLE_ROOT) == "examples" else "Samples"


def _stdlib_path(import_name):
    if not import_name.startswith("std:"):
        raise ValueError("stdlib paths must start with std:")
    relative_path = import_name.removeprefix("std:")
    if not relative_path.endswith(".dice"):
        relative_path = relative_path + ".dice"
    absolute_path = os.path.abspath(os.path.join(STDLIB_ROOT, relative_path))
    if os.path.commonpath([STDLIB_ROOT, absolute_path]) != STDLIB_ROOT:
        raise ValueError("stdlib path must stay within the bundled standard library")
    return relative_path, absolute_path


def _serialize_span(span):
    if span is None:
        return None
    return {
        "document": span.document.name,
        "start_index": span.start_index,
        "end_index": span.end_index,
        "start_line": span.start_line,
        "start_column": span.start_column,
        "end_line": span.end_line,
        "end_column": span.end_column,
        "line_text": span.line_text,
    }


def _serialize_error(error):
    if isinstance(error, DiagnosticError):
        return {
            "title": error.title,
            "message": error.message,
            "hint": error.hint,
            "formatted": format_diagnostic(error),
            "span": _serialize_span(error.span),
        }
    return {
        "title": "error",
        "message": str(error),
        "hint": None,
        "formatted": "error: {}".format(error),
        "span": None,
    }


def _count_report_panels(report_payload):
    if not isinstance(report_payload, dict):
        return 0
    report = report_payload.get("report")
    if not isinstance(report, dict):
        return 0
    count = 1 if report.get("hero") is not None else 0
    count += sum(len(row) for row in report.get("rows", ()))
    return count


class WebExecutor(ExactExecutor):
    def __init__(self, render_config=None):
        config = render_config if render_config is not None else RenderConfig()
        super().__init__(render_config=config.with_backend("json"))
        self.render_reports = []

    def render(self, path=None, format=None, dpi=None):
        rendered = super().render(path=path, format="json" if format is None else format, dpi=dpi)
        if path is None:
            payload = json.loads(rendered)
        else:
            with open(rendered, encoding="utf-8") as handle:
                payload = json.load(handle)
        self.render_reports.append(payload)
        return "__dice_web_render__"

    def set_render_backend(self, backend):
        del backend
        self.render_config = self.render_config.with_backend("json")
        return "json"


def _sample_relative_path(path):
    normalized = _normalize_workspace_path(path)
    if SAMPLE_ROOT is None:
        raise ValueError("No bundled samples are available")
    absolute_path = os.path.abspath(os.path.join(SAMPLE_ROOT, normalized))
    if os.path.commonpath([SAMPLE_ROOT, absolute_path]) != SAMPLE_ROOT:
        raise ValueError("sample path must stay within the bundled sample directory")
    return normalized, absolute_path


def _render_axis_name(axis, index):
    return axis.get("name") or "Sweep {}".format(index + 1)


def _distribution_is_scalar(entries):
    return (
        len(entries) == 1
        and entries[0]["probability"] == 1
        and _is_numeric(entries[0]["outcome"])
    )


def _distribution_scalar_value(entries):
    return entries[0]["outcome"]


def _all_scalar_cells(payload):
    return all(_distribution_is_scalar(cell["distribution"]) for cell in payload["cells"])


def _distribution_is_bernoulli(entries):
    outcomes = {entry["outcome"] for entry in entries}
    return bool(outcomes) and outcomes.issubset({0, 1})


def _distribution_mean_value(entries):
    return sum(entry["outcome"] * entry["probability"] for entry in entries if _is_numeric(entry["outcome"]))


def _all_bernoulli_cells(payload):
    return all(_distribution_is_bernoulli(cell["distribution"]) for cell in payload["cells"])


def _cell_lookup(payload):
    lookup = {}
    for cell in payload["cells"]:
        key = tuple(entry["value"] for entry in cell["coordinates"])
        lookup[key] = cell
    return lookup


def _probability_scale(probability_mode):
    return 100.0 if probability_mode == "percent" else 1.0


def _render_y_label(kind, probability_mode):
    if kind in ("bar", "heatmap_distribution"):
        return "Probability (%)" if probability_mode == "percent" else "Probability"
    return "Value"


def _render_payload_from_distributions(payload, probability_mode):
    axes = payload["axes"]
    cells = payload["cells"]
    scale = _probability_scale(probability_mode)
    if not axes:
        distribution = cells[0]["distribution"]
        return {
            "kind": "bar",
            "spec": {
                "kind": "bar",
                "x_label": "Outcome",
                "y_label": _render_y_label("bar", probability_mode),
                "series_labels": [],
            },
            "categories": [entry["outcome"] for entry in distribution],
            "series": [
                {
                    "name": "Probability",
                    "values": [_round_numeric(entry["probability"] * scale, 6) for entry in distribution],
                }
            ],
        }
    if len(axes) == 1:
        axis = axes[0]
        if _all_scalar_cells(payload):
            lookup = _cell_lookup(payload)
            return {
                "kind": "line",
                "spec": {
                    "kind": "line",
                    "x_label": _render_axis_name(axis, 0),
                    "y_label": "Value",
                    "series_labels": [],
                },
                "categories": list(axis["values"]),
                "series": [
                    {
                        "name": "Value",
                        "values": [
                            _distribution_scalar_value(lookup[(x_value,)]["distribution"])
                            for x_value in axis["values"]
                        ],
                    }
                ],
            }
        if _all_bernoulli_cells(payload):
            lookup = _cell_lookup(payload)
            return {
                "kind": "line",
                "spec": {
                    "kind": "line",
                    "x_label": _render_axis_name(axis, 0),
                    "y_label": _render_y_label("bar", probability_mode),
                    "series_labels": [],
                },
                "categories": list(axis["values"]),
                "series": [
                    {
                        "name": "Probability",
                        "values": [
                            _round_numeric(_distribution_mean_value(lookup[(x_value,)]["distribution"]) * scale, 6)
                            for x_value in axis["values"]
                        ],
                    }
                ],
            }
        lookup = _cell_lookup(payload)
        outcomes = _ordered_labels(
            {
                entry["outcome"]
                for cell in cells
                for entry in cell["distribution"]
            }
        )
        matrix = []
        for outcome in outcomes:
            row = []
            for x_value in axis["values"]:
                distribution = lookup[(x_value,)]["distribution"]
                probability = next(
                    (
                        entry["probability"]
                        for entry in distribution
                        if entry["outcome"] == outcome
                    ),
                    0,
                )
                row.append(_round_numeric(probability * scale, 6))
            matrix.append(row)
        return {
            "kind": "heatmap_distribution",
            "spec": {
                "kind": "heatmap_distribution",
                "x_label": _render_axis_name(axis, 0),
                "y_label": "Outcome",
                "series_labels": [],
            },
            "x_values": list(axis["values"]),
            "y_values": outcomes,
            "matrix": matrix,
            "color_label": _render_y_label("heatmap_distribution", probability_mode),
        }
    if len(axes) == 2 and (_all_scalar_cells(payload) or _all_bernoulli_cells(payload)):
        y_axis = axes[0]
        x_axis = axes[1]
        lookup = _cell_lookup(payload)
        matrix = []
        for y_value in y_axis["values"]:
            row = []
            for x_value in x_axis["values"]:
                distribution = lookup[(y_value, x_value)]["distribution"]
                if _distribution_is_scalar(distribution):
                    row.append(_distribution_scalar_value(distribution))
                else:
                    row.append(_round_numeric(_distribution_mean_value(distribution) * scale, 6))
            matrix.append(row)
        return {
            "kind": "heatmap_scalar",
            "spec": {
                "kind": "heatmap_scalar",
                "x_label": _render_axis_name(x_axis, 1),
                "y_label": _render_axis_name(y_axis, 0),
                "series_labels": [],
            },
            "x_values": list(x_axis["values"]),
            "y_values": list(y_axis["values"]),
            "matrix": matrix,
            "color_label": "Value" if _all_scalar_cells(payload) else _render_y_label("heatmap_distribution", probability_mode),
        }
    return None


def render_payload(result, settings=None):
    settings = {} if settings is None else dict(settings)
    probability_mode = settings.get("probability_mode", "percent")
    payload = result.get("result", result) if isinstance(result, dict) else result
    if not isinstance(payload, dict):
        return None
    if payload.get("type") not in ("distributions", "distribution"):
        return None
    if payload.get("type") == "distribution":
        payload = {"type": "distributions", "axes": [], "cells": [{"coordinates": [], "distribution": payload["distribution"]}]}
    return _render_payload_from_distributions(payload, probability_mode)


def _stdlib_imports():
    imports = []
    for root, _dirs, filenames in os.walk(STDLIB_ROOT):
        for filename in filenames:
            if not filename.endswith(".dice"):
                continue
            relative_path = os.path.relpath(os.path.join(root, filename), STDLIB_ROOT)
            import_name = os.path.splitext(relative_path)[0].replace(os.sep, "/")
            imports.append("std:" + import_name)
    return sorted(imports)


def list_symbols():
    executor = ExactExecutor(render_config=RenderConfig.from_mode("nonblocking"))
    builtins = []
    for name in sorted(executor.functions):
        entry = executor.functions[name]
        parameters = getattr(entry, "parameters", ())
        builtins.append(
            {
                "name": name,
                "arity": len(parameters),
                "variadic": getattr(entry, "variadic", False),
                "parameters": [parameter.name for parameter in parameters],
            }
        )
    return {
        "keywords": sorted(COMPLETION_KEYWORDS),
        "builtins": builtins,
        "stdlib_imports": _stdlib_imports(),
    }


def list_samples():
    entries = []

    if SAMPLE_ROOT is not None:
        for sample_root_name in RUNNABLE_SAMPLE_ROOTS:
            runnable_root = os.path.join(SAMPLE_ROOT, sample_root_name)
            if not os.path.isdir(runnable_root):
                continue
            for root, dirs, filenames in os.walk(runnable_root):
                dirs.sort()
                for filename in sorted(filenames):
                    if not filename.endswith(".dice"):
                        continue
                    if os.path.basename(root) == "lib":
                        continue
                    absolute_path = os.path.join(root, filename)
                    relative_path = os.path.relpath(absolute_path, SAMPLE_ROOT).replace(os.sep, "/")
                    parent = os.path.dirname(relative_path)
                    entries.append(
                        {
                            "path": relative_path,
                            "name": os.path.splitext(filename)[0].replace("_", " "),
                            "group": f"{SAMPLE_GROUP_LABEL}/{parent}",
                            "kind": "sample",
                        }
                    )

    for import_name in _stdlib_imports():
        entries.append(
            {
                "path": import_name,
                "name": import_name.removeprefix("std:"),
                "group": "Standard Library",
                "kind": "stdlib",
            }
        )

    return entries


def load_sample(path):
    if path.startswith("std:"):
        relative_path, absolute_path = _stdlib_path(path)
        if not os.path.isfile(absolute_path):
            raise ValueError("Unknown sample {}".format(path))
        files = {}
        for import_name in _stdlib_imports():
            stdlib_relative, stdlib_absolute = _stdlib_path(import_name)
            with open(stdlib_absolute, encoding="utf-8") as handle:
                files[stdlib_relative] = handle.read()
        return {
            "path": path,
            "source_path": relative_path,
            "source": files[relative_path],
            "files": files,
        }

    relative_path, absolute_path = _sample_relative_path(path)
    if not os.path.isfile(absolute_path):
        raise ValueError("Unknown sample {}".format(path))
    top_level = relative_path.split("/", 1)[0]
    sample_root = os.path.join(SAMPLE_ROOT, top_level)
    files = {}
    for root, dirs, filenames in os.walk(sample_root):
        dirs.sort()
        for filename in sorted(filenames):
            if not (filename.endswith(".dice") or filename.endswith(".py")):
                continue
            file_path = os.path.join(root, filename)
            relative_file_path = os.path.relpath(file_path, SAMPLE_ROOT).replace(os.sep, "/")
            with open(file_path, encoding="utf-8") as handle:
                files[relative_file_path] = handle.read()
    return {
        "path": relative_path,
        "source_path": relative_path,
        "source": files[relative_path],
        "files": files,
    }


def _parse_program(text, *, source_name):
    return DiceParser(Lexer(text, source_name=source_name)).parse()


def _identifier_context(source, cursor):
    line_start = source.rfind("\n", 0, cursor) + 1
    line_buffer = source[line_start:cursor]
    start = cursor
    end = cursor
    while start > line_start and source[start - 1] in IMPORT_PATH_CHARS:
        start -= 1
    while end < len(source) and source[end] in IMPORT_PATH_CHARS:
        end += 1
    return {
        "text": source[start:cursor],
        "line_buffer": line_buffer,
        "begidx": start - line_start,
        "endidx": cursor - line_start,
        "from": start,
        "to": end,
    }


def _truncate_to_complete_program(source_prefix):
    candidates = [source_prefix]
    seen = {source_prefix}
    current = source_prefix
    while current:
        boundary = max(current.rfind("\n"), current.rfind(";"))
        if boundary < 0:
            break
        current = current[:boundary]
        if current in seen:
            break
        candidates.append(current)
        seen.add(current)
    candidates.append("")
    return candidates


def _register_top_level_names(interpreter, ast, seen_imports=None):
    seen_imports = set() if seen_imports is None else seen_imports

    def visit_node(node, current_dir):
        node_type = type(node).__name__
        if node_type == "VarOp" and node.op.type == SEMI:
            for child in node.nodes:
                visit_node(child, current_dir)
            return
        if node_type == "FunctionDef":
            try:
                interpreter.register_function_definition(node)
            except DiagnosticError:
                pass
            return
        if node_type == "BinOp" and node.op.type == ASSIGN:
            interpreter.global_scope[node.left.value] = 0
            return
        if node_type != "Import":
            return
        previous_dir = interpreter.current_dir
        interpreter.current_dir = current_dir
        try:
            resolved_path = interpreter._resolve_import_path(node.path.value)
        except DiagnosticError:
            interpreter.current_dir = previous_dir
            return
        interpreter.current_dir = previous_dir
        if resolved_path in seen_imports or not os.path.isfile(resolved_path):
            return
        seen_imports.add(resolved_path)
        try:
            with open(resolved_path, encoding="utf-8") as handle:
                imported_text = handle.read()
            imported_ast = _parse_program(imported_text, source_name=resolved_path)
        except (OSError, LexerError, ParserError):
            return
        visit_node(imported_ast, os.path.dirname(resolved_path))

    visit_node(ast, interpreter.current_dir)


def _completion_options(interpreter, suggestions):
    options = []
    seen = set()
    for suggestion in suggestions:
        if suggestion in seen:
            continue
        seen.add(suggestion)
        option = {"label": suggestion}
        if suggestion in COMPLETION_KEYWORDS:
            option["type"] = "keyword"
        elif suggestion in interpreter.executor.functions or suggestion in interpreter.callable_scope:
            option["type"] = "function"
        elif suggestion.startswith("std:") or "/" in suggestion:
            option["type"] = "module"
        else:
            option["type"] = "variable"
        entry = interpreter.executor.functions.get(suggestion)
        if entry is None:
            entry = interpreter.callable_scope.get(suggestion)
        parameters = getattr(entry, "parameters", None)
        if getattr(entry, "variadic", False):
            option["detail"] = "variadic"
        elif parameters is not None:
            option["detail"] = "{} args".format(len(parameters))
        options.append(option)
    return options


def complete(source, cursor, files=None, settings=None):
    settings = {} if settings is None else dict(settings)
    cursor = max(0, min(int(cursor), len(source)))
    source_path = settings.get("source_path", DEFAULT_SOURCE_PATH)
    with tempfile.TemporaryDirectory(prefix="dice-web-complete-") as workspace:
        normalized_source_path = _write_workspace_files(
            workspace,
            source,
            files=files,
            source_path=source_path,
        )
        absolute_source_path = os.path.join(workspace, normalized_source_path)
        context = _identifier_context(source, cursor)
        interpreter = Interpreter(
            None,
            current_dir=os.path.dirname(absolute_source_path),
            render_config=RenderConfig.from_mode("nonblocking"),
        )
        completion_source = source[:context["from"]]
        for candidate in _truncate_to_complete_program(completion_source):
            if not candidate.strip():
                break
            try:
                ast = _parse_program(candidate, source_name=absolute_source_path)
            except (LexerError, ParserError):
                continue
            _register_top_level_names(interpreter, ast)
            break
        suggestions = interpreter.complete(
            context["text"],
            line_buffer=context["line_buffer"],
            begidx=context["begidx"],
            endidx=context["endidx"],
        )
        return {
            "from": context["from"],
            "to": context["to"],
            "options": _completion_options(interpreter, suggestions),
        }


def evaluate(source, files=None, settings=None):
    settings = {} if settings is None else dict(settings)
    roundlevel = int(settings.get("roundlevel", DEFAULT_ROUNDLEVEL))
    probability_mode = settings.get("probability_mode", "raw")
    text_probability_mode = settings.get("text_probability_mode", "percent")
    source_path = settings.get("source_path", DEFAULT_SOURCE_PATH)
    with tempfile.TemporaryDirectory(prefix="dice-web-eval-") as workspace:
        normalized_source_path = _write_workspace_files(
            workspace,
            source,
            files=files,
            source_path=source_path,
        )
        absolute_source_path = os.path.join(workspace, normalized_source_path)
        current_dir = os.path.dirname(absolute_source_path)
        try:
            ast = _parse_program(source, source_name=absolute_source_path)
            executor = WebExecutor(
                render_config=RenderConfig.from_mode("nonblocking").with_probability_mode("percent")
            )
            interpreter = Interpreter(
                ast,
                current_dir=current_dir,
                render_config=executor.render_config,
                executor=executor,
            )
            result = interpreter.interpret()
        except Exception as error:
            return {"ok": False, "error": _serialize_error(error)}
        serialized = _serialize_result(
            result,
            roundlevel=roundlevel,
            probability_mode=probability_mode,
        )
        text = _format_result_text(
            result,
            roundlevel=roundlevel,
            probability_mode=text_probability_mode,
        )
        reports = list(executor.render_reports)
        if reports and serialized.get("type") == "string" and serialized.get("value") == "__dice_web_render__":
            panel_count = sum(_count_report_panels(report) for report in reports)
            serialized = {"type": "string", "value": "Rendered {} plot(s).".format(panel_count)}
            text = "Rendered {} plot(s).".format(panel_count)
        return {
            "ok": True,
            "text": text,
            "result": serialized,
            "reports": reports,
        }
