#!/usr/bin/env python3

"""The Interpreter for the dice language."""

from __future__ import annotations

from difflib import get_close_matches
import inspect
import os
import re
from itertools import product

from diagnostics import DiagnosticError, RuntimeError as DiceRuntimeError
from diceparser import DiceParser
from lexer import (
    Lexer,
    INTEGER,
    FLOAT,
    ROLL,
    GREATER_OR_EQUAL,
    LESS_OR_EQUAL,
    LESS,
    GREATER,
    EQUAL,
    IN,
    PLUS,
    MINUS,
    MUL,
    DIV,
    FLOORDIV,
    RES,
    ELSE,
    EOF,
    ADV,
    DIS,
    ELSEDIV,
    ELSEFLOORDIV,
    HIGH,
    LOW,
    AVG,
    PROP,
    ID,
    ASSIGN,
    SEMI,
    PRINT,
    STRING,
)
from diceengine import (
    Sweep,
    SweepValues,
    FiniteMeasure,
    Distribution,
    RenderConfig,
    TRUE,
    FALSE,
    _accumulate_distribution_contributions,
    _coerce_to_measure_cell,
    _coerce_to_distribution_cell,
    _coerce_value_to_sweep,
    _coerce_to_distributions,
    _deterministic_numeric_value,
    _lookup_projected,
    _union_axes,
)
from executor import ExactExecutor


STDLIB_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stdlib")
IMPORT_COMPLETION_PATTERN = re.compile(r'(?:^|[;\n])\s*import\s+"$')
IDENTIFIER_COMPLETION_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")
COMPLETION_KEYWORDS = ("as", "import", "in", "match", "otherwise")


class CallableEntry(object):
    def __init__(self, name, kind, arity=None, variadic=False, function=None, node=None, sweep_mode=False):
        self.name = name
        self.kind = kind
        self.arity = arity
        self.variadic = variadic
        self.function = function
        self.node = node
        self.sweep_mode = sweep_mode


