#!/usr/bin/env python3

"""Sweep-aware finite-measure and probability primitives for dice semantics."""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import wraps
import importlib
from itertools import product
from math import inf, isfinite, sqrt
import random
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
_viewer_module = None


def exception(message):
    raise DiceRuntimeError(message)


def runtime_error(message, hint=None):
    raise DiceRuntimeError(message, hint=hint)


@dataclass(frozen=True)
class RenderConfig:
    interactive_blocking: bool = True
    wait_for_figures_on_exit: bool = False
    probability_mode: str | None = None

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


def _get_viewer():
    global _viewer_module
    if _viewer_module is None:
        _viewer_module = importlib.import_module("viewer")
    return _viewer_module


def wait_for_rendered_figures(render_config=None):
    viewer = _get_viewer()
    viewer.wait_for_rendered_figures(
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
    if isinstance(value, (int, float, str, FiniteMeasure, SweepValues)):
        return value
    runtime_error("unsupported runtime value {}".format(type(value)))


def _coerce_to_measure_cell(value):
    if isinstance(value, FiniteMeasure):
        return value
    if isinstance(value, (int, float, str)):
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
    if isinstance(value, (int, float, str)):
        return _deterministic_distribution(value)
    runtime_error("expected a distribution-compatible value, got {}".format(type(value)))


def _coerce_value_to_sweep(value):
    if isinstance(value, Sweep):
        return value
    if isinstance(value, SweepValues):
        return Sweep.from_values(value)
    return Sweep.scalar(value)


def _runtime_type_name(value):
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
        if isinstance(outcome, Distribution):
            runtime_error(
                "in does not accept probabilistic members on the right-hand side yet",
                hint="Use a finite measure of scalar or nested finite-measure values.",
            )
        support.add(outcome)
    result = []
    for outcome, probability in left_distribution.items():
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


def _resolve_target_axis(value, axis_name):
    if not isinstance(axis_name, str):
        runtime_error(
            "sumover expects a string axis name",
            hint='Pass the axis name as a string, for example sumover("party", value).',
        )
    matches = [axis for axis in value.axes if axis.name == axis_name and axis.name != axis.key]
    if not matches:
        runtime_error(
            "sumover could not find named axis {}".format(axis_name),
            hint="Create a named sweep like [party:1, 2, 3] before calling sumover.",
        )
    if len(matches) > 1:
        runtime_error("sumover found multiple axes named {}".format(axis_name))
    return matches[0]


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


def _coordinates_without_axis(axes, coordinates, target_key):
    return tuple(coordinate for axis, coordinate in zip(axes, coordinates) if axis.key != target_key)


def _sum_axis(add_function, value, target_axis):
    sweep = _coerce_value_to_sweep(value)
    remaining_axes = tuple(axis for axis in sweep.axes if axis.key != target_axis.key)
    grouped = {}
    for coordinates, cell in sweep.items():
        remaining_coordinates = _coordinates_without_axis(sweep.axes, coordinates, target_axis.key)
        grouped.setdefault(remaining_coordinates, []).append(cell)
    cells = {}
    for remaining_coordinates, cell_values in grouped.items():
        reduced = 0
        for cell in cell_values:
            reduced = add_function(reduced, cell)
        reduced_sweep = _coerce_value_to_sweep(reduced)
        if not reduced_sweep.is_unswept():
            runtime_error("sumover reduction produced an unexpected sweep")
        cells[remaining_coordinates] = reduced_sweep.only_value()
    if not cells:
        return Sweep.scalar(0)
    return Sweep(remaining_axes, cells)


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


def sumover_with(add_function, axis_name, value):
    sweep = _coerce_value_to_sweep(value)
    target_axis = _resolve_target_axis(sweep, axis_name)
    return _sum_axis(add_function, sweep, target_axis)


def sumover(axis_name, value):
    return sumover_with(add, axis_name, value)


def total_with(add_function, value):
    sweep = _coerce_value_to_sweep(value)
    target_axis = _resolve_total_axis(sweep)
    return _sum_axis(add_function, sweep, target_axis)


def total(value):
    return total_with(add, value)


def _require_render_text(value, message, hint):
    if not isinstance(value, str):
        runtime_error(message, hint=hint)
    return value


def _render(*args, render_config=None, assume_probability=False):
    viewer = _get_viewer()
    render_config = render_config if render_config is not None else RenderConfig()
    if not args:
        runtime_error("render expects at least one expression")
    if len(args) == 1:
        return viewer.render_result(
            args[0],
            render_config=render_config,
            assume_probability=assume_probability,
        ).output_path
    if len(args) == 2:
        runtime_error(
            "render titles require an axis label before the title",
            hint='Call render(value, "Axis Label", "Title").',
        )
    if len(args) == 3:
        axis_label = _require_render_text(args[1], "render axis labels must be strings", 'Call render(value, "Axis Label", "Title").')
        if not isinstance(args[2], str):
            runtime_error(
                "render comparisons require a label for every expression",
                hint='Call render(value1, "Label 1", value2, "Label 2").',
            )
        return viewer.render_result(
            args[0],
            x_label=axis_label,
            title=args[2],
            render_config=render_config,
            assume_probability=assume_probability,
        ).output_path

    comparison_axis_label = None
    comparison_title = None
    comparison_args = args
    if len(args) >= 6 and isinstance(args[-2], str) and isinstance(args[-1], str):
        potential_args = args[:-2]
        if len(potential_args) >= 4 and len(potential_args) % 2 == 0:
            comparison_args = potential_args
            comparison_axis_label = args[-2]
            comparison_title = args[-1]
    if comparison_axis_label is None and len(args) % 2 != 0:
        runtime_error(
            "render titles require an axis label before the title",
            hint='Call render(value, "Axis Label", "Title") or render(value1, "Label 1", value2, "Label 2", "Axis Label", "Title").',
        )
    if len(comparison_args) % 2 != 0:
        runtime_error(
            "render comparisons require a label for every expression",
            hint='Call render(value1, "Label 1", value2, "Label 2").',
        )
    entries = []
    for index in range(0, len(comparison_args), 2):
        label = comparison_args[index + 1]
        if not isinstance(label, str):
            runtime_error("render comparison labels must be strings")
        entries.append((label, comparison_args[index]))
    if len(entries) < 2:
        runtime_error(
            "render comparisons need at least two expressions",
            hint='Call render(value1, "Label 1", value2, "Label 2").',
        )
    return viewer.render_comparison(
        entries,
        x_label=comparison_axis_label,
        title=comparison_title,
        render_config=render_config,
        assume_probability=assume_probability,
    ).output_path


def render(*args, render_config=None):
    return _render(*args, render_config=render_config, assume_probability=False)


def renderp(*args, render_config=None):
    return _render(*args, render_config=render_config, assume_probability=True)
