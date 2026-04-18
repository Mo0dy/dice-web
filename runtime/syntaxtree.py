#!/usr/bin/env python3


"""Classes that make up an abstract syntax tree.

Each node holds operator(s) and data to operate on."""


class AST(object):
    """The baseclass for all AST nodes"""


class Op(AST):
    def __init__(self, op):
        self.token = self.op = op

    def __repr__(self):
        result = "Op: {}".format(self.op)
        return result


class UnOp(AST):
    """Node for all unary operators"""
    def __init__(self, value, op):
        self.value = value
        self.token = self.op = op

    def __repr__(self):
        result = "UnOp: {}".format(self.op)
        node = str(self.value)
        result += '\t|'.join(('\n' + "node: " + str(node).lstrip()).splitlines(True))
        return result


class BinOp(AST):
    """Node for all binary operators"""
    def __init__(self, left, op, right):
        self.left = left
        self.token = self.op = op
        self.right = right

    def __repr__(self):
        result = "BinOp: {}".format(self.op)
        left_node = str(self.left)
        right_node = str(self.right)
        result += '\t|'.join(('\n' + "left: " + str(self.left).lstrip()).splitlines(True))
        result += '\t|'.join(('\n' + "right: " + str(self.right).lstrip()).splitlines(True))
        return result


class TenOp(AST):
    """Node for all tenary operators"""
    def __init__(self, left, op, middle, op2, right):
        self.left = left
        self.middle = middle
        self.right = right
        self.token1 = self.op1 = op
        self.token2 = self.op2 = op2

    def __repr__(self):
        # NOTE: copyied from BinOp
        result = "TenOp: {}, {}".format(self.op1, self.op2)
        left_node = str(self.left)
        middle_node = str(self.middle)
        right_node = str(self.right)
        result += '\t|'.join(('\n' + "left: " + str(self.left).lstrip()).splitlines(True))
        result += '\t|'.join(('\n' + "middle " + str(self.middle).lstrip()).splitlines(True))
        result += '\t|'.join(('\n' + "right: " + str(self.right).lstrip()).splitlines(True))
        return result


class VarOp(AST):
    """Node for all variadic operators"""
    def __init__(self, op, nodes):
        self.token = self.op = op
        self.nodes = nodes

    def __repr__(self):
        # NOTE: copied from TenOp
        result = "VarOp: {}".format(self.op)
        for node in self.nodes:
            node = str(node)
            result += '\t|'.join(('\n' + "node: " + str(node).lstrip()).splitlines(True))
        return result


class FunctionDef(AST):
    """Top-level function definition."""
    def __init__(self, name, params, body):
        self.name = name
        self.params = params
        self.body = body
        self.token = name.token

    def __repr__(self):
        result = "FunctionDef: {}".format(self.name.value)
        result += '\t|'.join(('\n' + "params: " + ", ".join(param.name.value for param in self.params)).splitlines(True))
        result += '\t|'.join(('\n' + "body: " + str(self.body).lstrip()).splitlines(True))
        return result


class Call(AST):
    """Function call expression."""
    def __init__(self, name, args):
        self.name = name
        self.args = args
        self.token = name.token

    def __repr__(self):
        result = "Call: {}".format(self.name.value)
        for arg in self.args:
            result += '\t|'.join(('\n' + "arg: " + str(arg).lstrip()).splitlines(True))
        return result


class Param(AST):
    """Named function parameter with an optional default expression."""

    def __init__(self, name, default=None):
        self.name = name
        self.default = default
        self.token = name.token

    def __repr__(self):
        if self.default is None:
            return "Param: {}".format(self.name.value)
        return "Param: {}={}".format(self.name.value, self.default)


class CallArg(AST):
    """Function call argument, optionally passed by keyword."""

    def __init__(self, value, name=None):
        self.name = name
        self.value = value
        self.token = name.token if name is not None else getattr(value, "token", getattr(value, "token1", None))

    def __repr__(self):
        if self.name is None:
            return "CallArg: {}".format(self.value)
        return "CallArg: {}={}".format(self.name.value, self.value)


class LocalAssign(AST):
    """Function-local assignment inside an indented function body."""

    def __init__(self, name, value, token):
        self.name = name
        self.value = value
        self.token = token

    def __repr__(self):
        return "LocalAssign: {}={}".format(self.name.value, self.value)


class BlockBody(AST):
    """Indented function body consisting of local assignments and a final expression."""

    def __init__(self, statements, result, token):
        self.statements = statements
        self.result = result
        self.token = token

    def __repr__(self):
        result = "BlockBody"
        for statement in self.statements:
            result += '\t|'.join(('\n' + "statement: " + str(statement).lstrip()).splitlines(True))
        result += '\t|'.join(('\n' + "result: " + str(self.result).lstrip()).splitlines(True))
        return result


class SplitClause(AST):
    """One guarded clause in a split expression."""
    def __init__(self, condition, result, otherwise=False):
        self.condition = condition
        self.result = result
        self.otherwise = otherwise
        self.token = result.token

    def __repr__(self):
        label = "otherwise" if self.otherwise else str(self.condition).lstrip()
        result = "SplitClause: {}".format(label)
        result += '\t|'.join(('\n' + "result: " + str(self.result).lstrip()).splitlines(True))
        return result


