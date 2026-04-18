#!/usr/bin/env python3

"""Sweep-aware finite-measure and probability primitives for dice semantics."""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import wraps
import importlib
from itertools import product
from math import inf, isfinite, sqrt
import random
import re
from typing import Any, Generic, TypeVar

from diagnostics import RuntimeError as DiceRuntimeError

try:
    from math import comb
except ImportError:
    from math import factorial

    def comb(n, k):
        return factorial(n) / factorial(k) / factorial(n - k)


TRUE = 1
FALSE = 0
PROBABILITY_TOLERANCE = 1e-9
_renderer_modules = {}
_RENDERER_MODULE_NAMES = {
    "matplotlib": "viewer",
    "json": "jsonrenderer",
}
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_OMITTED = object()


def exception(message):
    raise DiceRuntimeError(message)


def runtime_error(message, hint=None):
    raise DiceRuntimeError(message, hint=hint)


@dataclass(frozen=True)
class RenderConfig:
    interactive_blocking: bool = True
    wait_for_figures_on_exit: bool = False
    probability_mode: str | None = None
    backend: str = "matplotlib"

    @classmethod
    def from_mode(cls, mode):
        normalized = _normalize_render_mode(mode)
        if normalized == "blocking":
            return cls(interactive_blocking=True, wait_for_figures_on_exit=False)
        if normalized == "nonblocking":
            return cls(interactive_blocking=False, wait_for_figures_on_exit=False)
        if normalized == "deferred":
            return cls(interactive_blocking=False, wait_for_figures_on_exit=True)
        runtime_error(
            "unknown render mode {}".format(mode),
            hint='Use "blocking", "nonblocking", or "deferred".',
        )

    def with_mode(self, mode):
        updated = RenderConfig.from_mode(mode)
        return replace(
            self,
            interactive_blocking=updated.interactive_blocking,
            wait_for_figures_on_exit=updated.wait_for_figures_on_exit,
        )

    def with_probability_mode(self, mode):
        return replace(self, probability_mode=_normalize_probability_mode(mode))

    def with_backend(self, backend):
        return replace(self, backend=_normalize_render_backend(backend))

    def mode_name(self):
        if self.interactive_blocking:
            return "blocking"
        if self.wait_for_figures_on_exit:
            return "deferred"
        return "nonblocking"

    def effective_probability_mode(self, default="percent"):
        return self.probability_mode if self.probability_mode is not None else default

    def probability_scale(self, default="percent"):
        return 100.0 if self.effective_probability_mode(default) == "percent" else 1.0

    def probability_axis_label(self, default="percent"):
        return "Probability (%)" if self.effective_probability_mode(default) == "percent" else "Probability"


def _normalize_render_mode(mode):
    if not isinstance(mode, str):
        runtime_error("render mode must be a string")
    return mode.strip().lower()


def _normalize_probability_mode(mode):
    if not isinstance(mode, str):
        runtime_error("probability mode must be a string")
    normalized = mode.strip().lower()
    if normalized not in ("percent", "raw"):
        runtime_error(
            "unknown probability mode {}".format(mode),
            hint='Use "percent" or "raw".',
        )
    return normalized


def _normalize_render_backend(backend):
    if not isinstance(backend, str):
        runtime_error("render backend must be a string")
    normalized = backend.strip().lower()
    if normalized not in _RENDERER_MODULE_NAMES:
        runtime_error(
            "unknown render backend {}".format(backend),
            hint='Use "matplotlib" or "json".',
        )
    return normalized


def _get_renderer(render_config=None):
    render_config = render_config if render_config is not None else RenderConfig()
    backend = _normalize_render_backend(render_config.backend)
    renderer = _renderer_modules.get(backend)
    if renderer is None:
        renderer = importlib.import_module(_RENDERER_MODULE_NAMES[backend])
        _renderer_modules[backend] = renderer
    return renderer


def wait_for_rendered_figures(render_config=None):
    renderer = _get_renderer(render_config)
    renderer.wait_for_rendered_figures(
        render_config=render_config if render_config is not None else RenderConfig()
    )


def _canonicalize_weighted_entries(entries):
    merged = {}
    order = []
    for outcome, weight in entries:
        if not isinstance(weight, (int, float)) or not isfinite(weight):
            runtime_error("weights must be finite numbers")
        if weight < 0:
            runtime_error("weights must be non-negative")
        if weight == 0:
            continue
        try:
            existing = merged.get(outcome, 0.0)
        except TypeError as error:
            runtime_error("measure outcomes must be hashable: {}".format(error))
        if outcome not in merged:
            order.append(outcome)
        merged[outcome] = existing + float(weight)
    return tuple((outcome, merged[outcome]) for outcome in order if merged[outcome] != 0)


def _is_identifier_key(key):
    return isinstance(key, str) and _IDENTIFIER_PATTERN.match(key) is not None


def _is_record_key(key):
    return isinstance(key, int) or _is_identifier_key(key)


def _format_runtime_key(key):
    if isinstance(key, int):
        return str(key)
    return key


def _format_runtime_literal(value):
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return '"{}"'.format(escaped)
    if isinstance(value, TupleValue) or isinstance(value, RecordValue):
        return str(value)
    return str(value)


@dataclass(frozen=True, init=False)
class TupleValue:
    items: tuple[object, ...]

    def __init__(self, items=()):
        object.__setattr__(self, "items", tuple(items))

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)

    def __getitem__(self, index):
        return self.items[index]

    def __repr__(self):
        if not self.items:
            return "()"
        if len(self.items) == 1:
            return "({},)".format(_format_runtime_literal(self.items[0]))
        return "({})".format(", ".join(_format_runtime_literal(item) for item in self.items))

    __str__ = __repr__


@dataclass(frozen=True, init=False)
class RecordValue:
    entries: tuple[tuple[object, object], ...]

    def __init__(self, entries):
        normalized = []
        seen = set()
        for key, value in entries:
            if not _is_record_key(key):
                runtime_error("record keys must be identifiers or integers")
            if key in seen:
                runtime_error("duplicate record key {}".format(key))
            seen.add(key)
            normalized.append((key, value))
        if not normalized:
            runtime_error("records require at least one entry")
        object.__setattr__(self, "entries", tuple(normalized))

    def __iter__(self):
        return iter(self.entries)

    def items(self):
        return self.entries

    def keys(self):
        return tuple(key for key, _ in self.entries)

    def values(self):
        return tuple(value for _, value in self.entries)

    def __getitem__(self, key):
        for entry_key, value in self.entries:
            if entry_key == key:
                return value
        raise KeyError(key)

    def __repr__(self):
        return "({})".format(
            ", ".join("{}: {}".format(_format_runtime_key(key), _format_runtime_literal(value)) for key, value in self.entries)
        )

    __str__ = __repr__


