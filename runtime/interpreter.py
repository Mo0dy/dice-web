#!/usr/bin/env python3

"""The Interpreter for the dice language."""

from __future__ import annotations

from difflib import get_close_matches
import hashlib
import importlib.util
import os
import re
import sys
from itertools import product

from diagnostics import DiagnosticError, DiagnosticWarning, RuntimeError as DiceRuntimeError
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
    CARET,
    DIV,
    FLOORDIV,
    RES,
    ELSE,
    EOF,
    ADV,
    DIS,
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
    ChartSpec,
    TupleValue,
    RecordValue,
    PROBABILITY_TOLERANCE,
    RenderConfig,
    TRUE,
    FALSE,
    _accumulate_distribution_contributions,
    _coerce_value_to_sweep,
    _coerce_to_distributions,
    _deterministic_numeric_value,
    _lookup_projected,
    _union_axes,
    sweep_index,
)
from executor import ExactExecutor
from executor import DiceDefault, MISSING, ParameterSpec, get_dicefunction_metadata, validate_runtime_value


STDLIB_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stdlib")
IMPORT_COMPLETION_PATTERN = re.compile(r'(?:^|[;\n])\s*import\s+"$')
IDENTIFIER_COMPLETION_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")
COMPLETION_KEYWORDS = ("as", "import", "in", "otherwise", "split")