class Split(AST):
    """Expression-level split with a shared bound value."""
    def __init__(self, value, name, clauses, token, implicit_zero_warning=False):
        self.value = value
        self.name = name
        self.clauses = clauses
        self.token = token
        self.implicit_zero_warning = implicit_zero_warning

    def __repr__(self):
        result = "Split: {}".format(self.name.value)
        result += '\t|'.join(('\n' + "value: " + str(self.value).lstrip()).splitlines(True))
        for clause in self.clauses:
            result += '\t|'.join(('\n' + "clause: " + str(clause).lstrip()).splitlines(True))
        return result


class Import(AST):
    """Top-level import statement."""
    def __init__(self, path, token):
        self.path = path
        self.token = token

    def __repr__(self):
        return "Import: {}".format(self.path.value)


class Named(AST):
    """Attach a semantic name to another AST value."""
    def __init__(self, name, value):
        self.name = name
        self.value = value
        self.token = name.token

    def __repr__(self):
        result = "Named: {}".format(self.name.value)
        result += '\t|'.join(('\n' + "value: " + str(self.value).lstrip()).splitlines(True))
        return result


class RangeLiteral(AST):
    """Finite range literal with configurable end inclusivity."""

    def __init__(self, start, end, inclusive_end, token):
        self.start = start
        self.end = end
        self.inclusive_end = inclusive_end
        self.token = token

    def __repr__(self):
        op = ".." if self.inclusive_end else "..<"
        return "RangeLiteral: {}{}{}".format(self.start, op, self.end)


class MeasureEntry(AST):
    """One entry inside a finite-measure literal."""

    def __init__(self, value, weight=None, token=None):
        self.value = value
        self.weight = weight
        self.token = token if token is not None else getattr(value, "token", None)

    def __repr__(self):
        if self.weight is None:
            return "MeasureEntry: {}".format(self.value)
        return "MeasureEntry: {} @ {}".format(self.value, self.weight)


class MeasureLiteral(AST):
    """Finite weighted measure literal."""

    def __init__(self, entries, token):
        self.entries = entries
        self.token = token

    def __repr__(self):
        result = "MeasureLiteral"
        for entry in self.entries:
            result += '\t|'.join(('\n' + "entry: " + str(entry).lstrip()).splitlines(True))
        return result


class SweepLiteral(AST):
    """Bracket-based sweep literal."""

    def __init__(self, values, token, name=None):
        self.values = values
        self.token = token
        self.name = name

    def __repr__(self):
        label = self.name.value if self.name is not None else "_"
        return "SweepLiteral: {} => {}".format(label, self.values)


class TupleLiteral(AST):
    """Tuple literal."""

    def __init__(self, items, token):
        self.items = items
        self.token = token

    def __repr__(self):
        result = "TupleLiteral"
        for item in self.items:
            result += '\t|'.join(('\n' + "item: " + str(item).lstrip()).splitlines(True))
        return result


class RecordEntry(AST):
    """One entry inside a record literal."""

    def __init__(self, key, key_type, value, token):
        self.key = key
        self.key_type = key_type
        self.value = value
        self.token = token

    def __repr__(self):
        return "RecordEntry: {}: {}".format(self.key, self.value)


class RecordLiteral(AST):
    """Record literal."""

    def __init__(self, entries, token):
        self.entries = entries
        self.token = token

    def __repr__(self):
        result = "RecordLiteral"
        for entry in self.entries:
            result += '\t|'.join(('\n' + "entry: " + str(entry).lstrip()).splitlines(True))
        return result


class SweepIndexCoordinate(AST):
    """One coordinate entry inside sweep indexing."""

    def __init__(self, key, key_type, value, token):
        self.key = key
        self.key_type = key_type
        self.value = value
        self.token = token

    def __repr__(self):
        return "SweepIndexCoordinate: {}: {}".format(self.key, self.value)


class SweepIndexFilter(AST):
    """One axis-domain filter inside sweep indexing."""

    def __init__(self, key, key_type, value, token):
        self.key = key
        self.key_type = key_type
        self.value = value
        self.token = token

    def __repr__(self):
        return "SweepIndexFilter: {} in {}".format(self.key, self.value)


class SweepIndex(AST):
    """Postfix sweep indexing expression."""

    def __init__(self, value, clauses, token):
        self.value = value
        self.clauses = clauses
        self.token = token

    def __repr__(self):
        result = "SweepIndex"
        result += '\t|'.join(('\n' + "value: " + str(self.value).lstrip()).splitlines(True))
        for clause in self.clauses:
            result += '\t|'.join(('\n' + "clause: " + str(clause).lstrip()).splitlines(True))
        return result


class Val(AST):
    """Value end node"""
    def __init__(self, token):
        self.token = token
        self.value = token.value

    def __repr__(self):
        return "{}, Val: {}".format(self.token, self.value)