@dataclass(frozen=True, init=False)
class FiniteMeasure:
    entries: tuple[tuple[object, float], ...]
    total_weight: float

    def __init__(self, entries=None):
        normalized_entries = _canonicalize_weighted_entries(entries.items() if isinstance(entries, dict) else (entries or ()))
        object.__setattr__(self, "entries", normalized_entries)
        object.__setattr__(self, "total_weight", sum(weight for _, weight in normalized_entries))

    def __repr__(self):
        return str(dict(self.entries))

    def __getitem__(self, key):
        for outcome, weight in self.entries:
            if outcome == key:
                return weight
        return 0

    def __iter__(self):
        return iter(self.entries)

    def items(self):
        return self.entries

    def keys(self):
        return tuple(outcome for outcome, _ in self.entries)

    def weights(self):
        return tuple(weight for _, weight in self.entries)

    def is_normalized(self):
        return abs(self.total_weight - 1.0) <= PROBABILITY_TOLERANCE and self.total_weight > 0

    def total_probability(self):
        return self.total_weight

    def average(self):
        total = 0.0
        for outcome, probability in self.entries:
            if not isinstance(outcome, (int, float)):
                runtime_error(
                    "mean expects numeric outcomes, got {}".format(type(outcome)),
                    hint="Apply mean only to numeric distributions.",
                )
            total += outcome * probability
        return total

    def variance(self):
        mean_value = self.average()
        total = 0.0
        for outcome, probability in self.entries:
            if not isinstance(outcome, (int, float)):
                runtime_error(
                    "variance expects numeric outcomes, got {}".format(type(outcome)),
                    hint="Apply variance only to numeric distributions.",
                )
            total += ((outcome - mean_value) ** 2) * probability
        return total

    def stddev(self):
        return sqrt(self.variance())

    def map_support(self, mapper):
        mapped = []
        for outcome, weight in self.entries:
            mapped.append((mapper(outcome), weight))
        if isinstance(self, Distribution):
            return Distribution(mapped)
        return FiniteMeasure(mapped)


@dataclass(frozen=True, init=False)
class Distribution(FiniteMeasure):
    def __init__(self, entries=None):
        super().__init__(entries)
        if self.total_weight <= 0:
            runtime_error("distributions must have positive total probability")
        if abs(self.total_weight - 1.0) > PROBABILITY_TOLERANCE:
            runtime_error(
                "distribution must be normalized, got total probability {}".format(self.total_weight)
            )


@dataclass(frozen=True)
class SweepAxis:
    key: str
    name: str
    values: tuple


class SweepValues:
    counter = 0

    def __init__(self, values, name=None):
        deduped = tuple(dict.fromkeys(values))
        if not deduped:
            runtime_error("sweeps require at least one value")
        self.values = deduped
        self.name = name
        self.key = "sweep_{}".format(SweepValues.counter)
        SweepValues.counter += 1

    def axis(self):
        axis_name = self.name if self.name else self.key
        return SweepAxis(self.key, axis_name, self.values)

    def renamed(self, name):
        renamed = SweepValues(self.values, name=name)
        renamed.key = self.key
        return renamed

    def __repr__(self):
        label = "{}:".format(self.name) if self.name else ""
        return "[{}{}]".format(label, ", ".join(str(value) for value in self.values))


T = TypeVar("T")


@dataclass(frozen=True, init=False)
class Sweep(Generic[T]):
    axes: tuple[SweepAxis, ...]
    _cells: tuple[tuple[tuple[object, ...], T], ...]

    def __init__(self, axes=None, cells=None):
        axes = tuple(axes or ())
        raw_cells = cells if cells is not None else {(): None}
        if isinstance(raw_cells, dict):
            items = tuple(raw_cells.items())
        else:
            items = tuple(raw_cells)
        if not items:
            items = (((), None),)
        object.__setattr__(self, "axes", axes)
        object.__setattr__(self, "_cells", items)

    @staticmethod
    def scalar(value):
        return Sweep((), {(): value})

    @staticmethod
    def from_values(sweep_values: SweepValues):
        axis = sweep_values.axis()
        return Sweep((axis,), {(value,): value for value in axis.values})

    @property
    def cells(self):
        return dict(self._cells)

    def items(self):
        return self._cells

    def values(self):
        return tuple(value for _, value in self._cells)

    def is_unswept(self):
        return len(self.axes) == 0

    def only_value(self):
        return dict(self._cells)[()]

    def only_distribution(self):
        return self.only_value()

    def lookup(self, combined_axes, coordinates):
        if self.is_unswept():
            return self.only_value()
        index_by_key = {axis.key: idx for idx, axis in enumerate(combined_axes)}
        local_coordinates = tuple(coordinates[index_by_key[axis.key]] for axis in self.axes)
        return dict(self._cells)[local_coordinates]

    def with_cells(self, cells):
        return Sweep(self.axes, cells)

    def round_probabilities(self, digits):
        if not digits:
            return self
        updated = {}
        for coordinates, value in self._cells:
            if isinstance(value, FiniteMeasure):
                rounded_entries = [(outcome, round(weight, digits)) for outcome, weight in value.items()]
                if isinstance(value, Distribution):
                    if rounded_entries:
                        total = sum(weight for _, weight in rounded_entries)
                        diff = round(1.0 - total, digits)
                        last_outcome, last_weight = rounded_entries[-1]
                        rounded_entries[-1] = (last_outcome, round(last_weight + diff, digits))
                    updated_value = Distribution(rounded_entries)
                else:
                    updated_value = FiniteMeasure(rounded_entries)
            else:
                updated_value = round(value, digits) if isinstance(value, float) else value
            updated[coordinates] = updated_value
        return Sweep(self.axes, updated)

    def __repr__(self):
        if self.is_unswept():
            return repr(self.only_value())
        rendered = {}
        for coordinates, value in self._cells:
            if len(self.axes) == 1:
                axis = self.axes[0]
                key = coordinates[0] if axis.name.startswith("sweep_") else "{}={}".format(axis.name, coordinates[0])
            else:
                key = tuple(
                    "{}={}".format(axis.name if not axis.name.startswith("sweep_") else axis.key, coordinate)
                    for axis, coordinate in zip(self.axes, coordinates)
                )
            rendered[key] = value
        return str(rendered)


Distrib = Distribution
Distributions = Sweep


@dataclass(frozen=True)
class ChartSpec:
    intent: str
    payload: object
    x_label: str | None = None
    y_label: str | None = None
    title: str | None = None
    width_override: str | None = None


@dataclass(frozen=True)
class ReportBlock:
    kind: str
    value: object


@dataclass(frozen=True)
class ReportSpec:
    title: str | None = None
    hero: ChartSpec | None = None
    blocks: tuple[ReportBlock, ...] = ()

    def is_empty(self):
        return self.title is None and self.hero is None and not self.blocks


@dataclass(frozen=True)
class RenderPlan:
    kind: str
    payload: object
    width_class: str


class PanelWidthClass:
    NARROW = "narrow"
    WIDE = "wide"