class CallableEntry(object):
    def __init__(self, name, kind, parameters=(), variadic=False, function=None, node=None, sweep_mode=False):
        self.name = name
        self.kind = kind
        self.parameters = tuple(parameters)
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
        output_callback=None,
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
        self.output_callback = output_callback
        self.warnings = []

    def visit(self, node):
        method_name = "visit_" + type(node).__name__
        if self.debug:
            print(f"EXEC: {type(node).__name__}, {getattr(node, 'token', None)}")
        visitor = getattr(self, method_name, self.generic_visit)
        return visitor(node)

    def generic_visit(self, node):
        raise DiceRuntimeError("internal error: no visit_{} method".format(type(node).__name__))

    def interpret(self):
        result = self.evaluate(self.ast)
        if isinstance(result, ChartSpec):
            self.executor.append_chart(result)
            result = None
        auto_rendered = self.executor.flush_pending_report_at_end()
        if result is None and auto_rendered is not None:
            return auto_rendered
        return result

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

    def _identifier_names(self, node):
        names = set()
        if node is None:
            return names
        if type(node).__name__ == "Val" and getattr(getattr(node, "token", None), "type", None) == ID:
            names.add(node.value)
        for value in getattr(node, "__dict__", {}).values():
            if isinstance(value, list):
                for item in value:
                    names.update(self._identifier_names(item))
            else:
                names.update(self._identifier_names(value))
        return names

    def _dsl_parameter_specs(self, node):
        seen = set()
        param_names = [param.name.value for param in node.params]
        parameters = []
        for param in node.params:
            name = param.name.value
            if name in seen:
                self.exception(
                    "Duplicate parameter name {}".format(name),
                    node=param,
                    hint="Rename one of the parameters so each parameter name is unique.",
                )
            seen.add(name)
            if param.default is not None:
                forbidden = sorted(name for name in param_names if name in self._identifier_names(param.default))
                if forbidden:
                    self.exception(
                        "parameter defaults may only reference globals, not parameters: {}".format(", ".join(forbidden)),
                        node=param.default,
                    )
            parameters.append(
                ParameterSpec(
                    name=name,
                    default_value=param.default if param.default is not None else MISSING,
                )
            )
        return tuple(parameters)

    def register_function_definition(self, node):
        self._register_callable(
            CallableEntry(
                node.name.value,
                "dsl",
                parameters=self._dsl_parameter_specs(node),
                node=node,
            )
        )

    def register_function(self, function, name=None):
        metadata = get_dicefunction_metadata(function)
        if metadata is None:
            self.exception("Python functions must be decorated with @dicefunction to be registered")
        callable_name = name if name is not None else metadata.export_name
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
        params = []
        for parameter in getattr(entry, "parameters", ()):
            if parameter.has_default:
                params.append("{}=...".format(parameter.name))
            else:
                params.append(parameter.name)
        if not params:
            params = ["arg{}".format(index + 1) for index in range(len(getattr(entry, "parameters", ())))]
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

    def warn(self, message="", node=None, hint=None):
        self.warnings.append(DiagnosticWarning(message, span=self._node_span(node), hint=hint))

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
        try:
            return validate_runtime_value(value)
        except Exception as error:
            self.exception(str(error))

    def _literal_scalar_value(self, value, *, node, context, hint=None):
        if isinstance(value, (int, float, str, TupleValue, RecordValue)):
            return value
        if isinstance(value, Sweep):
            if not value.is_unswept():
                self.exception(context, node=node, hint=hint)
            value = value.only_value()
        if isinstance(value, Distribution):
            items = list(value.items())
            if len(items) == 1 and abs(items[0][1] - 1.0) <= PROBABILITY_TOLERANCE:
                return items[0][0]
        self.exception(context, node=node, hint=hint)

    def _bool_masses(self, condition, node=None):
        invalid = [outcome for outcome in condition.keys() if outcome not in (TRUE, FALSE)]
        if invalid:
            self.exception(
                "split guards must evaluate to Bernoulli outcomes 0 or 1, got {}".format(invalid),
                node=node,
                hint="Use a comparison like 'roll >= 15' or convert each guard to 0 or 1.",
            )
        return condition[TRUE], condition[FALSE]

    def _evaluate_in_global_scope(self, node):
        saved_scopes = self.local_scopes
        self.local_scopes = []
        try:
            return self.visit(node)
        finally:
            self.local_scopes = saved_scopes

    def _resolve_default_argument(self, entry, parameter):
        default = parameter.default_value
        if getattr(entry, "kind", None) == "dsl":
            return self._evaluate_in_global_scope(default)
        if isinstance(default, DiceDefault):
            return self._evaluate_in_global_scope(default.ast)
        return default

    def _bind_call_arguments(self, entry, args, node=None):
        if entry.variadic:
            if getattr(entry, "variadic_keyword_arguments", False):
                positional_values = []
                keyword_values = {}
                parameter_indexes = {parameter.name: parameter for parameter in getattr(entry, "parameters", ())}
                saw_keyword = False
                for arg in args:
                    if arg.name is None:
                        if saw_keyword:
                            self.exception(
                                "positional arguments cannot follow keyword arguments",
                                node=arg,
                                hint=self._call_hint(entry),
                            )
                        positional_values.append(self.visit(arg.value))
                        continue

                    saw_keyword = True
                    keyword = arg.name.value
                    parameter = parameter_indexes.get(keyword)
                    if parameter is None:
                        self.exception(
                            "function {} got an unknown keyword argument {}".format(entry.name, keyword),
                            node=arg,
                            hint=self._call_hint(entry),
                        )
                    if keyword in keyword_values:
                        self.exception(
                            "function {} got multiple values for argument {}".format(entry.name, keyword),
                            node=arg,
                            hint=self._call_hint(entry),
                        )
                    keyword_values[keyword] = self.visit(arg.value)

                for parameter in getattr(entry, "parameters", ()):
                    if parameter.name in keyword_values:
                        continue
                    if parameter.has_default:
                        keyword_values[parameter.name] = self._resolve_default_argument(entry, parameter)
                        continue
                    self.exception(
                        "function {} missing required argument {}".format(entry.name, parameter.name),
                        node=node,
                        hint=self._call_hint(entry),
                    )
                return positional_values, keyword_values

            for arg in args:
                if arg.name is not None:
                    self.exception(
                        "function {} does not accept keyword arguments".format(entry.name),
                        node=arg,
                        hint=self._call_hint(entry),
                    )
            return [self.visit(arg.value) for arg in args]

        parameters = getattr(entry, "parameters", ())
        bound = [MISSING] * len(parameters)
        parameter_indexes = {parameter.name: index for index, parameter in enumerate(parameters)}
        positional_index = 0
        saw_keyword = False

        for arg in args:
            if arg.name is None:
                if saw_keyword:
                    self.exception(
                        "positional arguments cannot follow keyword arguments",
                        node=arg,
                        hint=self._call_hint(entry),
                    )
                if positional_index >= len(parameters):
                    self.exception(
                        "function {} expected at most {} arguments but got {}".format(
                            entry.name,
                            len(parameters),
                            len(args),
                        ),
                        node=node,
                        hint=self._call_hint(entry),
                    )
                bound[positional_index] = self.visit(arg.value)
                positional_index += 1
                continue

            saw_keyword = True
            keyword = arg.name.value
            if keyword not in parameter_indexes:
                self.exception(
                    "function {} got an unknown keyword argument {}".format(entry.name, keyword),
                    node=arg,
                    hint=self._call_hint(entry),
                )
            parameter_index = parameter_indexes[keyword]
            if bound[parameter_index] is not MISSING:
                self.exception(
                    "function {} got multiple values for argument {}".format(entry.name, keyword),
                    node=arg,
                    hint=self._call_hint(entry),
                )
            bound[parameter_index] = self.visit(arg.value)

        for index, parameter in enumerate(parameters):
            if bound[index] is not MISSING:
                continue
            if parameter.has_default:
                bound[index] = self._resolve_default_argument(entry, parameter)
                continue
            self.exception(
                "function {} missing required argument {}".format(entry.name, parameter.name),
                node=node,
                hint=self._call_hint(entry),
            )
        return bound

    def _call_dsl_function(self, entry, values):
        function = entry.node
        if entry.name in self.call_stack:
            self.exception(
                "Recursion not supported for {}".format(entry.name),
                node=function,
                hint="Rewrite the function using a closed-form expression or a builtin helper.",
            )
        local_scope = {parameter.name: value for parameter, value in zip(entry.parameters, values)}
        self.call_stack.append(entry.name)
        self.local_scopes.append(local_scope)
        try:
            return self.visit(function.body)
        finally:
            self.local_scopes.pop()
            self.call_stack.pop()

    def _call_host_function(self, entry, values):
        if entry.variadic and getattr(entry, "variadic_keyword_arguments", False):
            positional_values, keyword_values = values
            return self._validate_runtime_value(entry.function(*positional_values, **keyword_values))
        return self._validate_runtime_value(entry.function(*values))

    def _parse_imported_source(self, resolved_path):
        with open(resolved_path, encoding="utf-8") as handle:
            text = handle.read()
        return DiceParser(Lexer(text, source_name=resolved_path)).parse()

    def _load_imported_python_module(self, resolved_path):
        module_name = "dice_import_{}".format(hashlib.sha256(resolved_path.encode("utf-8")).hexdigest())
        spec = importlib.util.spec_from_file_location(module_name, resolved_path)
        if spec is None or spec.loader is None:
            raise DiceRuntimeError("Could not import {!r}".format(resolved_path))
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        return module

    def _import_python_exports(self, module, node):
        exported = []
        for value in module.__dict__.values():
            metadata = get_dicefunction_metadata(value)
            if metadata is None:
                continue
            if getattr(value, "__module__", None) != module.__name__:
                continue
            exported.append(value)
        if not exported:
            self.exception(
                "Python module {} defines no @dicefunction exports".format(getattr(module, "__file__", module.__name__)),
                node=node.path,
                hint="Decorate exported functions with @dicefunction before importing the file.",
            )
        for function in exported:
            self.register_function(function)

    def visit_VarOp(self, node):
        if node.op.type == SEMI:
            last_result = None
            for n in node.nodes:
                if type(n).__name__ == "FunctionDef":
                    continue
                statement_result = self.visit(n)
                if isinstance(statement_result, ChartSpec) and not (
                    type(n).__name__ == "BinOp" and n.op.type == ASSIGN
                ):
                    self.executor.append_chart(statement_result)
                    last_result = None
                    continue
                last_result = statement_result
            return last_result
        self.exception("{} not implemented".format(node), node=node)

    def visit_FunctionDef(self, node):
        return None

    def visit_BlockBody(self, node):
        for statement in node.statements:
            self.visit(statement)
        return self.visit(node.result)

    def visit_LocalAssign(self, node):
        if not self.local_scopes:
            self.exception("local assignments are only valid inside function bodies", node=node)
        local_scope = self.local_scopes[-1]
        if node.name.value not in local_scope and node.name.value in self.global_scope:
            self.warn(
                "local assignment shadows global {}".format(node.name.value),
                node=node,
                hint="This assignment only updates the function-local binding, not the global value.",
            )
        local_scope[node.name.value] = self.visit(node.value)
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
        self.imported_files.add(resolved_path)
        self.import_stack.append(resolved_path)
        previous_dir = self.current_dir
        self.current_dir = os.path.dirname(resolved_path)
        try:
            if resolved_path.endswith(".py"):
                module = self._load_imported_python_module(resolved_path)
                self._import_python_exports(module, node)
                return None
            ast = self._parse_imported_source(resolved_path)
            return self.evaluate(ast)
        finally:
            self.current_dir = previous_dir
            self.import_stack.pop()

    def visit_SweepLiteral(self, node):
        if type(node.values).__name__ == "RangeLiteral":
            start = self._literal_scalar_value(
                self.visit(node.values.start),
                node=node.values.start,
                context="expected an integer range start",
            )
            end = self._literal_scalar_value(
                self.visit(node.values.end),
                node=node.values.end,
                context="expected an integer range end",
            )
            if not isinstance(start, int):
                self.exception("expected an integer range start", node=node.values.start)
            if not isinstance(end, int):
                self.exception("expected an integer range end", node=node.values.end)
            stop = end + 1 if node.values.inclusive_end else end
            values = tuple(range(start, stop))
        else:
            values = []
            for child in node.values:
                new_value = self._literal_scalar_value(
                    self.visit(child),
                    node=child,
                    context="sweep construction expects scalar values",
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
                start = self._literal_scalar_value(
                    self.visit(entry.value.start),
                    node=entry.value.start,
                    context="expected an integer range start",
                )
                end = self._literal_scalar_value(
                    self.visit(entry.value.end),
                    node=entry.value.end,
                    context="expected an integer range end",
                )
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
            values = self._bind_call_arguments(entry, node.args, node=node)
            return self._with_runtime_context(node, lambda: self._call_dsl_function(entry, values))
        if function_name not in self.executor.functions:
            self.exception(
                "Unknown function {}".format(function_name),
                node=node,
                hint=self._identifier_hint(function_name, prefer_call=True),
            )
        entry = self.executor.functions[function_name]
        values = self._bind_call_arguments(entry, node.args, node=node)
        return self._with_runtime_context(node, lambda: self._call_host_function(entry, values))

    def visit_Split(self, node):
        if node.implicit_zero_warning:
            self.warn(
                "split omitted a final branch and will default remaining cases to 0",
                node=node,
                hint="Add '| otherwise -> 0' explicitly if this is intentional, or use '||' to terminate with zero.",
            )
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
                            "split expression left unmatched cases for {}".format(node.name.value),
                            node=node,
                            hint="Add an 'otherwise -> ...' clause to cover the remaining cases.",
                        )
                finally:
                    self.local_scopes.pop()
        return _accumulate_distribution_contributions(contributions)

    def visit_TenOp(self, node):
        if node.op1.type == RES and node.op2.type == ELSE:
            condition = self.visit(node.left)
            success_value = self.visit(node.middle)
            self.local_scopes.append({"@": success_value})
            try:
                else_value = self.visit(node.right)
            finally:
                self.local_scopes.pop()
            return self._with_runtime_context(
                node,
                lambda: self.executor.reselse(condition, success_value, else_value),
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
        if node.op.type == CARET:
            return self._with_runtime_context(node, lambda: self.executor.repeat_sum(self.visit(node.right), self.visit(node.left)))
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
            value = self.visit(node.value)
            if self.output_callback is not None:
                self.output_callback(value)
            else:
                print(value)
            return None
        self.exception("{} not implemented".format(node), node=node)

    def visit_TupleLiteral(self, node):
        return TupleValue(self.visit(item) for item in node.items)

    def visit_RecordLiteral(self, node):
        return RecordValue((entry.key, self.visit(entry.value)) for entry in node.entries)

    def visit_SweepIndex(self, node):
        value = self.visit(node.value)
        clauses = []
        for clause in node.clauses:
            clause_type = type(clause).__name__
            if clause_type == "SweepIndexCoordinate":
                clauses.append(
                    {
                        "kind": "coordinate",
                        "key": clause.key,
                        "value": self.visit(clause.value),
                    }
                )
                continue
            if clause_type == "SweepIndexFilter":
                clauses.append(
                    {
                        "kind": "filter",
                        "key": clause.key,
                        "value": self.visit(clause.value),
                    }
                )
                continue
            clauses.append({"kind": "value", "value": self.visit(clause)})
        return self._with_runtime_context(node, lambda: sweep_index(value, clauses))

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
