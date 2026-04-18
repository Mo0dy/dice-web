#!/usr/bin/env python3

"""Interpreter-facing execution backends for dice semantics."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import functools
import inspect
from itertools import product
from typing import Any, get_origin, get_type_hints

import diceengine
from diceparser import DiceParser
from lexer import Lexer, ASSIGN, SEMI, PRINT


MISSING = object()
_DICEFUNCTION_ATTR = "_dicefunction_metadata"


@dataclass(frozen=True)
class DiceDefault:
    source: str
    ast: object


def D(source):
    if not isinstance(source, str) or not source.strip():
        raise Exception("D(...) expects a non-empty dice expression string")
    ast = DiceParser(Lexer(source)).parse()
    if type(ast).__name__ in {"FunctionDef", "Import"}:
        raise Exception("D(...) defaults must be expressions, not top-level statements")
    if type(ast).__name__ == "VarOp" and getattr(ast.op, "type", None) == SEMI:
        raise Exception("D(...) defaults must be a single expression")
    if type(ast).__name__ == "BinOp" and getattr(ast.op, "type", None) == ASSIGN:
        raise Exception("D(...) defaults must be expressions, not assignments")
    if type(ast).__name__ == "UnOp" and getattr(ast.op, "type", None) == PRINT:
        raise Exception("D(...) defaults must be expressions, not print statements")
    return DiceDefault(source, ast)


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    default_value: object = MISSING
    annotation: object = None
    keyword_only: bool = False

    @property
    def has_default(self):
        return self.default_value is not MISSING


@dataclass(frozen=True)
class DiceFunctionMetadata:
    export_name: str
    raw_function: object
    parameters: tuple[ParameterSpec, ...]
    signature: inspect.Signature


@dataclass
class HostFunction:
    name: str
    function: object
    parameters: tuple[ParameterSpec, ...] = ()
    variadic: bool = False
    variadic_keyword_arguments: bool = False
    sweep_mode: bool = False


def validate_runtime_value(value):
    if value is None:
        return value
    if isinstance(
        value,
        (
            int,
            float,
            str,
            diceengine.TupleValue,
            diceengine.RecordValue,
            diceengine.SweepValues,
            diceengine.FiniteMeasure,
            diceengine.Distribution,
            diceengine.Sweep,
            diceengine.ChartSpec,
            diceengine.ReportSpec,
        ),
    ):
        return value
    raise Exception("Unsupported host value type {}".format(type(value)))


def _identifier_names(node):
    names = set()
    if node is None:
        return names
    node_type = type(node).__name__
    if node_type == "Val" and getattr(getattr(node, "token", None), "type", None) == "ID":
        names.add(node.value)
    for value in getattr(node, "__dict__", {}).values():
        if isinstance(value, list):
            for item in value:
                names.update(_identifier_names(item))
        else:
            names.update(_identifier_names(value))
    return names


def _function_type_hints(function):
    try:
        return get_type_hints(function)
    except Exception:
        return {}


def callable_parameters(function, variadic=False):
    if variadic:
        return ()
    signature = inspect.signature(function)
    parameters = list(signature.parameters.values())
    names = [parameter.name for parameter in parameters]
    hints = _function_type_hints(function)
    specs = []
    for parameter in parameters:
        if parameter.kind != inspect.Parameter.POSITIONAL_OR_KEYWORD:
            raise Exception("Python functions only support POSITIONAL_OR_KEYWORD parameters")
        default_value = MISSING
        if parameter.default is not inspect._empty:
            default_value = parameter.default
            if isinstance(default_value, DiceDefault):
                referenced = _identifier_names(default_value.ast)
                forbidden = sorted(name for name in names if name in referenced)
                if forbidden:
                    raise Exception(
                        "D(...) defaults may only reference globals, not parameters: {}".format(", ".join(forbidden))
                    )
        specs.append(
            ParameterSpec(
                name=parameter.name,
                default_value=default_value,
                annotation=hints.get(parameter.name),
            )
        )
    return tuple(specs)


def _annotation_requests_sweep(function):
    hints = _function_type_hints(function)
    for annotation in hints.values():
        if _annotation_is_sweep(annotation):
            return True
    return False


def _annotation_is_sweep(annotation):
    return annotation is diceengine.Sweep or get_origin(annotation) is diceengine.Sweep


def _convert_projected_argument(projected, annotation):
    if annotation is diceengine.Distribution:
        return diceengine._coerce_to_distribution_cell(projected)
    if annotation is diceengine.FiniteMeasure:
        return diceengine._coerce_to_measure_cell(projected)
    return projected


def _lifted_python_call(function, parameters, values):
    projected_arguments = []
    combined_sweeps = []
    for index, value in enumerate(values):
        annotation = parameters[index].annotation if index < len(parameters) else None
        if _annotation_is_sweep(annotation):
            projected_arguments.append((False, value, annotation))
            continue
        sweep = diceengine._coerce_value_to_sweep(value)
        projected_arguments.append((True, sweep, annotation))
        combined_sweeps.append(sweep)
    combined_axes = diceengine._union_axes(combined_sweeps)
    if not combined_axes:
        projected = []
        for is_projected, value, annotation in projected_arguments:
            if not is_projected:
                projected.append(value)
                continue
            projected.append(_convert_projected_argument(value.only_value(), annotation))
        return validate_runtime_value(function(*projected))
    cells = {}
    for coordinates in ([()] if not combined_axes else product(*(axis.values for axis in combined_axes))):
        projected = []
        for is_projected, value, annotation in projected_arguments:
            if not is_projected:
                projected.append(value)
                continue
            projected.append(_convert_projected_argument(value.lookup(combined_axes, coordinates), annotation))
        cells[coordinates] = validate_runtime_value(function(*projected))
    return diceengine.Sweep(combined_axes, cells)


def dicefunction(function=None, *, name=None):
    def decorate(raw_function):
        export_name = name if name is not None else raw_function.__name__
        if not export_name:
            raise Exception("Python functions must have a name")
        parameters = callable_parameters(raw_function)
        signature = inspect.signature(raw_function)

        @functools.wraps(raw_function)
        def wrapped(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            values = []
            for parameter in parameters:
                value = bound.arguments[parameter.name]
                if isinstance(value, DiceDefault):
                    raise Exception("D(...) defaults are only resolved by dice-session invocation")
                values.append(value)
            return _lifted_python_call(raw_function, parameters, values)

        setattr(
            wrapped,
            _DICEFUNCTION_ATTR,
            DiceFunctionMetadata(
                export_name=export_name,
                raw_function=raw_function,
                parameters=parameters,
                signature=signature,
            ),
        )
        return wrapped

    if function is None:
        return decorate
    return decorate(function)


def get_dicefunction_metadata(function):
    return getattr(function, _DICEFUNCTION_ATTR, None)


class Executor(ABC):
    """Abstract interpreter backend plus named host-callable registry."""

    def __init__(self, render_config=None):
        self.functions = {}
        self.render_config = render_config if render_config is not None else diceengine.RenderConfig()
        self.pending_report = diceengine.ReportSpec()
        self._register_builtin_functions()

    def _callable_parameters(self, function, variadic=False):
        metadata = get_dicefunction_metadata(function)
        if metadata is not None and not variadic:
            return metadata.parameters
        return callable_parameters(function, variadic=variadic)

    def _type_hints(self, function):
        return _function_type_hints(function)

    def _annotation_requests_sweep(self, function):
        return _annotation_requests_sweep(function)

    def _register_host_function(
        self,
        function,
        name=None,
        variadic=False,
        sweep_mode=None,
        require_decorated=False,
        parameters=None,
        variadic_keyword_arguments=False,
    ):
        metadata = get_dicefunction_metadata(function)
        if require_decorated and metadata is None:
            raise Exception("Python functions must be decorated with @dicefunction to be registered")
        callable_name = name if name is not None else (metadata.export_name if metadata is not None else function.__name__)
        if not callable_name:
            raise Exception("Python functions must have a name")
        if callable_name in self.functions:
            raise Exception("Duplicate function definition for {}".format(callable_name))
        parameters = parameters if parameters is not None else self._callable_parameters(function, variadic=variadic)
        entry = HostFunction(
            callable_name,
            function=function,
            parameters=parameters,
            variadic=variadic,
            variadic_keyword_arguments=variadic_keyword_arguments,
            sweep_mode=self._annotation_requests_sweep(function) if sweep_mode is None else sweep_mode,
        )
        self.functions[callable_name] = entry
        return function

    def _register_builtin_functions(self):
        for name in [
            "add",
            "sub",
            "mul",
            "div",
            "floordiv",
            "neg",
            "roll",
            "rollsingle",
            "rolladvantage",
            "rolldisadvantage",
            "rollhigh",
            "rolllow",
            "greaterorequal",
            "greater",
            "equal",
            "lessorequal",
            "less",
            "member",
            "res",
            "reselse",
            "reselsediv",
            "reselsefloordiv",
            "mean",
            "sample",
            "var",
            "std",
            "cum",
            "surv",
            "type",
            "shape",
            "repeat_sum",
            "sumover",
            "meanover",
            "maxover",
            "argmaxover",
            "total",
            "set_render_mode",
            "set_render_backend",
            "set_render_autoflush",
            "set_render_omit_dominant_zero",
            "set_probability_mode",
            "r_title",
            "r_note",
            "r_hero",
            "r_wide",
            "r_narrow",
        ]:
            self._register_host_function(getattr(self, name), name=name, sweep_mode=True)
        self._register_host_function(
            self.r_row,
            name="r_row",
            variadic=True,
            sweep_mode=True,
        )
        chart_kw_parameters = (
            ParameterSpec("x", default_value=None, keyword_only=True),
            ParameterSpec("y", default_value=None, keyword_only=True),
            ParameterSpec("title", default_value=None, keyword_only=True),
        )
        compare_kw_parameters = (
            ParameterSpec("x", default_value=None, keyword_only=True),
            ParameterSpec("y", default_value=None, keyword_only=True),
            ParameterSpec("title", default_value=None, keyword_only=True),
        )
        self._register_host_function(self.r_auto, name="r_auto", sweep_mode=True, parameters=chart_kw_parameters, variadic=True, variadic_keyword_arguments=True)
        self._register_host_function(self.r_dist, name="r_dist", sweep_mode=True, parameters=chart_kw_parameters, variadic=True, variadic_keyword_arguments=True)
        self._register_host_function(self.r_cdf, name="r_cdf", sweep_mode=True, parameters=chart_kw_parameters, variadic=True, variadic_keyword_arguments=True)
        self._register_host_function(self.r_surv, name="r_surv", sweep_mode=True, parameters=chart_kw_parameters, variadic=True, variadic_keyword_arguments=True)
        self._register_host_function(self.r_compare, name="r_compare", sweep_mode=True, parameters=compare_kw_parameters, variadic=True, variadic_keyword_arguments=True)
        self._register_host_function(self.r_diff, name="r_diff", sweep_mode=True, parameters=compare_kw_parameters, variadic=True, variadic_keyword_arguments=True)
        self._register_host_function(self.r_best, name="r_best", sweep_mode=True, parameters=chart_kw_parameters, variadic=True, variadic_keyword_arguments=True)
        self._register_host_function(
            self.render,
            name="render",
            sweep_mode=True,
            parameters=(
                ParameterSpec("path", default_value=None),
                ParameterSpec("format", default_value=None),
                ParameterSpec("dpi", default_value=None),
            ),
        )

    def register_function(self, function, name=None):
        return self._register_host_function(function, name=name, require_decorated=True)

    def repeat_sum(self, count, value):
        return diceengine.repeat_sum_with(self.add, count, value)

    def sumover(self, value, axes=None):
        return diceengine.sumover_with(self.add, value, diceengine._OMITTED if axes is None else axes)

    def meanover(self, value, axes=None):
        return diceengine.meanover(value, diceengine._OMITTED if axes is None else axes)

    def maxover(self, value, axes=None):
        return diceengine.maxover(value, diceengine._OMITTED if axes is None else axes)

    def argmaxover(self, value, axes=None):
        return diceengine.argmaxover(value, diceengine._OMITTED if axes is None else axes)

    def total(self, value: diceengine.Sweep[Any]) -> diceengine.Sweep[Any]:
        return diceengine.total_with(self.add, value)

    def _normalize_chart_arguments(self, args, x=None, y=None, title=None):
        if len(args) != 1:
            raise Exception("chart constructors expect exactly one expression")
        return args[0], x, y, title

    def r_auto(self, *args, x=None, y=None, title=None):
        value, x, y, title = self._normalize_chart_arguments(args, x=x, y=y, title=title)
        return diceengine.ChartSpec("auto", payload=value, x_label=x, y_label=y, title=title)

    def r_dist(self, *args, x=None, y=None, title=None):
        value, x, y, title = self._normalize_chart_arguments(args, x=x, y=y, title=title)
        return diceengine.ChartSpec("dist", payload=value, x_label=x, y_label=y, title=title)

    def r_cdf(self, *args, x=None, y=None, title=None):
        value, x, y, title = self._normalize_chart_arguments(args, x=x, y=y, title=title)
        return diceengine.ChartSpec("cdf", payload=value, x_label=x, y_label=y, title=title)

    def r_surv(self, *args, x=None, y=None, title=None):
        value, x, y, title = self._normalize_chart_arguments(args, x=x, y=y, title=title)
        return diceengine.ChartSpec("surv", payload=value, x_label=x, y_label=y, title=title)

    def r_compare(self, *entries, x=None, y=None, title=None):
        return diceengine.ChartSpec("compare", payload=tuple(entries), x_label=x, y_label=y, title=title)

    def r_diff(self, *entries, x=None, y=None, title=None):
        return diceengine.ChartSpec("diff", payload=tuple(entries), x_label=x, y_label=y, title=title)

    def r_best(self, *args, x=None, y=None, title=None):
        value, x, y, title = self._normalize_chart_arguments(args, x=x, y=y, title=title)
        return diceengine.ChartSpec("best", payload=value, x_label=x, y_label=y, title=title)

    def r_title(self, text):
        self.pending_report = diceengine.report_set_title(self.pending_report, text)
        return None

    def r_note(self, text):
        self.pending_report = diceengine.report_add_note(self.pending_report, text)
        return None

    def r_hero(self, chart):
        self.pending_report = diceengine.report_set_hero(self.pending_report, chart)
        return None

    def r_row(self, *charts):
        self.pending_report = diceengine.report_add_row(self.pending_report, charts)
        return None

    def r_wide(self, chart):
        return diceengine.chart_with_width(chart, "wide")

    def r_narrow(self, chart):
        return diceengine.chart_with_width(chart, "narrow")

    def append_chart(self, chart):
        self.pending_report = diceengine.report_append_chart(self.pending_report, chart)

    def render(self, path=None, format=None, dpi=None):
        output_path = diceengine.render_report(
            self.pending_report,
            render_config=self.render_config,
            path=path,
            format=format,
            dpi=dpi,
        )
        self.pending_report = diceengine.ReportSpec()
        return output_path

    def flush_pending_report_at_end(self):
        if not self.render_config.auto_render_pending_on_exit:
            return None
        if not self.pending_report.has_renderable_content():
            return None
        return self.render()

    def set_render_mode(self, mode):
        self.render_config = self.render_config.with_mode(mode)
        return self.render_config.mode_name()

    def set_render_backend(self, backend):
        self.render_config = self.render_config.with_backend(backend)
        return self.render_config.backend

    def set_render_autoflush(self, enabled):
        self.render_config = self.render_config.with_auto_render_pending(enabled)
        return "on" if self.render_config.auto_render_pending_on_exit else "off"

    def set_render_omit_dominant_zero(self, enabled):
        self.render_config = self.render_config.with_omit_dominant_zero_outcome(enabled)
        return "on" if self.render_config.omit_dominant_zero_outcome else "off"

    def set_probability_mode(self, mode):
        self.render_config = self.render_config.with_probability_mode(mode)
        return self.render_config.effective_probability_mode()

    @abstractmethod
    def member(self, left, right):
        raise NotImplementedError

    @abstractmethod
    def res(self, condition, distrib):
        raise NotImplementedError

    @abstractmethod
    def mean(self, value):
        raise NotImplementedError

    @abstractmethod
    def meanover(self, value, axes=None):
        raise NotImplementedError

    @abstractmethod
    def maxover(self, value, axes=None):
        raise NotImplementedError

    @abstractmethod
    def argmaxover(self, value, axes=None):
        raise NotImplementedError

    @abstractmethod
    def var(self, value):
        raise NotImplementedError

    @abstractmethod
    def std(self, value):
        raise NotImplementedError

    @abstractmethod
    def cum(self, value):
        raise NotImplementedError

    @abstractmethod
    def surv(self, value):
        raise NotImplementedError

    @abstractmethod
    def sample(self, value):
        raise NotImplementedError

    def type(self, value):
        return diceengine.runtime_type(value)

    def shape(self, value):
        return diceengine.runtime_shape(value)

    @abstractmethod
    def reselse(self, condition, distrib_if, distrib_else):
        raise NotImplementedError

    @abstractmethod
    def reselsediv(self, condition, distrib):
        raise NotImplementedError

    @abstractmethod
    def reselsefloordiv(self, condition, distrib):
        raise NotImplementedError

    @abstractmethod
    def roll(self, n, s):
        raise NotImplementedError

    @abstractmethod
    def rollsingle(self, dice):
        raise NotImplementedError

    @abstractmethod
    def rolladvantage(self, dice):
        raise NotImplementedError

    @abstractmethod
    def rolldisadvantage(self, dice):
        raise NotImplementedError

    @abstractmethod
    def rollhigh(self, n, s, nh):
        raise NotImplementedError

    @abstractmethod
    def rolllow(self, n, s, nl):
        raise NotImplementedError

    @abstractmethod
    def add(self, left, right):
        raise NotImplementedError

    @abstractmethod
    def sub(self, left, right):
        raise NotImplementedError

    @abstractmethod
    def mul(self, left, right):
        raise NotImplementedError

    @abstractmethod
    def div(self, left, right):
        raise NotImplementedError

    @abstractmethod
    def floordiv(self, left, right):
        raise NotImplementedError

    @abstractmethod
    def neg(self, value):
        raise NotImplementedError

    @abstractmethod
    def greaterorequal(self, left, right):
        raise NotImplementedError

    @abstractmethod
    def greater(self, left, right):
        raise NotImplementedError

    @abstractmethod
    def equal(self, left, right):
        raise NotImplementedError

    @abstractmethod
    def lessorequal(self, left, right):
        raise NotImplementedError

    @abstractmethod
    def less(self, left, right):
        raise NotImplementedError


class ExactExecutor(Executor):
    """Exact backend delegating to pure functions in diceengine."""

    def member(self, left, right):
        return diceengine.member(left, right)

    def res(self, condition, distrib):
        return diceengine.res(condition, distrib)

    def mean(self, value):
        return diceengine.mean(value)

    def meanover(self, value, axes=None):
        return diceengine.meanover(value, diceengine._OMITTED if axes is None else axes)

    def maxover(self, value, axes=None):
        return diceengine.maxover(value, diceengine._OMITTED if axes is None else axes)

    def argmaxover(self, value, axes=None):
        return diceengine.argmaxover(value, diceengine._OMITTED if axes is None else axes)

    def var(self, value):
        return diceengine.var(value)

    def std(self, value):
        return diceengine.std(value)

    def cum(self, value):
        return diceengine.cum(value)

    def surv(self, value):
        return diceengine.surv(value)

    def sample(self, value):
        return diceengine.sample(value)

    def reselse(self, condition, distrib_if, distrib_else):
        return diceengine.reselse(condition, distrib_if, distrib_else)

    def reselsediv(self, condition, distrib):
        return diceengine.reselsediv(condition, distrib)

    def reselsefloordiv(self, condition, distrib):
        return diceengine.reselsefloordiv(condition, distrib)

    def roll(self, n, s):
        return diceengine.roll(n, s)

    def rollsingle(self, dice):
        return diceengine.rollsingle(dice)

    def rolladvantage(self, dice):
        return diceengine.rolladvantage(dice)

    def rolldisadvantage(self, dice):
        return diceengine.rolldisadvantage(dice)

    def rollhigh(self, n, s, nh):
        return diceengine.rollhigh(n, s, nh)

    def rolllow(self, n, s, nl):
        return diceengine.rolllow(n, s, nl)

    def add(self, left, right):
        return diceengine.add(left, right)

    def sub(self, left, right):
        return diceengine.sub(left, right)

    def mul(self, left, right):
        return diceengine.mul(left, right)

    def div(self, left, right):
        return diceengine.div(left, right)

    def floordiv(self, left, right):
        return diceengine.floordiv(left, right)

    def neg(self, value):
        return diceengine.neg(value)

    def greaterorequal(self, left, right):
        return diceengine.greaterorequal(left, right)

    def greater(self, left, right):
        return diceengine.greater(left, right)

    def equal(self, left, right):
        return diceengine.equal(left, right)

    def lessorequal(self, left, right):
        return diceengine.lessorequal(left, right)

    def less(self, left, right):
        return diceengine.less(left, right)