def _require_numeric(value, opname):
    if not isinstance(value, (int, float)):
        runtime_error(
            "{} expects numeric outcomes, got {}".format(opname, type(value)),
            hint="Convert the expression to numbers before using {}.".format(opname),
        )


def _require_int(value, opname):
    if not isinstance(value, int):
        runtime_error(
            "{} expects integer outcomes, got {}".format(opname, type(value)),
            hint="Dice counts, sides, and indexes must be integers.",
        )


def _require_keep_count(n, keep, opname):
    _require_int(n, opname)
    _require_int(keep, opname)
    if keep < 0 or keep > n:
        runtime_error(
            "{} expects 0 <= keep <= count".format(opname),
            hint="Examples: 4d6h3 keeps 3 of 4 dice, and 3d20l1 keeps 1 of 3 dice.",
        )


def _ordered_numeric_outcomes(distrib, opname):
    outcomes = list(distrib.keys())
    for outcome in outcomes:
        _require_numeric(outcome, opname)
    return tuple(sorted(outcomes))


def _deterministic_distribution(value):
    return Distribution(((value, 1.0),))


def _coerce_scalar(value):
    if isinstance(value, (int, float, str, TupleValue, RecordValue, FiniteMeasure, SweepValues, ChartSpec, ReportSpec)):
        return value
    runtime_error("unsupported runtime value {}".format(type(value)))


def _coerce_to_measure_cell(value):
    if isinstance(value, FiniteMeasure):
        return value
    if isinstance(value, (int, float, str, TupleValue, RecordValue)):
        return FiniteMeasure(((value, 1.0),))
    runtime_error("expected a finite measure-compatible value, got {}".format(type(value)))


def _coerce_to_distribution_cell(value):
    if isinstance(value, Distribution):
        return value
    if isinstance(value, FiniteMeasure):
        runtime_error(
            "expected a normalized distribution here",
            hint="Normalize a finite measure with d{...} before using it probabilistically.",
        )
    if isinstance(value, (int, float, str, TupleValue, RecordValue)):
        return _deterministic_distribution(value)
    runtime_error("expected a distribution-compatible value, got {}".format(type(value)))


def _coerce_value_to_sweep(value):
    if isinstance(value, Sweep):
        return value
    if isinstance(value, SweepValues):
        return Sweep.from_values(value)
    return Sweep.scalar(value)


def _runtime_type_name(value):
    if isinstance(value, TupleValue):
        return "tuple"
    if isinstance(value, RecordValue):
        return "record"
    if isinstance(value, Distribution):
        return "Distribution"
    if isinstance(value, FiniteMeasure):
        return "FiniteMeasure"
    if isinstance(value, SweepValues):
        return "SweepValues"
    if isinstance(value, Sweep):
        cell_type_names = tuple(dict.fromkeys(_runtime_type_name(cell) for cell in value.values()))
        if len(cell_type_names) == 1:
            return "Sweep[{}]".format(cell_type_names[0])
        return "Sweep[mixed:{}]".format(", ".join(cell_type_names))
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    runtime_error("unsupported runtime value {}".format(type(value)))


def runtime_type(value):
    return _runtime_type_name(value)


def _runtime_shape_axis_entries(axes):
    entries = []
    unnamed_count = 0
    for axis in axes:
        if axis.name == axis.key or axis.name.startswith("sweep_"):
            unnamed_count += 1
            label = "<unnamed{}>".format(unnamed_count)
        else:
            label = axis.name
        entries.append("{}: {}".format(label, repr(axis.values)))
    return entries


def runtime_shape(value):
    if isinstance(value, SweepValues):
        return "[{}]".format(", ".join(_runtime_shape_axis_entries((value.axis(),))))
    if isinstance(value, Sweep):
        return "[{}]".format(", ".join(_runtime_shape_axis_entries(value.axes)))
    return "[]"


def _coerce_to_measure_sweep(value):
    sweep = _coerce_value_to_sweep(value)
    return Sweep(sweep.axes, {coordinates: _coerce_to_measure_cell(cell) for coordinates, cell in sweep.items()})


def _coerce_to_distributions(value):
    sweep = _coerce_value_to_sweep(value)
    return Sweep(sweep.axes, {coordinates: _coerce_to_distribution_cell(cell) for coordinates, cell in sweep.items()})


def _union_axes(sweeps):
    axes = []
    seen = set()
    for sweep in sweeps:
        for axis in sweep.axes:
            if axis.key not in seen:
                axes.append(axis)
                seen.add(axis.key)
    return tuple(axes)


def _lookup_projected(axes, cells, combined_axes, coordinates, default):
    if not axes:
        return cells.get((), default)
    index_by_key = {axis.key: idx for idx, axis in enumerate(combined_axes)}
    local_coordinates = tuple(coordinates[index_by_key[axis.key]] for axis in axes)
    return cells.get(local_coordinates, default)


def _coordinates_space(axes):
    return [()] if not axes else product(*(axis.values for axis in axes))


def _lift_cellwise(function, *args):
    sweeps = [_coerce_value_to_sweep(arg) for arg in args]
    combined_axes = _union_axes(sweeps)
    cells = {}
    for coordinates in _coordinates_space(combined_axes):
        projected = [sweep.lookup(combined_axes, coordinates) for sweep in sweeps]
        cells[coordinates] = function(*projected)
    return Sweep(combined_axes, cells)


def lift_sweeps(function):
    @wraps(function)
    def wrapped(*args):
        return _lift_cellwise(
            lambda *cells: function(*[_coerce_to_distribution_cell(cell) for cell in cells]),
            *args
        )

    return wrapped


def _deterministic_numeric_value(value, opname, *, allow_float=True):
    if isinstance(value, (int, float)):
        result = value
    elif isinstance(value, Distribution):
        items = list(value.items())
        if len(items) != 1 or abs(items[0][1] - 1.0) > PROBABILITY_TOLERANCE:
            runtime_error("{} expects a deterministic scalar here".format(opname))
        result = items[0][0]
    else:
        runtime_error("{} expects a deterministic scalar here".format(opname))

    if not allow_float and not isinstance(result, int):
        runtime_error("{} expects an integer here".format(opname))
    _require_numeric(result, opname)
    return result


def _bool_mass(condition):
    invalid = [outcome for outcome in condition.keys() if outcome not in (TRUE, FALSE)]
    if invalid:
        runtime_error(
            "branching expects Bernoulli outcomes 0 or 1, got {}".format(invalid),
            hint="Use a comparison like 'd20 >= 15' or convert the guard to 0 or 1 before '->'.",
        )
    return condition[TRUE], condition[FALSE]


