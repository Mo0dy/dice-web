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
    """Top-level one-line function definition."""
    def __init__(self, name, params, body):
        self.name = name
        self.params = params
        self.body = body
        self.token = name.token

    def __repr__(self):
        result = "FunctionDef: {}".format(self.name.value)
        result += '\t|'.join(('\n' + "params: " + ", ".join(param.value for param in self.params)).splitlines(True))
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


class MatchClause(AST):
    """One guarded clause in a match expression."""
    def __init__(self, condition, result, otherwise=False):
        self.condition = condition
        self.result = result
        self.otherwise = otherwise
        self.token = result.token

    def __repr__(self):
        label = "otherwise" if self.otherwise else str(self.condition).lstrip()
        result = "MatchClause: {}".format(label)
        result += '\t|'.join(('\n' + "result: " + str(self.result).lstrip()).splitlines(True))
        return result


class Match(AST):
    """Expression-level match with a shared bound value."""
    def __init__(self, value, name, clauses, token):
        self.value = value
        self.name = name
        self.clauses = clauses
        self.token = token

    def __repr__(self):
        result = "Match: {}".format(self.name.value)
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


class Val(AST):
    """Value end node"""
    def __init__(self, token):
        self.token = token
        self.value = token.value

    def __repr__(self):
        return "{}, Val: {}".format(self.token, self.value)