class Interpreter:
    def __init__(
        self,
        ast,
        debug=False,
        executor=None,
        current_dir=None,
        imported_files=None,
        import_stack=None,
        render_config=None,
    ):
        self.ast = ast
        self.debug = debug
        self.global_scope = {}
        self.callable_scope = {}
        self.local_scopes = []
        self.call_stack = []
        self.render_config = render_config if render_config is not None else RenderConfig()
        self.executor = executor if executor is not None else ExactExecutor(render_config=self.render_config)
        self.current_dir = os.path.abspath(current_dir if current_dir is not None else os.getcwd())
        self.stdlib_root = os.path.abspath(STDLIB_ROOT)
        self.imported_files = imported_files if imported_files is not None else set()
        self.import_stack = import_stack if import_stack is not None else []
        self._sweep_cache = {}

    def visit(self, node):
        method_name = "visit_" + type(node).__name__
        if self.debug:
            print(f"EXEC: {type(node).__name__}, {getattr(node, 'token', None)}")
        visitor = getattr(self, method_name, self.generic_visit)
        return visitor(node)

    def generic_visit(self, node):
        raise DiceRuntimeError("internal error: no visit_{} method".format(type(node).__name__))

    def interpret(self):
        return self.evaluate(self.ast)

    def evaluate(self, ast):
        self.collect_function_definitions(ast)
        return self.visit(ast)

    def collect_function_definitions(self, node):
        if node is None:
            return
        if type(node).__name__ == "FunctionDef":
            self.register_function_definition(node)
            return
        if type(node).__name__ == "VarOp" and node.op.type == SEMI:
            for child in node.nodes:
                if type(child).__name__ == "FunctionDef":
                    self.register_function_definition(child)

    def _register_callable(self, entry):
        if entry.name in self.callable_scope:
            self.exception(
                "Duplicate function definition for {}".format(entry.name),
                node=entry.node,
                hint="Rename one of the functions or remove the duplicate definition.",
            )
        if entry.name in self.executor.functions:
            self.exception(
                "Duplicate function definition for {}".format(entry.name),
                node=entry.node,
                hint="Builtins and user-defined functions share the same namespace.",
            )
        self.callable_scope[entry.name] = entry

    def register_function_definition(self, node):
        self._register_callable(CallableEntry(node.name.value, "dsl", arity=len(node.params), node=node))

    def register_function(self, function, name=None):
        callable_name = name if name is not None else function.__name__
        if not callable_name:
            self.exception("python functions must have a name")
        if callable_name in self.callable_scope or callable_name in self.executor.functions:
            self.exception("Duplicate function definition for {}".format(callable_name))
        self.executor.register_function(function, name=callable_name)
        return function

    def _node_span(self, node):
        if node is None:
            return None
        token = getattr(node, "token", None)
        if token is None:
            token = getattr(node, "token1", None)
        if token is None:
            return None
        return getattr(token, "span", None)

    def _raise_or_enrich(self, error, node=None, hint=None):
        span = self._node_span(self._best_error_node(error, node))
        if isinstance(error, DiagnosticError):
            raise error.attach_span(span).attach_hint(hint)
        raise DiceRuntimeError(str(error), span=span, hint=hint)

    def _with_runtime_context(self, node, function):
        try:
            return function()
        except Exception as error:
            self._raise_or_enrich(error, node=node)

    def _suggest_name(self, name, candidates):
        matches = get_close_matches(name, sorted(candidates), n=1, cutoff=0.6)
        return matches[0] if matches else None

    def _value_candidates(self):
        candidates = set(self.global_scope.keys())
        for scope in self.local_scopes:
            candidates.update(scope.keys())
        return candidates

    def _function_candidates(self):
        return set(self.callable_scope) | set(self.executor.functions)

    def _completion_names(self):
        names = set(COMPLETION_KEYWORDS)
        names.update(self._value_candidates())
        names.update(self._function_candidates())
        return sorted(names)

    def _identifier_hint(self, name, *, prefer_call=False):
        function_candidates = self._function_candidates()
        value_candidates = self._value_candidates()
        if not prefer_call and name in function_candidates:
            return "{} is a function. Did you mean {}(...)?".format(name, name)
        if prefer_call and name in value_candidates:
            return "{} is a variable, not a function.".format(name)
        function_match = self._suggest_name(name, function_candidates)
        value_match = self._suggest_name(name, value_candidates)
        if prefer_call and function_match:
            return "Did you mean {}?".format(function_match)
        if not prefer_call and value_match:
            return "Did you mean {}?".format(value_match)
        if not prefer_call and function_match:
            return "Did you mean {}?".format(function_match)
        if prefer_call and value_match:
            return "Did you mean {}?".format(value_match)
        return None

    def _call_hint(self, entry):
        if entry.variadic:
            return None
        if getattr(entry, "kind", None) == "dsl":
            params = [param.value for param in entry.node.params]
        else:
            try:
                signature = inspect.signature(entry.function)
                params = [
                    parameter.name
                    for parameter in signature.parameters.values()
                    if parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                ]
            except (TypeError, ValueError):
                params = []
            if not params:
                params = ["arg{}".format(index + 1) for index in range(entry.arity)]
        return "Call it like {}({}).".format(entry.name, ", ".join(params))

    def _literal_scalar_from_node(self, node):
        if type(node).__name__ == "Val" and node.token.type in [INTEGER, FLOAT, STRING]:
            return node.value
        return None

    def _best_roll_node(self, left_node, right_node):
        left_value = self._literal_scalar_from_node(left_node)
        right_value = self._literal_scalar_from_node(right_node)
        if right_value is not None and (not isinstance(right_value, int) or right_value <= 0):
            return right_node
        if left_value is not None and (not isinstance(left_value, int) or left_value < 0):
            return left_node
        return None

    def _best_keep_node(self, count_node, sides_node, keep_node):
        count_value = self._literal_scalar_from_node(count_node)
        sides_value = self._literal_scalar_from_node(sides_node)
        keep_value = self._literal_scalar_from_node(keep_node)
        if keep_value is not None and (
            not isinstance(keep_value, int)
            or keep_value < 0
            or (isinstance(count_value, int) and keep_value > count_value)
        ):
            return keep_node
        if sides_value is not None and (not isinstance(sides_value, int) or sides_value <= 0):
            return sides_node
        if count_value is not None and (not isinstance(count_value, int) or count_value < 0):
            return count_node
        return None

    def _best_error_node(self, error, node):
        if node is None:
            return None
        message = str(error).lower()
        node_type = type(node).__name__
        if node_type == "BinOp":
            if node.op.type in (DIV, FLOORDIV) and "divide by zero" in message:
                return node.right
            if node.op.type == ROLL and ("positive sides" in message or "integer outcomes" in message):
                return self._best_roll_node(node.left, node.right) or node
        if node_type == "TenOp" and node.op1.type == ROLL and node.op2.type in [HIGH, LOW]:
            if "keep count" in message or "positive sides" in message or "integer outcomes" in message:
                return self._best_keep_node(node.left, node.middle, node.right) or node
        return node

    def _unknown_name_hint(self, name):
        return self._identifier_hint(name, prefer_call=False)

    def exception(self, message="", node=None, hint=None):
        raise DiceRuntimeError(message, span=self._node_span(node), hint=hint)

    def _import_path_variants(self, path):
        variants = [os.path.abspath(path)]
        if not os.path.splitext(path)[1]:
            variants.append(os.path.abspath(path + ".dice"))
        deduped = []
        seen = set()
        for variant in variants:
            if variant in seen:
                continue
            deduped.append(variant)
            seen.add(variant)
        return deduped

    def _resolve_import_path(self, import_path):
        if import_path.startswith("std:"):
            stdlib_path = import_path[len("std:"):].lstrip("/\\")
            if not stdlib_path:
                self.exception(
                    "Could not import {!r}".format(import_path),
                    hint='Use a stdlib path like "std:dnd/weapons".',
                )
            candidates = self._import_path_variants(os.path.join(self.stdlib_root, stdlib_path))
            for candidate in candidates:
                if os.path.commonpath([self.stdlib_root, candidate]) != self.stdlib_root:
                    self.exception(
                        "Could not import {!r}".format(import_path),
                        hint="Stdlib imports must stay inside the stdlib directory.",
                    )
            for candidate in candidates:
                if os.path.isfile(candidate):
                    return candidate
            return candidates[0]

        base_path = import_path if os.path.isabs(import_path) else os.path.join(self.current_dir, import_path)
        candidates = self._import_path_variants(base_path)
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate
        return candidates[0]

    def _is_import_completion_context(self, line_buffer, begidx):
        return IMPORT_COMPLETION_PATTERN.search(line_buffer[:begidx]) is not None

    def _import_completion_entries(self, root_dir, relative_dir, partial_name, prefix):
        search_dir = os.path.join(root_dir, relative_dir) if relative_dir else root_dir
        if not os.path.isdir(search_dir):
            return []
        entries = []
        for entry in sorted(os.scandir(search_dir), key=lambda item: (not item.is_dir(), item.name)):
            if not entry.name.startswith(partial_name):
                continue
            completed_name = entry.name
            is_directory = entry.is_dir()
            if is_directory:
                completed_name += "/"
            elif entry.is_file() and entry.name.endswith(".dice"):
                completed_name = entry.name[:-len(".dice")]
            completed_path = completed_name if not relative_dir else relative_dir + "/" + completed_name
            entries.append(
                {
                    "suggestion": prefix + completed_path.replace(os.sep, "/"),
                    "is_directory": is_directory,
                    "relative_path": completed_path.replace(os.sep, "/"),
                }
            )
        return entries

    def _complete_import_path(self, text):
        prefix = ""
        relative_prefix = text
        root_dir = self.current_dir
        if text.startswith("std:"):
            prefix = "std:"
            relative_prefix = text[len(prefix):]
            root_dir = self.stdlib_root
        elif text.startswith("/"):
            prefix = "/"
            relative_prefix = text[len(prefix):]
            root_dir = os.path.sep
        relative_dir, partial_name = os.path.split(relative_prefix)
        entries = self._import_completion_entries(root_dir, relative_dir, partial_name, prefix)
        if len(entries) == 1 and entries[0]["is_directory"]:
            child_relative_dir = entries[0]["relative_path"].rstrip("/")
            entries.extend(self._import_completion_entries(root_dir, child_relative_dir, "", prefix))
        completions = []
        seen = set()
        for entry in entries:
            suggestion = entry["suggestion"]
            if suggestion not in seen:
                completions.append(suggestion)
                seen.add(suggestion)
        return completions

    def complete(self, text, *, line_buffer="", begidx=None, endidx=None):
        if line_buffer is None:
            line_buffer = ""
        if endidx is None:
            endidx = len(line_buffer)
        if begidx is None:
            begidx = max(0, endidx - len(text))
        if self._is_import_completion_context(line_buffer, begidx):
            return self._complete_import_path(text)
        if text and not IDENTIFIER_COMPLETION_PATTERN.fullmatch(text):
            return []
        candidates = self._completion_names()
        if not text:
            return candidates
        return [candidate for candidate in candidates if candidate.startswith(text)]

    def _validate_runtime_value(self, value):
        if value is None:
            return value
        if isinstance(value, (int, float, str, SweepValues, FiniteMeasure, Distribution, Sweep)):
            return value
        self.exception("Unsupported host value type {}".format(type(value)))

    def _bool_masses(self, condition, node=None):
        invalid = [outcome for outcome in condition.keys() if outcome not in (TRUE, FALSE)]
        if invalid:
            self.exception(
                "match guards must evaluate to Bernoulli outcomes 0 or 1, got {}".format(invalid),
                node=node,
                hint="Use a comparison like 'roll >= 15' or convert each guard to 0 or 1.",
            )
        return condition[TRUE], condition[FALSE]

    def _check_call_arity(self, entry, call_arity, node=None):
        if entry.variadic:
            return
        if call_arity != entry.arity:
            self.exception(
                "function {} expected {} arguments but got {}".format(entry.name, entry.arity, call_arity),
                node=node,
                hint=self._call_hint(entry),
            )

    def _call_dsl_function(self, entry, values):
        function = entry.node
        if entry.name in self.call_stack:
            self.exception(
                "Recursion not supported for {}".format(entry.name),
                node=function,
                hint="Rewrite the function using a closed-form expression or a builtin helper.",
            )
        local_scope = {param.value: value for param, value in zip(function.params, values)}
        self.call_stack.append(entry.name)
        self.local_scopes.append(local_scope)
        try:
            return self.visit(function.body)
        finally:
            self.local_scopes.pop()
            self.call_stack.pop()

    def _call_host_function(self, entry, values):
        if entry.sweep_mode:
            return self._validate_runtime_value(entry.function(*values))
        def convert_argument(projected, annotation):
            if annotation is Distribution:
                return _coerce_to_distribution_cell(projected)
            if annotation is FiniteMeasure:
                return _coerce_to_measure_cell(projected)
            return projected

        sweeps = [_coerce_value_to_sweep(value) for value in values]
        combined_axes = _union_axes(sweeps)
        if not combined_axes:
            projected = [
                convert_argument(sweep.only_value(), entry.parameter_annotations[index] if index < len(entry.parameter_annotations) else None)
                for index, sweep in enumerate(sweeps)
            ]
            return self._validate_runtime_value(entry.function(*projected))
        cells = {}
        for coordinates in product(*(axis.values for axis in combined_axes)):
            projected = [
                convert_argument(
                    sweep.lookup(combined_axes, coordinates),
                    entry.parameter_annotations[index] if index < len(entry.parameter_annotations) else None,
                )
                for index, sweep in enumerate(sweeps)
            ]
            cells[coordinates] = self._validate_runtime_value(entry.function(*projected))
        return Sweep(combined_axes, cells)

    def _parse_imported_source(self, resolved_path):
        with open(resolved_path, encoding="utf-8") as handle:
            text = handle.read()
        return DiceParser(Lexer(text, source_name=resolved_path)).parse()

    def visit_VarOp(self, node):
        if node.op.type == SEMI:
            last_result = None
            for n in node.nodes:
                if type(n).__name__ == "FunctionDef":
                    continue
                last_result = self.visit(n)
            return last_result
        self.exception("{} not implemented".format(node), node=node)

    def visit_FunctionDef(self, node):
        return None

    def visit_Import(self, node):
        import_path = node.path.value
        resolved_path = self._resolve_import_path(import_path)
        if resolved_path in self.import_stack:
            cycle = " -> ".join(self.import_stack + [resolved_path])
            self.exception(
                "Import cycle detected: {}".format(cycle),
                node=node,
                hint="Remove one of the circular imports or move shared definitions into a third file.",
            )
        if resolved_path in self.imported_files:
            return None
        if not os.path.isfile(resolved_path):
            self.exception(
                "Could not import {!r}".format(import_path),
                node=node.path,
                hint="Check that the file exists and that the path is relative to the importing file.",
            )
        ast = self._parse_imported_source(resolved_path)
        self.imported_files.add(resolved_path)
        self.import_stack.append(resolved_path)
        previous_dir = self.current_dir
        self.current_dir = os.path.dirname(resolved_path)
        try:
            return self.evaluate(ast)
        finally:
            self.current_dir = previous_dir
            self.import_stack.pop()

    def visit_SweepLiteral(self, node):
        if type(node.values).__name__ == "RangeLiteral":
            start = self.visit(node.values.start)
            end = self.visit(node.values.end)
            if not isinstance(start, int):
                self.exception("expected an integer range start", node=node.values.start)
            if not isinstance(end, int):
                self.exception("expected an integer range end", node=node.values.end)
            stop = end + 1 if node.values.inclusive_end else end
            values = tuple(range(start, stop))
        else:
            values = []
            for child in node.values:
                new_value = self.visit(child)
                if type(new_value) not in [int, float, str]:
                    self.exception(
                        "sweep construction expects scalar values, got {}".format(type(new_value)),
                        node=child,
                        hint="Use plain integers, floats, or strings inside [...].",
                    )
                values.append(new_value)
            values = tuple(values)
        return SweepValues(values, name=node.name.value if node.name is not None else None)

    def visit_RangeLiteral(self, node):
        self.exception("ranges may only appear inside sweeps or finite measures", node=node)

    def visit_MeasureLiteral(self, node):
        entry_values = []
        for entry in node.entries:
            weight = _coerce_value_to_sweep(1 if entry.weight is None else self.visit(entry.weight))
            if type(entry.value).__name__ == "RangeLiteral":
                start = self.visit(entry.value.start)
                end = self.visit(entry.value.end)
                if not isinstance(start, int):
                    self.exception("expected an integer range start", node=entry.value.start)
                if not isinstance(end, int):
                    self.exception("expected an integer range end", node=entry.value.end)
                stop = end + 1 if entry.value.inclusive_end else end
                values = [Sweep.scalar(value) for value in range(start, stop)]
            else:
                values = [_coerce_value_to_sweep(self.visit(entry.value))]
            entry_values.append((entry, values, weight))
        combined_axes = _union_axes([sweep for _, values, weight in entry_values for sweep in (*values, weight)])
        cells = {}
        for coordinates in ([()] if not combined_axes else product(*(axis.values for axis in combined_axes))):
            projected_entries = []
            for entry, value_sweeps, weight_sweep in entry_values:
                projected_weight = weight_sweep.lookup(combined_axes, coordinates)
                try:
                    numeric_weight = _deterministic_numeric_value(projected_weight, "finite measure weight")
                except Exception as error:
                    self._raise_or_enrich(error, node=entry.weight if entry.weight is not None else entry)
                if isinstance(projected_weight, FiniteMeasure):
                    self.exception("finite measure weights must be deterministic numbers", node=entry.weight or entry)
                for value_sweep in value_sweeps:
                    projected_entries.append((value_sweep.lookup(combined_axes, coordinates), numeric_weight))
            cells[coordinates] = FiniteMeasure(projected_entries)
        return Sweep(combined_axes, cells)

    def visit_Call(self, node):
        function_name = node.name.value
        if function_name in self.callable_scope:
            entry = self.callable_scope[function_name]
            self._check_call_arity(entry, len(node.args), node=node)
            values = [self.visit(arg) for arg in node.args]
            return self._with_runtime_context(node, lambda: self._call_dsl_function(entry, values))
        if function_name not in self.executor.functions:
            self.exception(
                "Unknown function {}".format(function_name),
                node=node,
                hint=self._identifier_hint(function_name, prefer_call=True),
            )
        entry = self.executor.functions[function_name]
        self._check_call_arity(entry, len(node.args), node=node)
        values = [self.visit(arg) for arg in node.args]
        return self._with_runtime_context(node, lambda: self._call_host_function(entry, values))

    def visit_Match(self, node):
        matched_value = _coerce_to_distributions(self.visit(node.value))
        contributions = []
        for matched_coordinates, matched_distrib in matched_value.items():
            for outcome, outcome_probability in matched_distrib.items():
                if outcome_probability == 0:
                    continue
                local_scope = {node.name.value: outcome}
                self.local_scopes.append(local_scope)
                try:
                    remaining_axes = matched_value.axes
                    remaining_cells = {matched_coordinates: 1.0}
                    for clause in node.clauses:
                        if clause.otherwise:
                            result_value = _coerce_to_distributions(self.visit(clause.result))
                            clause_axes = _union_axes([Sweep(remaining_axes, {coord: 1 for coord in remaining_cells}), result_value])
                            clause_cells = {}
                            for coordinates in ([()] if not clause_axes else product(*(axis.values for axis in clause_axes))):
                                remaining_mass = _lookup_projected(remaining_axes, remaining_cells, clause_axes, coordinates, 0)
                                if remaining_mass == 0:
                                    continue
                                result_distrib = result_value.lookup(clause_axes, coordinates)
                                weighted = FiniteMeasure(
                                    (result_outcome, outcome_probability * remaining_mass * result_probability)
                                    for result_outcome, result_probability in result_distrib.items()
                                )
                                clause_cells[coordinates] = weighted
                            contributions.append((clause_axes, clause_cells))
                            remaining_cells = {}
                            break

                        condition_value = _coerce_to_distributions(self.visit(clause.condition))
                        result_value = _coerce_to_distributions(self.visit(clause.result))
                        clause_axes = _union_axes([
                            Sweep(remaining_axes, {coord: 1 for coord in remaining_cells}),
                            condition_value,
                            result_value,
                        ])
                        clause_cells = {}
                        next_remaining = {}
                        for coordinates in ([()] if not clause_axes else product(*(axis.values for axis in clause_axes))):
                            remaining_mass = _lookup_projected(remaining_axes, remaining_cells, clause_axes, coordinates, 0)
                            if remaining_mass == 0:
                                continue
                            condition_distrib = condition_value.lookup(clause_axes, coordinates)
                            true_mass, false_mass = self._bool_masses(condition_distrib, node=clause.condition)
                            matched_mass = remaining_mass * true_mass
                            if matched_mass:
                                result_distrib = result_value.lookup(clause_axes, coordinates)
                                clause_cells[coordinates] = FiniteMeasure(
                                    (result_outcome, outcome_probability * matched_mass * result_probability)
                                    for result_outcome, result_probability in result_distrib.items()
                                )
                            next_mass = remaining_mass * false_mass
                            if next_mass:
                                next_remaining[coordinates] = next_mass
                        contributions.append((clause_axes, clause_cells))
                        remaining_axes = clause_axes
                        remaining_cells = next_remaining

                    if any(mass for mass in remaining_cells.values()):
                        self.exception(
                            "match expression left unmatched cases for {}".format(node.name.value),
                            node=node,
                            hint="Add an 'otherwise' clause to cover the remaining cases.",
                        )
                finally:
                    self.local_scopes.pop()
        return _accumulate_distribution_contributions(contributions)

    def visit_TenOp(self, node):
        if node.op1.type == RES and node.op2.type == ELSE:
            return self._with_runtime_context(
                node,
                lambda: self.executor.reselse(self.visit(node.left), self.visit(node.middle), self.visit(node.right)),
            )
        if node.op1.type == ROLL and node.op2.type == HIGH:
            return self._with_runtime_context(
                node,
                lambda: self.executor.rollhigh(self.visit(node.left), self.visit(node.middle), self.visit(node.right)),
            )
        if node.op1.type == ROLL and node.op2.type == LOW:
            return self._with_runtime_context(
                node,
                lambda: self.executor.rolllow(self.visit(node.left), self.visit(node.middle), self.visit(node.right)),
            )
        self.exception("{} not implemented".format(node), node=node)

    def visit_BinOp(self, node):
        if node.op.type == PLUS:
            return self._with_runtime_context(node, lambda: self.executor.add(self.visit(node.left), self.visit(node.right)))
        if node.op.type == MINUS:
            return self._with_runtime_context(node, lambda: self.executor.sub(self.visit(node.left), self.visit(node.right)))
        if node.op.type == MUL:
            return self._with_runtime_context(node, lambda: self.executor.mul(self.visit(node.left), self.visit(node.right)))
        if node.op.type == DIV:
            return self._with_runtime_context(node, lambda: self.executor.div(self.visit(node.left), self.visit(node.right)))
        if node.op.type == FLOORDIV:
            return self._with_runtime_context(node, lambda: self.executor.floordiv(self.visit(node.left), self.visit(node.right)))
        if node.op.type == ROLL:
            return self._with_runtime_context(node, lambda: self.executor.roll(self.visit(node.left), self.visit(node.right)))
        if node.op.type == GREATER_OR_EQUAL:
            return self._with_runtime_context(node, lambda: self.executor.greaterorequal(self.visit(node.left), self.visit(node.right)))
        if node.op.type == LESS_OR_EQUAL:
            return self._with_runtime_context(node, lambda: self.executor.lessorequal(self.visit(node.left), self.visit(node.right)))
        if node.op.type == GREATER:
            return self._with_runtime_context(node, lambda: self.executor.greater(self.visit(node.left), self.visit(node.right)))
        if node.op.type == LESS:
            return self._with_runtime_context(node, lambda: self.executor.less(self.visit(node.left), self.visit(node.right)))
        if node.op.type == EQUAL:
            return self._with_runtime_context(node, lambda: self.executor.equal(self.visit(node.left), self.visit(node.right)))
        if node.op.type == IN:
            return self._with_runtime_context(node, lambda: self.executor.member(self.visit(node.left), self.visit(node.right)))
        if node.op.type == RES:
            return self._with_runtime_context(node, lambda: self.executor.res(self.visit(node.left), self.visit(node.right)))
        if node.op.type == ELSEDIV:
            return self._with_runtime_context(node, lambda: self.executor.reselsediv(self.visit(node.left), self.visit(node.right)))
        if node.op.type == ELSEFLOORDIV:
            return self._with_runtime_context(node, lambda: self.executor.reselsefloordiv(self.visit(node.left), self.visit(node.right)))
        if node.op.type == ASSIGN:
            self.global_scope[node.left.value] = self.visit(node.right)
            return None
        self.exception("{} not implemented".format(node), node=node)

    def visit_UnOp(self, node):
        if node.op.type == ROLL:
            return self._with_runtime_context(node, lambda: self.executor.rollsingle(self.visit(node.value)))
        if node.op.type == ADV:
            return self._with_runtime_context(node, lambda: self.executor.rolladvantage(self.visit(node.value)))
        if node.op.type == DIS:
            return self._with_runtime_context(node, lambda: self.executor.rolldisadvantage(self.visit(node.value)))
        if node.op.type == AVG:
            return self._with_runtime_context(node, lambda: self.executor.mean(self.visit(node.value)))
        if node.op.type == PROP:
            return self._with_runtime_context(node, lambda: self.executor.sample(self.visit(node.value)))
        if node.op.type == MINUS:
            return self._with_runtime_context(node, lambda: self.executor.neg(self.visit(node.value)))
        if node.op.type == PRINT:
            print(self.visit(node.value))
            return None
        self.exception("{} not implemented".format(node), node=node)

    def visit_Val(self, node):
        if node.token.type in [INTEGER, FLOAT, STRING]:
            return node.value
        for scope in reversed(self.local_scopes):
            if node.value in scope:
                return scope[node.value]
        if node.value not in self.global_scope:
            self.exception(
                "unknown name {}".format(node.value),
                node=node,
                hint=self._unknown_name_hint(node.value),
            )
        return self.global_scope[node.value]