def _sample_from_distribution(distrib, rng=None):
    total = distrib.total_weight
    if total <= 0:
        runtime_error("sampling expects a non-empty normalized distribution")
    if abs(total - 1.0) > PROBABILITY_TOLERANCE:
        runtime_error("sampling expects a normalized distribution")

    rng = rng if rng is not None else random
    threshold = rng.random()
    cumulative = 0.0
    last_outcome = None
    for outcome, probability in distrib.items():
        last_outcome = outcome
        cumulative += probability
        if threshold <= cumulative + PROBABILITY_TOLERANCE:
            return _deterministic_distribution(outcome)
    return _deterministic_distribution(last_outcome)


def _normalize_measure_cell(measure):
    measure = _coerce_to_measure_cell(measure)
    if measure.total_weight <= 0:
        runtime_error("cannot normalize an empty finite measure")
    entries = []
    for outcome, weight in measure.items():
        outer_probability = weight / measure.total_weight
        if isinstance(outcome, Distribution):
            for inner_outcome, inner_probability in outcome.items():
                entries.append((inner_outcome, outer_probability * inner_probability))
        else:
            entries.append((outcome, outer_probability))
    return Distribution(entries)


def _uniform_die_distribution(sides):
    _require_int(sides, "roll")
    if sides <= 0:
        runtime_error("roll expects positive die sides")
    return Distribution(((outcome, 1.0 / sides) for outcome in range(1, sides + 1)))


def _roll_plain(n, s):
    _require_int(n, "roll")
    _require_int(s, "roll")
    if n < 0 or s <= 0:
        runtime_error(
            "roll expects positive sides and a non-negative dice count",
            hint="Examples: 2d6, 1d20, or 0d6.",
        )
    if n == 0:
        return _deterministic_distribution(0)

    results = []
    for p in range(1, s * n + 1):
        c = (p - n) // s
        probability = sum(
            [(-1) ** k * comb(n, k) * comb(p - s * k - 1, n - 1) for k in range(0, c + 1)]
        ) / s ** n
        if probability != 0:
            results.append((p, probability))
    return Distribution(results)


def _distribution_support_transform(value, scalar, operator, opname):
    measure = _coerce_to_measure_cell(value)
    _require_numeric(scalar, opname)
    return measure.map_support(lambda outcome: operator(_require_support_numeric(outcome, opname), scalar))


def _require_support_numeric(outcome, opname):
    _require_numeric(outcome, opname)
    return outcome


def _pairwise_numeric(left, right, operator, opname):
    result = []
    for left_value, left_probability in left.items():
        _require_numeric(left_value, opname)
        for right_value, right_probability in right.items():
            _require_numeric(right_value, opname)
            result.append((operator(left_value, right_value), left_probability * right_probability))
    return Distribution(result)


def _is_structured_value(value):
    return isinstance(value, (TupleValue, RecordValue))


def _numeric_binary_cell(left, right, operator, opname, *, allow_measure_transform=True):
    left_is_raw_measure = isinstance(left, FiniteMeasure) and not isinstance(left, Distribution)
    right_is_raw_measure = isinstance(right, FiniteMeasure) and not isinstance(right, Distribution)
    if allow_measure_transform and left_is_raw_measure and not right_is_raw_measure:
        scalar = _deterministic_numeric_value(right, opname)
        return _distribution_support_transform(left, scalar, operator, opname)
    if allow_measure_transform and right_is_raw_measure and not left_is_raw_measure:
        scalar = _deterministic_numeric_value(left, opname)
        return _distribution_support_transform(right, scalar, lambda b, a: operator(a, b), opname)
    if left_is_raw_measure or right_is_raw_measure:
        runtime_error(
            "{} does not combine two finite measures directly".format(opname),
            hint="Normalize the measure with d{...} first or transform it with a scalar.",
        )
    return _pairwise_numeric(_coerce_to_distribution_cell(left), _coerce_to_distribution_cell(right), operator, opname)


def _compare_plain(left, right, operator):
    if operator not in ["<=", ">=", "<", ">", "==", "in"]:
        runtime_error("unknown operator {}".format(operator))
    result = []
    for left_value, left_probability in left.items():
        for right_value, right_probability in right.items():
            if _is_structured_value(left_value) or _is_structured_value(right_value):
                runtime_error(
                    "comparisons do not support tuple or record values yet",
                    hint="Use tuples and records as data values for now, not with comparison operators.",
                )
            comparison_true = False
            if operator == "<=":
                comparison_true = left_value <= right_value
            elif operator == ">=":
                comparison_true = left_value >= right_value
            elif operator == "<":
                comparison_true = left_value < right_value
            elif operator == ">":
                comparison_true = left_value > right_value
            elif operator == "==":
                comparison_true = left_value == right_value
            outcome = TRUE if comparison_true else FALSE
            result.append((outcome, left_probability * right_probability))
    return Distribution(result)


def _member_cell(left, right):
    left_distribution = _coerce_to_distribution_cell(left)
    domain = _coerce_to_measure_cell(right)
    support = set()
    for outcome, _ in domain.items():
        if _is_structured_value(outcome):
            runtime_error(
                "in does not support tuple or record values yet",
                hint="Use tuples and records as stored values for now, not with membership tests.",
            )
        if isinstance(outcome, Distribution):
            runtime_error(
                "in does not accept probabilistic members on the right-hand side yet",
                hint="Use a finite measure of scalar or nested finite-measure values.",
            )
        support.add(outcome)
    result = []
    for outcome, probability in left_distribution.items():
        if _is_structured_value(outcome):
            runtime_error(
                "in does not support tuple or record values yet",
                hint="Use tuples and records as stored values for now, not with membership tests.",
            )
        result.append((TRUE if outcome in support else FALSE, probability))
    return Distribution(result)


def _fixed_axis_distribution(axes, coordinates):
    return Sweep(axes, {coordinates: _deterministic_distribution(0)})


def _accumulate_distribution_contributions(contributions):
    if not contributions:
        return Sweep.scalar(_deterministic_distribution(0))
    combined_axes = _union_axes([Sweep(axes, cells) for axes, cells in contributions])
    cells = {}
    for coordinates in _coordinates_space(combined_axes):
        entries = []
        for axes, contribution_cells in contributions:
            projected = _lookup_projected(axes, contribution_cells, combined_axes, coordinates, None)
            if projected is None:
                continue
            for outcome, probability in projected.items():
                entries.append((outcome, probability))
        cells[coordinates] = Distribution(entries)
    return Sweep(combined_axes, cells)


def _resolve_axis_ref(axes, axis_ref, opname):
    if isinstance(axis_ref, int):
        if axis_ref < 0 or axis_ref >= len(axes):
            runtime_error(
                "{} could not find axis position {}".format(opname, axis_ref),
                hint="Use a position between 0 and {}.".format(max(len(axes) - 1, 0)),
            )
        return axes[axis_ref]
    if isinstance(axis_ref, str):
        matches = [axis for axis in axes if axis.name == axis_ref]
        if not matches:
            runtime_error(
                "{} could not find named axis {}".format(opname, axis_ref),
                hint='Use a named sweep axis like [AC:10..12] or a positional ref like 0.',
            )
        if len(matches) > 1:
            runtime_error("{} found multiple axes named {}".format(opname, axis_ref))
        return matches[0]
    runtime_error(
        "{} expects axis refs to be integers or strings".format(opname),
        hint='Use a positional axis like 0 or a named axis like "AC".',
    )


def _axis_spec_refs(value, opname):
    if isinstance(value, TupleValue):
        refs = tuple(value.items)
    elif isinstance(value, tuple):
        refs = tuple(value)
    else:
        refs = (value,)
    if not refs:
        runtime_error("{} expects at least one axis".format(opname))
    for ref in refs:
        if not isinstance(ref, (int, str)):
            runtime_error(
                "{} expects axis specs made of integers or strings".format(opname),
                hint='Use axis specs like "AC", 0, or ("AC", "PLAN").',
            )
    return refs


def _default_coordinate_key(axes, axis):
    if axis.name != axis.key and not axis.name.startswith("sweep_"):
        return axis.name
    return axes.index(axis)


def _resolve_axis_spec(axes, axes_value, opname):
    refs = _axis_spec_refs(axes_value, opname)
    resolved = []
    seen = set()
    for ref in refs:
        axis = _resolve_axis_ref(axes, ref, opname)
        if axis.key in seen:
            runtime_error("{} cannot mention the same axis twice".format(opname))
        seen.add(axis.key)
        resolved.append((axis, ref))
    return tuple(resolved)


def _selector_scalar(value, opname):
    if isinstance(value, Distribution):
        items = list(value.items())
        if len(items) != 1 or abs(items[0][1] - 1.0) > PROBABILITY_TOLERANCE:
            runtime_error("{} expects deterministic selector values".format(opname))
        value = items[0][0]
    if isinstance(value, (int, float, str, TupleValue, RecordValue)):
        return value
    runtime_error(
        "{} expects selector values to be deterministic scalars".format(opname),
        hint="Use deterministic sweep values or coordinate records when indexing.",
    )


def _filter_domain(value, opname):
    sweep = _coerce_value_to_sweep(value)
    if not sweep.is_unswept():
        runtime_error(
            "{} filters must use an unswept domain".format(opname),
            hint='Use a literal like {12, 16, 20} or a variable holding one.',
        )
    measure = _coerce_to_measure_cell(sweep.only_value())
    return {outcome for outcome, _ in measure.items()}


def _resolve_total_axis(value):
    if not value.axes or len(value.axes) != 1:
        runtime_error(
            "total expects exactly one named axis",
            hint="Call total on a single named sweep like [party:1, 2, 3].",
        )
    axis = value.axes[0]
    if axis.name == axis.key:
        runtime_error(
            "total expects exactly one named axis",
            hint="Name the sweep first, for example [party:1, 2, 3].",
        )
    return axis


def _apply_reduction(sweep, targets, opname, reducer):
    if not targets:
        if opname == "argmaxover":
            runtime_error("{} expects at least one sweep axis".format(opname))
        return sweep
    target_keys = {axis.key for axis, _ in targets}
    remaining_axes = tuple(axis for axis in sweep.axes if axis.key not in target_keys)
    grouped = {}
    for coordinates, cell in sweep.items():
        remaining_coordinates = tuple(
            coordinate for axis, coordinate in zip(sweep.axes, coordinates) if axis.key not in target_keys
        )
        target_coordinates = tuple(
            coordinate for axis, coordinate in zip(sweep.axes, coordinates) if axis.key in target_keys
        )
        grouped.setdefault(remaining_coordinates, []).append((target_coordinates, cell))
    cells = {}
    for remaining_coordinates, entries in grouped.items():
        reduced = reducer(targets, entries)
        reduced_sweep = _coerce_value_to_sweep(reduced)
        if not reduced_sweep.is_unswept():
            runtime_error("{} reduction produced an unexpected sweep".format(opname))
        cells[remaining_coordinates] = reduced_sweep.only_value()
    if not cells:
        return Sweep.scalar(0)
    return Sweep(remaining_axes, cells)


def _mean_reduce_cell(entries):
    cells = [cell for _, cell in entries]
    if all(isinstance(cell, (int, float)) for cell in cells):
        return sum(cells) / len(cells)

    normalized_entries = []
    probability_like = True
    for cell in cells:
        if isinstance(cell, (int, float)):
            measure = _deterministic_distribution(cell)
        elif isinstance(cell, Distribution):
            measure = cell
        elif isinstance(cell, FiniteMeasure):
            measure = cell
            probability_like = False
        else:
            runtime_error(
                "meanover expects numeric scalars or finite measures",
                hint="Apply meanover to numeric sweeps or sweeps of measure-like cells.",
            )
        for outcome, weight in measure.items():
            normalized_entries.append((outcome, weight / len(cells)))
    if probability_like:
        return Distribution(normalized_entries)
    return FiniteMeasure(normalized_entries)


def _max_key(cell, opname):
    if isinstance(cell, (int, float)):
        return cell
    if isinstance(cell, Distribution):
        return cell.average()
    runtime_error(
        "{} expects numeric scalars or distributions".format(opname),
        hint="Apply {} to deterministic numeric cells or distributions with numeric outcomes.".format(opname),
    )


def _argmax_record(targets, coordinates):
    return RecordValue((record_key, coordinate) for (_, record_key), coordinate in zip(targets, coordinates))


def _resolve_reduction_targets(sweep, axes_value, opname):
    if axes_value is _OMITTED:
        return tuple((axis, _default_coordinate_key(sweep.axes, axis)) for axis in sweep.axes)
    return _resolve_axis_spec(sweep.axes, axes_value, opname)


def _coordinate_selectors_from_record_value(value, opname):
    sweep = _coerce_value_to_sweep(value)
    if sweep.is_unswept():
        record = sweep.only_value()
        if not isinstance(record, RecordValue):
            runtime_error(
                "{} expects coordinate records inside []".format(opname),
                hint='Use a record like (PLAN: "gwm", LEVEL: 11).',
            )
        return [(key, Sweep.scalar(selector)) for key, selector in record.items()]

    selector_cells = {}
    expected_keys = None
    for coordinates, record in sweep.items():
        if not isinstance(record, RecordValue):
            runtime_error(
                "{} expects swept coordinate clauses to contain record values".format(opname),
                hint="Use argmaxover(...) or a sweep of record values here.",
            )
        keys = tuple(key for key, _ in record.items())
        if expected_keys is None:
            expected_keys = keys
        elif keys != expected_keys:
            runtime_error("{} expects swept coordinate records to use the same keys everywhere".format(opname))
        for key, selector in record.items():
            selector_cells.setdefault(key, {})[coordinates] = selector
    return [(key, Sweep(sweep.axes, cells)) for key, cells in selector_cells.items()]


def sweep_index(value, clauses):
    opname = "sweep indexing"
    sweep = _coerce_value_to_sweep(value)
    if not sweep.axes:
        runtime_error("{} expects a swept value".format(opname))

    keep_refs = []
    coordinate_specs = []
    filter_specs = []
    for clause in clauses:
        kind = clause["kind"]
        if kind == "coordinate":
            coordinate_specs.append((clause["key"], _coerce_value_to_sweep(clause["value"])))
            continue
        if kind == "filter":
            filter_specs.append((clause["key"], _filter_domain(clause["value"], opname)))
            continue
        raw_value = _coerce_value_to_sweep(clause["value"])
        if raw_value.is_unswept():
            literal = raw_value.only_value()
            if isinstance(literal, RecordValue):
                coordinate_specs.extend(_coordinate_selectors_from_record_value(literal, opname))
            else:
                keep_refs.extend(_axis_spec_refs(_selector_scalar(literal, opname), opname))
            continue
        coordinate_specs.extend(_coordinate_selectors_from_record_value(raw_value, opname))

    filter_by_key = {}
    for axis_ref, domain in filter_specs:
        axis = _resolve_axis_ref(sweep.axes, axis_ref, opname)
        if axis.key in filter_by_key:
            runtime_error("{} cannot filter the same axis twice".format(opname))
        filter_by_key[axis.key] = domain

    selector_by_key = {}
    for axis_ref, selector in coordinate_specs:
        axis = _resolve_axis_ref(sweep.axes, axis_ref, opname)
        if axis.key in selector_by_key or axis.key in filter_by_key:
            runtime_error("{} cannot mention the same axis twice".format(opname))
        selector_by_key[axis.key] = _coerce_value_to_sweep(selector)

    remaining_axes = []
    for axis in sweep.axes:
        if axis.key in selector_by_key:
            continue
        values = tuple(value for value in axis.values if value in filter_by_key.get(axis.key, set(axis.values)))
        if not values:
            runtime_error("{} removed every value from axis {}".format(opname, axis.name))
        remaining_axes.append(SweepAxis(axis.key, axis.name, values))

    if keep_refs:
        resolved_keep = [(_resolve_axis_ref(tuple(remaining_axes), axis_ref, opname), axis_ref) for axis_ref in keep_refs]
        keep_keys = [axis.key for axis, _ in resolved_keep]
        if len(set(keep_keys)) != len(keep_keys):
            runtime_error("{} cannot mention the same axis twice".format(opname))
        remaining_keys = [axis.key for axis in remaining_axes]
        if set(keep_keys) != set(remaining_keys):
            runtime_error(
                "{} cannot drop unfixed axes yet".format(opname),
                hint="Fix or reduce the omitted axes before reordering the remaining ones.",
            )
        output_axes = tuple(next(axis for axis in remaining_axes if axis.key == key) for key in keep_keys)
    else:
        output_axes = tuple(remaining_axes)

    output_axis_keys = {axis.key for axis in output_axes}
    for axis_key, selector in selector_by_key.items():
        for dependency_axis in selector.axes:
            if dependency_axis.key == axis_key:
                runtime_error("{} selectors cannot vary over the axis they select".format(opname))
            if dependency_axis.key not in output_axis_keys:
                runtime_error(
                    "{} selectors may only depend on axes that remain visible".format(opname),
                    hint="Keep the selector's dependency axes visible, or reduce them first.",
                )

    source_cells = sweep.cells
    output_index = {axis.key: idx for idx, axis in enumerate(output_axes)}
    cells = {}
    for output_coordinates in _coordinates_space(output_axes):
        source_coordinates = []
        for axis in sweep.axes:
            if axis.key in selector_by_key:
                selected_value = _selector_scalar(selector_by_key[axis.key].lookup(output_axes, output_coordinates), opname)
                if selected_value not in axis.values:
                    runtime_error(
                        "{} selected value {} outside axis {}".format(opname, selected_value, axis.name),
                    )
                source_coordinates.append(selected_value)
                continue
            source_coordinates.append(output_coordinates[output_index[axis.key]])
        cells[output_coordinates] = source_cells[tuple(source_coordinates)]
    return Sweep(output_axes, cells)


def choose(left, right):
    return member(left, right)


def choose_single(left, right):
    return member(left, right)


def res(condition, distrib):
    return reselse(condition, distrib, 0)


def mean(value):
    return _lift_cellwise(lambda cell: _deterministic_distribution(_coerce_to_distribution_cell(cell).average()), value)


def var(value):
    return _lift_cellwise(lambda cell: _deterministic_distribution(_coerce_to_distribution_cell(cell).variance()), value)


def std(value):
    return _lift_cellwise(lambda cell: _deterministic_distribution(_coerce_to_distribution_cell(cell).stddev()), value)


def sample(value):
    return _lift_cellwise(lambda cell: _sample_from_distribution(_coerce_to_distribution_cell(cell)), value)


def cum(value):
    def apply(cell):
        distrib = _coerce_to_distribution_cell(cell)
        cumulative = 0.0
        entries = []
        for outcome in _ordered_numeric_outcomes(distrib, "cum"):
            cumulative += distrib[outcome]
            entries.append((outcome, cumulative))
        return FiniteMeasure(entries)

    return _lift_cellwise(apply, value)


def surv(value):
    def apply(cell):
        distrib = _coerce_to_distribution_cell(cell)
        remaining = distrib.total_weight
        entries = []
        for outcome in _ordered_numeric_outcomes(distrib, "surv"):
            remaining -= distrib[outcome]
            entries.append((outcome, remaining))
        return FiniteMeasure(entries)

    return _lift_cellwise(apply, value)


def reselse(condition, distrib_if, distrib_else):
    def apply(condition_cell, if_cell, else_cell):
        condition_distribution = _coerce_to_distribution_cell(condition_cell)
        true_mass, false_mass = _bool_mass(condition_distribution)
        if_distribution = _coerce_to_distribution_cell(if_cell)
        else_distribution = _coerce_to_distribution_cell(else_cell)
        entries = []
        for outcome, probability in if_distribution.items():
            entries.append((outcome, true_mass * probability))
        for outcome, probability in else_distribution.items():
            entries.append((outcome, false_mass * probability))
        return Distribution(entries)

    return _lift_cellwise(apply, condition, distrib_if, distrib_else)


def reselsediv(condition, distrib):
    return reselse(condition, distrib, div(distrib, 2))


def reselsefloordiv(condition, distrib):
    return reselse(condition, distrib, floordiv(distrib, 2))


def roll(n, s):
    def apply(n_cell, s_cell):
        n_distribution = _coerce_to_distribution_cell(n_cell)
        s_distribution = _coerce_to_distribution_cell(s_cell)
        entries = []
        for dice_count, dice_count_probability in n_distribution.items():
            _require_int(dice_count, "roll")
            for sides, sides_probability in s_distribution.items():
                _require_int(sides, "roll")
                rolled = _roll_plain(dice_count, sides)
                outer = dice_count_probability * sides_probability
                for outcome, probability in rolled.items():
                    entries.append((outcome, outer * probability))
        return Distribution(entries)

    return _lift_cellwise(apply, n, s)


def rollsingle(dice):
    def apply(cell):
        if isinstance(cell, FiniteMeasure) and not isinstance(cell, Distribution):
            return _normalize_measure_cell(cell)
        sides_distribution = _coerce_to_distribution_cell(cell)
        entries = []
        for sides, probability in sides_distribution.items():
            _require_int(sides, "roll")
            die_distribution = _uniform_die_distribution(sides)
            for outcome, inner_probability in die_distribution.items():
                entries.append((outcome, probability * inner_probability))
        return Distribution(entries)

    return _lift_cellwise(apply, dice)


def rolladvantage(dice):
    def apply(cell):
        dice_distribution = _coerce_to_distribution_cell(cell)
        entries = []
        for dice_sides, dice_probability in dice_distribution.items():
            _require_int(dice_sides, "advantage")
            if dice_sides <= 0:
                runtime_error("can't roll advantage with non-positive dice sides")
            for outcome in range(1, dice_sides + 1):
                probability = 2 / dice_sides ** 2 * (outcome - 1) + (1 / dice_sides) ** 2
                entries.append((outcome, dice_probability * probability))
        return Distribution(entries)

    return _lift_cellwise(apply, dice)


def rolldisadvantage(dice):
    def apply(cell):
        dice_distribution = _coerce_to_distribution_cell(cell)
        entries = []
        for dice_sides, dice_probability in dice_distribution.items():
            _require_int(dice_sides, "disadvantage")
            if dice_sides <= 0:
                runtime_error("can't roll disadvantage with non-positive dice sides")
            for outcome in range(1, dice_sides + 1):
                probability = 2 / dice_sides ** 2 * (dice_sides - outcome) + (1 / dice_sides) ** 2
                entries.append((outcome, dice_probability * probability))
        return Distribution(entries)

    return _lift_cellwise(apply, dice)


def _rollhigh_plain(n, s, nh):
    _require_int(n, "rollhigh")
    _require_int(s, "rollhigh")
    _require_keep_count(n, nh, "rollhigh")
    if n < 0 or s <= 0 or nh < 0:
        runtime_error("rollhigh expects positive sides and non-negative counts")

    def count_children(sides, n_left, results, distrib):
        if n_left == 0:
            distrib.append((sum(results), 1))
            return
        for value in range(1, sides + 1):
            results_min = min(results)
            new_results = results.copy()
            if value > results_min:
                new_results[results.index(results_min)] = value
            count_children(sides, n_left - 1, new_results, distrib)

    combinations = []
    count_children(s, n, [0] * nh, combinations)
    counts = FiniteMeasure(combinations)
    total = s ** n
    return Distribution(((outcome, weight / total) for outcome, weight in counts.items()))


def _rolllow_plain(n, s, nl):
    _require_int(n, "rolllow")
    _require_int(s, "rolllow")
    _require_keep_count(n, nl, "rolllow")
    if n < 0 or s <= 0 or nl < 0:
        runtime_error("rolllow expects positive sides and non-negative counts")

    def count_children(sides, n_left, results, distrib):
        if n_left == 0:
            distrib.append((sum(results), 1))
            return
        for value in range(1, sides + 1):
            results_max = max(results)
            new_results = results.copy()
            if value < results_max:
                new_results[results.index(results_max)] = value
            count_children(sides, n_left - 1, new_results, distrib)

    combinations = []
    count_children(s, n, [inf] * nl, combinations)
    counts = FiniteMeasure(combinations)
    total = s ** n
    return Distribution(((outcome, weight / total) for outcome, weight in counts.items()))


def rollhigh(n, s, nh):
    def apply(n_cell, s_cell, keep_cell):
        n_distribution = _coerce_to_distribution_cell(n_cell)
        s_distribution = _coerce_to_distribution_cell(s_cell)
        keep_distribution = _coerce_to_distribution_cell(keep_cell)
        entries = []
        for dice_count, dice_count_probability in n_distribution.items():
            for sides, sides_probability in s_distribution.items():
                for keep_count, keep_probability in keep_distribution.items():
                    rolled = _rollhigh_plain(dice_count, sides, keep_count)
                    outer = dice_count_probability * sides_probability * keep_probability
                    for outcome, probability in rolled.items():
                        entries.append((outcome, outer * probability))
        return Distribution(entries)

    return _lift_cellwise(apply, n, s, nh)


def rolllow(n, s, nl):
    def apply(n_cell, s_cell, keep_cell):
        n_distribution = _coerce_to_distribution_cell(n_cell)
        s_distribution = _coerce_to_distribution_cell(s_cell)
        keep_distribution = _coerce_to_distribution_cell(keep_cell)
        entries = []
        for dice_count, dice_count_probability in n_distribution.items():
            for sides, sides_probability in s_distribution.items():
                for keep_count, keep_probability in keep_distribution.items():
                    rolled = _rolllow_plain(dice_count, sides, keep_count)
                    outer = dice_count_probability * sides_probability * keep_probability
                    for outcome, probability in rolled.items():
                        entries.append((outcome, outer * probability))
        return Distribution(entries)

    return _lift_cellwise(apply, n, s, nl)


def add(left, right):
    return _lift_cellwise(lambda a, b: _numeric_binary_cell(a, b, lambda x, y: x + y, "add"), left, right)


def sub(left, right):
    return _lift_cellwise(lambda a, b: _numeric_binary_cell(a, b, lambda x, y: x - y, "sub"), left, right)


def mul(left, right):
    return _lift_cellwise(lambda a, b: _numeric_binary_cell(a, b, lambda x, y: x * y, "mul"), left, right)


def div(left, right):
    def op(x, y):
        if y == 0:
            runtime_error("can't divide by zero")
        return x / y

    return _lift_cellwise(lambda a, b: _numeric_binary_cell(a, b, op, "div"), left, right)


def floordiv(left, right):
    def op(x, y):
        if y == 0:
            runtime_error("can't divide by zero")
        return x // y

    return _lift_cellwise(lambda a, b: _numeric_binary_cell(a, b, op, "floordiv"), left, right)


def neg(value):
    return mul(-1, value)


def greaterorequal(left, right):
    return _lift_cellwise(lambda a, b: _compare_plain(_coerce_to_distribution_cell(a), _coerce_to_distribution_cell(b), ">="), left, right)


def greater(left, right):
    return _lift_cellwise(lambda a, b: _compare_plain(_coerce_to_distribution_cell(a), _coerce_to_distribution_cell(b), ">"), left, right)


def equal(left, right):
    return _lift_cellwise(lambda a, b: _compare_plain(_coerce_to_distribution_cell(a), _coerce_to_distribution_cell(b), "=="), left, right)


def lessorequal(left, right):
    return _lift_cellwise(lambda a, b: _compare_plain(_coerce_to_distribution_cell(a), _coerce_to_distribution_cell(b), "<="), left, right)


def less(left, right):
    return _lift_cellwise(lambda a, b: _compare_plain(_coerce_to_distribution_cell(a), _coerce_to_distribution_cell(b), "<"), left, right)


def member(left, right):
    return _lift_cellwise(_member_cell, left, right)


def repeat_sum_with(add_function, count, value):
    count_sweep = _coerce_value_to_sweep(count)
    contributions = []
    for count_coordinates, count_cell in count_sweep.items():
        count_outcome = _deterministic_numeric_value(count_cell, "repeat_sum", allow_float=False)
        if count_outcome < 0:
            runtime_error(
                "repeat_sum expects a non-negative integer count",
                hint="Use 0 or a positive integer count.",
            )
        repeated = 0
        for _ in range(count_outcome):
            repeated = add_function(repeated, value)
        repeated_sweep = _coerce_value_to_sweep(repeated)
        count_selection = _fixed_axis_distribution(count_sweep.axes, count_coordinates)
        combined_axes = _union_axes([count_selection, repeated_sweep])
        cells = {}
        for coordinates in _coordinates_space(combined_axes):
            if _lookup_projected(count_sweep.axes, {count_coordinates: 1}, combined_axes, coordinates, 0) != 1:
                continue
            cells[coordinates] = repeated_sweep.lookup(combined_axes, coordinates)
        contributions.append((combined_axes, cells))
    return Sweep(_union_axes([Sweep(axes, cells) for axes, cells in contributions]), {coord: value for axes, cells in contributions for coord, value in cells.items()}) if contributions else Sweep.scalar(0)


def repeat_sum(count, value):
    return repeat_sum_with(add, count, value)


def sumover_with(add_function, value, axes=_OMITTED):
    sweep = _coerce_value_to_sweep(value)
    targets = _resolve_reduction_targets(sweep, axes, "sumover")
    return _apply_reduction(
        sweep,
        targets,
        "sumover",
        lambda _targets, entries: _sumover_reduce_entries(add_function, entries),
    )


def _sumover_reduce_entries(add_function, entries):
    reduced = 0
    for _, cell in entries:
        reduced = add_function(reduced, cell)
    reduced_sweep = _coerce_value_to_sweep(reduced)
    if not reduced_sweep.is_unswept():
        runtime_error("sumover reduction produced an unexpected sweep")
    return reduced_sweep.only_value()


def sumover(value, axes=_OMITTED):
    return sumover_with(add, value, axes)


def meanover(value, axes=_OMITTED):
    sweep = _coerce_value_to_sweep(value)
    targets = _resolve_reduction_targets(sweep, axes, "meanover")
    return _apply_reduction(sweep, targets, "meanover", lambda _targets, entries: _mean_reduce_cell(entries))


def maxover(value, axes=_OMITTED):
    sweep = _coerce_value_to_sweep(value)
    targets = _resolve_reduction_targets(sweep, axes, "maxover")
    return _apply_reduction(
        sweep,
        targets,
        "maxover",
        lambda _targets, entries: max(entries, key=lambda item: _max_key(item[1], "maxover"))[1],
    )


def argmaxover(value, axes=_OMITTED):
    sweep = _coerce_value_to_sweep(value)
    targets = _resolve_reduction_targets(sweep, axes, "argmaxover")
    return _apply_reduction(
        sweep,
        targets,
        "argmaxover",
        lambda resolved_targets, entries: _argmax_record(
            resolved_targets,
            max(entries, key=lambda item: _max_key(item[1], "argmaxover"))[0],
        ),
    )


def total_with(add_function, value):
    sweep = _coerce_value_to_sweep(value)
    target_axis = _resolve_total_axis(sweep)
    return _apply_reduction(
        sweep,
        ((target_axis, target_axis.name),),
        "total",
        lambda _targets, entries: _sumover_reduce_entries(add_function, entries),
    )


def total(value):
    return total_with(add, value)


def _require_string(value, context):
    if value is None:
        return None
    if not isinstance(value, str):
        runtime_error(context)
    return value


def _require_chart_spec(value, context):
    if not isinstance(value, ChartSpec):
        runtime_error(context)
    return value


def chart_with_width(chart, width):
    chart = _require_chart_spec(chart, "width overrides expect a chart spec")
    normalized = _require_string(width, "panel width must be a string")
    normalized = normalized.strip().lower()
    if normalized not in (PanelWidthClass.NARROW, PanelWidthClass.WIDE):
        runtime_error("panel width must be 'narrow' or 'wide'")
    return replace(chart, width_override=normalized)


def report_set_title(report, text):
    report = report if report is not None else ReportSpec()
    text = _require_string(text, "r_title expects a string")
    if report.title is not None:
        runtime_error("duplicate r_title in one pending report")
    return replace(report, title=text)


def report_add_note(report, text):
    report = report if report is not None else ReportSpec()
    text = _require_string(text, "r_note expects a string")
    return replace(report, blocks=report.blocks + (ReportBlock("note", text),))


def report_set_hero(report, chart):
    report = report if report is not None else ReportSpec()
    chart = _require_chart_spec(chart, "r_hero expects a chart spec")
    if report.hero is not None:
        runtime_error("duplicate r_hero in one pending report")
    return replace(report, hero=chart)


def report_add_row(report, charts):
    report = report if report is not None else ReportSpec()
    normalized = tuple(_require_chart_spec(chart, "r_row expects chart specs") for chart in charts)
    if not normalized:
        runtime_error("r_row expects at least one chart spec")
    if len(normalized) > 2:
        runtime_error("r_row supports at most two chart specs in v1")
    return replace(report, blocks=report.blocks + (ReportBlock("row", normalized),))


def report_append_chart(report, chart):
    report = report if report is not None else ReportSpec()
    chart = _require_chart_spec(chart, "pending report append expects a chart spec")
    return replace(report, blocks=report.blocks + (ReportBlock("panel", chart),))


def _normalize_render_export(path=None, format=None, dpi=None):
    if path is not None and not isinstance(path, str):
        runtime_error("render path must be a string")
    if format is not None:
        if not isinstance(format, str):
            runtime_error("render format must be a string")
        format = format.strip().lower()
    if dpi is not None:
        if not isinstance(dpi, (int, float)) or dpi <= 0:
            runtime_error("render dpi must be a positive number")
    return path, format, dpi


def render_report(report, render_config=None, path=None, format=None, dpi=None):
    report = report if report is not None else ReportSpec()
    if report.is_empty():
        runtime_error("render() requires at least one pending report item")
    render_config = render_config if render_config is not None else RenderConfig()
    renderer = _get_renderer(render_config)
    path, format, dpi = _normalize_render_export(path=path, format=format, dpi=dpi)
    return renderer.render_report(
        report,
        render_config=render_config,
        path=path,
        output_format=format,
        dpi=dpi,
    ).result
