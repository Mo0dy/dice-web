#!/usr/bin/env python3


"""The Parser generates an Abstract Syntax Tree from a tokenstream"""


from diagnostics import ParserError
from syntaxtree import (
    BinOp,
    TenOp,
    Val,
    UnOp,
    VarOp,
    Op,
    FunctionDef,
    Call,
    Split,
    SplitClause,
    Import,
    Named,
    RangeLiteral,
    MeasureEntry,
    MeasureLiteral,
    SweepLiteral,
    TupleLiteral,
    RecordLiteral,
    RecordEntry,
    SweepIndex,
    SweepIndexCoordinate,
    SweepIndexFilter,
    Param,
    CallArg,
    LocalAssign,
    BlockBody,
)
from lexer import (
    Token,
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
    RES,
    PIPE,
    PLUS,
    MINUS,
    MUL,
    CARET,
    DIV,
    FLOORDIV,
    ELSE,
    LBRACK,
    RBRACK,
    LBRACE,
    RBRACE,
    COMMA,
    COLON,
    AT,
    RANGE,
    RANGE_EXCLUSIVE,
    EOF,
    DIS,
    ADV,
    LPAREN,
    RPAREN,
    INDENT,
    DEDENT,
    HIGH,
    LOW,
    AVG,
    PROP,
    ASSIGN,
    SEMI,
    ID,
    PRINT,
    STRING,
    MATCH,
    SPLIT,
    AS,
    OTHERWISE,
    IMPORT,
    SPLITZERO,
)

TOKEN_LABELS = {
    INTEGER: "integer",
    FLOAT: "float",
    ROLL: "'d'",
    GREATER_OR_EQUAL: "'>='",
    LESS_OR_EQUAL: "'<='",
    LESS: "'<'",
    GREATER: "'>'",
    EQUAL: "'=='",
    IN: "'in'",
    RES: "'->'",
    PIPE: "'$'",
    PLUS: "'+'",
    MINUS: "'-'",
    MUL: "'*'",
    CARET: "'^'",
    DIV: "'/'",
    FLOORDIV: "'//'",
    ELSE: "'|'",
    LBRACK: "'['",
    RBRACK: "']'",
    LBRACE: "'{'",
    RBRACE: "'}'",
    COMMA: "','",
    COLON: "':'",
    AT: "'@'",
    RANGE: "'..'",
    RANGE_EXCLUSIVE: "'..<'",
    LPAREN: "'('",
    RPAREN: "')'",
    HIGH: "'h'",
    LOW: "'l'",
    AVG: "'~'",
    PROP: "'!'",
    ASSIGN: "'='",
    SEMI: "statement separator",
    INDENT: "indent",
    DEDENT: "dedent",
    ID: "identifier",
    PRINT: "'print'",
    STRING: "string",
    MATCH: "'match'",
    SPLIT: "'split'",
    AS: "'as'",
    OTHERWISE: "'otherwise'",
    IMPORT: "'import'",
    SPLITZERO: "'||'",
    EOF: "end of input",
}


class Parser(object):
    """The baseclass for all parsers."""
    def __init__(self, lexer):
        """lexer = Reference to the lexer to generate tokenstream"""
        # TODO: implement lexer as generator to reduce dependencies
        self.lexer = lexer
        # Keep one token of lookahead so assignments can be distinguished from
        # identifier expressions when parsing statements.
        self.current_token = lexer.next_token()
        self.peek_token = lexer.next_token()

    def exception(self, message="", token=None, hint=None):
        """Raises a parser exception"""
        token = self.current_token if token is None else token
        span = token.span if token is not None else None
        raise ParserError(message, span=span, hint=hint)

    def expected_token_hint(self, expected_type, actual_token):
        if actual_token.type == EOF and expected_type == RPAREN:
            return "You may be missing a closing ')'."
        if actual_token.type == EOF and expected_type == RBRACK:
            return "You may be missing a closing ']'."
        return None

    def token_label(self, token):
        if token.type == ID and token.value is not None:
            return "identifier {!r}".format(token.value)
        if token.type == INTEGER and token.value is not None:
            return "integer {!r}".format(token.value)
        if token.type == STRING and token.value is not None:
            return "string {!r}".format(token.value)
        return TOKEN_LABELS.get(token.type, token.type)

    def eat(self, type):
        """Checks for token type and advances token"""
        if type != self.current_token.type:
            self.exception(
                "expected {} but found {}".format(
                    TOKEN_LABELS.get(type, type),
                    self.token_label(self.current_token),
                ),
                token=self.current_token,
                hint=self.expected_token_hint(type, self.current_token),
            )
        self.current_token = self.peek_token
        self.peek_token = self.lexer.next_token()

    def eat_one_or_more(self, type):
        self.eat(type)
        while self.current_token.type == type:
            self.eat(type)

    def eat_zero_or_more(self, type):
        while self.current_token.type == type:
            self.eat(type)

    def snapshot(self):
        return (
            self.current_token,
            self.peek_token,
            self.lexer.string_input,
            self.lexer.location,
            self.lexer.line,
            self.lexer.column,
        )

    def restore(self, state):
        (
            self.current_token,
            self.peek_token,
            self.lexer.string_input,
            self.lexer.location,
            self.lexer.line,
            self.lexer.column,
        ) = state

    def eat_match_separators(self):
        while self.current_token.type == SEMI and self.peek_token.type in [SEMI, ELSE]:
            self.eat(SEMI)


class DiceParser(Parser):
    """Parser for the Dice language

    Grammar:
        expr      :  resolve (PIPE pipeline_target)*
        resolve   :  comp (RES comp (ELSE branch_else)?)?
        comp      :  side ((GREATER_OR_EQUAL | LESS_OR_EQUAL | GREATER | LESS | EQUAL | IN) side)?
        side      :  term ((PLUS | MINUS) term)*
        term      :  roll ((MUL | DIV | FLOORDIV) roll)*
        roll      :  factor (ROLL factor ((HIGH | LOW) factor)?)?
        factor    :  INTEGER | FLOAT | STRING | ID | LPAREN expr RPAREN | sweep | measure | split | ROLL factor | DIS factor | ADV factor | AVG expr | PROP expr | MINUS factor
        sweep     :  LBRACK (ID COLON)? sweep_values RBRACK
        sweep_values : range_expr | expr (COMMA expr)*
        measure   :  LBRACE measure_entry (COMMA measure_entry)* RBRACE
        measure_entry : range_expr_or_expr (AT expr)?
        split     :  SPLIT expr (AS ID)? (SEMI)* split_clause ((SEMI)* split_clause)* SPLITZERO?
        split_clause : ELSE (OTHERWISE RES expr | split_guard RES expr)
        pipeline_target : ID | ID LPAREN expr (COMMA expr)* RPAREN
    """

    # This just implements the grammar

    def maybe_range(self, start):
        if self.current_token.type not in (RANGE, RANGE_EXCLUSIVE):
            return start
        token = self.current_token
        inclusive_end = token.type == RANGE
        self.eat(token.type)
        return RangeLiteral(start, self.expr(), inclusive_end, token)

    def sweep_literal(self):
        token = self.current_token
        self.eat(LBRACK)
        sweep_name = None
        if self.current_token.type == ID and self.peek_token.type == COLON:
            sweep_name = Val(self.current_token)
            self.eat(ID)
            self.eat(COLON)
        value1 = self.maybe_range(self.expr())
        if isinstance(value1, RangeLiteral):
            self.eat(RBRACK)
            return SweepLiteral(value1, token, name=sweep_name)

        nodes = [value1]
        while self.current_token.type != RBRACK:
            self.eat(COMMA)
            nodes.append(self.expr())
        self.eat(RBRACK)
        return SweepLiteral(nodes, token, name=sweep_name)

    def measure_literal(self):
        token = self.current_token
        self.eat(LBRACE)
        entries = []
        while True:
            value = self.maybe_range(self.expr())
            weight = None
            if self.current_token.type == AT:
                at_token = self.current_token
                self.eat(AT)
                weight = self.expr()
            else:
                at_token = getattr(value, "token", token)
            entries.append(MeasureEntry(value, weight=weight, token=at_token))
            if self.current_token.type != COMMA:
                break
            self.eat(COMMA)
        self.eat(RBRACE)
        return MeasureLiteral(entries, token)

    def _record_key(self):
        if self.current_token.type not in (ID, INTEGER):
            self.exception(
                "record keys must be identifiers or integers",
                token=self.current_token,
                hint='Use a key like PLAN: 11 or 0: 5.',
            )
        token = self.current_token
        self.eat(token.type)
        return token

    def record_literal(self):
        token = self.current_token
        self.eat(LPAREN)
        entries = []
        seen = set()
        while True:
            key_token = self._record_key()
            normalized_key = (key_token.type, key_token.value)
            if normalized_key in seen:
                self.exception(
                    "duplicate record key {}".format(key_token.value),
                    token=key_token,
                    hint="Each record key may appear only once.",
                )
            seen.add(normalized_key)
            self.eat(COLON)
            entries.append(RecordEntry(key_token.value, key_token.type, self.expr(), key_token))
            if self.current_token.type != COMMA:
                break
            self.eat(COMMA)
            if self.current_token.type == RPAREN:
                self.exception(
                    "records do not allow trailing commas yet",
                    token=self.current_token,
                    hint='Write records like (PLAN: 11, LEVEL: 5).',
                )
            if self.current_token.type not in (ID, INTEGER) or self.peek_token.type != COLON:
                self.exception(
                    "cannot mix tuple and record entries",
                    token=self.current_token,
                    hint='Use either tuple syntax like (1, 2) or record syntax like (PLAN: 11).',
                )
        self.eat(RPAREN)
        return RecordLiteral(entries, token)

    def parenthesized_value(self):
        state = self.snapshot()
        token = self.current_token
        self.eat(LPAREN)
        if self.current_token.type == RPAREN:
            self.eat(RPAREN)
            return TupleLiteral([], token)
        if self.current_token.type in (ID, INTEGER) and self.peek_token.type == COLON:
            self.restore(state)
            return self.record_literal()
        first = self.expr()
        if self.current_token.type == RPAREN:
            self.eat(RPAREN)
            return first
        if self.current_token.type != COMMA:
            self.exception(
                "expected ',' or ')' in parenthesized expression",
                token=self.current_token,
            )
        items = [first]
        while self.current_token.type == COMMA:
            self.eat(COMMA)
            if self.current_token.type == RPAREN:
                self.eat(RPAREN)
                return TupleLiteral(items, token)
            if self.current_token.type in (ID, INTEGER) and self.peek_token.type == COLON:
                self.exception(
                    "cannot mix tuple and record entries",
                    token=self.current_token,
                    hint='Use either tuple syntax like (1, 2) or record syntax like (PLAN: 11).',
                )
            items.append(self.expr())
        self.eat(RPAREN)
        return TupleLiteral(items, token)

    def index_clause(self):
        if self.current_token.type in (ID, INTEGER) and self.peek_token.type == COLON:
            key_token = self.current_token
            self.eat(key_token.type)
            self.eat(COLON)
            return SweepIndexCoordinate(key_token.value, key_token.type, self.expr(), key_token)
        if self.current_token.type in (ID, INTEGER) and self.peek_token.type == IN:
            key_token = self.current_token
            self.eat(key_token.type)
            self.eat(IN)
            return SweepIndexFilter(key_token.value, key_token.type, self.expr(), key_token)
        return self.expr()

    def index_expr(self, value):
        token = self.current_token
        self.eat(LBRACK)
        if self.current_token.type == RBRACK:
            self.exception(
                "sweep indexing requires at least one clause",
                token=self.current_token,
                hint='Write something like expr["AC"] or expr[LEVEL: 11].',
            )
        clauses = [self.index_clause()]
        while self.current_token.type == COMMA:
            self.eat(COMMA)
            clauses.append(self.index_clause())
        self.eat(RBRACK)
        return SweepIndex(value, clauses, token)

    def primary(self):
        if self.current_token.type == LBRACK:
            return self.sweep_literal()
        elif self.current_token.type == LBRACE:
            return self.measure_literal()
        elif self.current_token.type == SPLIT:
            return self.split_expr()
        elif self.current_token.type == MATCH:
            self.exception(
                "'match' was replaced by 'split'",
                token=self.current_token,
                hint="Rewrite this as 'split ... | guard -> result'.",
            )
        elif self.current_token.type == LPAREN:
            return self.parenthesized_value()
        elif self.current_token.type == ID:
            token = self.current_token
            self.eat(ID)
            if self.current_token.type == LPAREN:
                return self.call(Val(token))
            return Val(token)
        elif self.current_token.type == STRING:
            token = self.current_token
            self.eat(STRING)
            return Val(token)
        elif self.current_token.type == FLOAT:
            token = self.current_token
            self.eat(FLOAT)
            return Val(token)
        elif self.current_token.type == INTEGER:
            token = self.current_token
            self.eat(INTEGER)
            return Val(token)
        else:
            self.exception(
                "expected an expression",
                token=self.current_token,
                hint="Try a number, identifier, function call, parenthesized expression, or dice expression.",
            )

    def postfix(self, node):
        while self.current_token.type == LBRACK:
            node = self.index_expr(node)
        return node

    def _anonymous_name(self, token):
        return Val(Token(ID, "@", span=token.span))

    def _relative_branch_else(self, reference):
        if self.current_token.type in [GREATER_OR_EQUAL, LESS_OR_EQUAL, GREATER, LESS, EQUAL, IN, PLUS, MUL, DIV, FLOORDIV, CARET]:
            return self._continue_comp(self._anonymous_name(reference))
        return self.comp()

    def _continue_term(self, node):
        node = self._continue_repeated(node)
        while self.current_token.type in [MUL, DIV, FLOORDIV]:
            token = self.current_token
            self.eat(token.type)
            node = BinOp(node, token, self.repeated())
        return node

    def _continue_side(self, node):
        node = self._continue_term(node)
        while self.current_token.type in [PLUS, MINUS]:
            token = self.current_token
            self.eat(token.type)
            node = BinOp(node, token, self.term())
        return node

    def _continue_comp(self, node):
        node = self._continue_side(node)
        if self.current_token.type in [GREATER_OR_EQUAL, LESS_OR_EQUAL, GREATER, LESS, EQUAL, IN]:
            token = self.current_token
            self.eat(token.type)
            node = BinOp(node, token, self.side())
        return node

    def _continue_roll(self, node):
        if self.current_token.type == ROLL:
            token = self.current_token
            self.eat(ROLL)
            node2 = self.factor()
            if self.current_token.type in [HIGH, LOW]:
                token2 = self.current_token
                self.eat(token2.type)
                return TenOp(node, token, node2, token2, self.factor())
            node = BinOp(node, token, node2)
        return node

    def _continue_repeated(self, node):
        node = self._continue_roll(node)
        if self.current_token.type == CARET:
            token = self.current_token
            self.eat(CARET)
            node = BinOp(node, token, self.factor())
        return node

    def _split_guard(self, name, *, allow_anonymous_sugar):
        if not allow_anonymous_sugar:
            if self.current_token.type in [AT, GREATER_OR_EQUAL, LESS_OR_EQUAL, GREATER, LESS, EQUAL, IN, PLUS, MINUS, MUL, DIV, FLOORDIV]:
                self.exception(
                    "explicit split bindings cannot use '@' or relative guards",
                    token=self.current_token,
                    hint="Use the bound name in each guard, for example: split d20 as roll | roll == 20 -> 10",
                )
            return self.comp()
        if self.current_token.type == AT:
            return self.comp()
        if self.current_token.type in [GREATER_OR_EQUAL, LESS_OR_EQUAL, GREATER, LESS, EQUAL, IN, PLUS, MINUS, MUL, DIV, FLOORDIV]:
            return self._continue_comp(self._anonymous_name(name.token))
        return self.comp()

    def split_expr(self):
        token = self.current_token
        self.eat(SPLIT)
        value = self.expr()
        explicit_binding = False
        name = self._anonymous_name(token)
        if self.current_token.type == AS:
            explicit_binding = True
            self.eat(AS)
            if self.current_token.type != ID:
                self.exception(
                    "expected an identifier after 'as'",
                    token=self.current_token,
                    hint="Write a binding name like: split d20 as roll | roll == 20 -> 10",
                )
            name = Val(self.current_token)
            self.eat(ID)
        self.eat_match_separators()
        clauses = []
        saw_otherwise = False
        while self.current_token.type == ELSE:
            self.eat(ELSE)
            if self.current_token.type == OTHERWISE:
                self.eat(OTHERWISE)
                condition = None
                otherwise = True
                saw_otherwise = True
            else:
                condition = self._split_guard(name, allow_anonymous_sugar=not explicit_binding)
                otherwise = False
            self.eat(RES)
            clauses.append(SplitClause(condition, self.expr(), otherwise=otherwise))
            self.eat_match_separators()
        if not clauses:
            self.exception(
                "expected at least one split clause",
                token=self.current_token,
                hint="Add a clause like '| otherwise -> 0' or '| == 20 -> 10'.",
            )
        zero_node = Val(Token(INTEGER, 0, span=token.span))
        if self.current_token.type == SPLITZERO:
            if saw_otherwise:
                self.exception(
                    "'||' cannot appear after an explicit otherwise branch",
                    token=self.current_token,
                    hint="Remove '||' or remove the explicit '| otherwise -> 0' branch.",
                )
            self.eat(SPLITZERO)
            clauses.append(SplitClause(None, zero_node, otherwise=True))
            return Split(value, name, clauses, token)
        if not saw_otherwise:
            clauses.append(SplitClause(None, zero_node, otherwise=True))
            return Split(value, name, clauses, token, implicit_zero_warning=True)
        return Split(value, name, clauses, token)

    def factor(self):
        if self.current_token.type == ROLL:
            token = self.current_token
            self.eat(ROLL)
            return UnOp(self.factor(), token)
        elif self.current_token.type == DIS:
            token = self.current_token
            self.eat(DIS)
            return UnOp(self.factor(), token)
        elif self.current_token.type == ADV:
            token = self.current_token
            self.eat(ADV)
            return UnOp(self.factor(), token)
        elif self.current_token.type == AVG:
            token = self.current_token
            self.eat(AVG)
            return UnOp(self.expr(), token)
        elif self.current_token.type == PROP:
            token = self.current_token
            self.eat(PROP)
            return UnOp(self.expr(), token)
        elif self.current_token.type == MINUS:
            token = self.current_token
            self.eat(MINUS)
            return UnOp(self.factor(), token)
        elif self.current_token.type == AT:
            token = self.current_token
            self.eat(AT)
            return Val(Token(ID, "@", span=token.span))
        return self.postfix(self.primary())

    def call_arg(self):
        if self.current_token.type == ID and self.peek_token.type == ASSIGN:
            name = Val(self.current_token)
            self.eat(ID)
            self.eat(ASSIGN)
            return CallArg(self.expr(), name=name)
        return CallArg(self.expr())

    def call(self, name, prefixed_args=None):
        self.eat(LPAREN)
        args = [] if prefixed_args is None else list(prefixed_args)
        if self.current_token.type != RPAREN:
            args.append(self.call_arg())
            while self.current_token.type == COMMA:
                self.eat(COMMA)
                args.append(self.call_arg())
        self.eat(RPAREN)
        return Call(name, args)

    def parameter(self):
        if self.current_token.type != ID:
            self.exception(
                "expected a parameter name",
                token=self.current_token,
                hint="Use an identifier like 'x' or 'slot_level'.",
            )
        name = Val(self.current_token)
        self.eat(ID)
        default = None
        if self.current_token.type == ASSIGN:
            self.eat(ASSIGN)
            default = self.expr()
        return Param(name, default=default)

    def parameter_list(self):
        params = []
        saw_default = False
        if self.current_token.type != RPAREN:
            while True:
                parameter = self.parameter()
                if parameter.default is None and saw_default:
                    self.exception(
                        "required parameters cannot follow parameters with defaults",
                        token=parameter.token,
                        hint="Move required parameters before optional ones.",
                    )
                if parameter.default is not None:
                    saw_default = True
                params.append(parameter)
                if self.current_token.type != COMMA:
                    break
                self.eat(COMMA)
        return params

    def function_body(self, token):
        if self.current_token.type != SEMI:
            return self.expr()

        self.eat_one_or_more(SEMI)
        self.eat(INDENT)
        self.eat_zero_or_more(SEMI)
        items = []
        while self.current_token.type != DEDENT:
            if self.current_token.type == ID and self.peek_token.type == ASSIGN:
                name = Val(self.current_token)
                self.eat(ID)
                assign_token = self.current_token
                self.eat(ASSIGN)
                items.append(LocalAssign(name, self.expr(), assign_token))
            else:
                items.append(self.expr())
            if self.current_token.type == DEDENT:
                break
            self.eat_one_or_more(SEMI)
            self.eat_zero_or_more(SEMI)
        self.eat(DEDENT)
        if not items:
            self.exception(
                "expected a function body",
                token=token,
                hint="Add at least one indented expression line after the function header.",
            )
        if any(type(item).__name__ != "LocalAssign" for item in items[:-1]):
            self.exception(
                "only assignments may appear before the final expression in a function body",
                token=getattr(items[-2], "token", token),
                hint="Use local assignments first, then end the function with one final expression line.",
            )
        if type(items[-1]).__name__ == "LocalAssign":
            self.exception(
                "function bodies must end with an expression",
                token=items[-1].token,
                hint="Add a final expression line after the local assignments.",
            )
        return BlockBody(items[:-1], items[-1], token)

    def try_function_definition(self):
        if self.current_token.type != ID or self.peek_token.type != LPAREN:
            return None

        state = self.snapshot()
        try:
            name_token = self.current_token
            self.eat(ID)
            self.eat(LPAREN)
            params = self.parameter_list()
            self.eat(RPAREN)
            if self.current_token.type != COLON:
                self.restore(state)
                return None
            self.eat(COLON)
            return FunctionDef(Val(name_token), params, self.function_body(name_token))
        except ParserError:
            self.restore(state)
            return None

    def roll(self):
        return self._continue_roll(self.factor())

    def repeated(self):
        return self._continue_repeated(self.factor())

    def term(self):
        node = self.repeated()
        while self.current_token.type in [MUL, DIV, FLOORDIV]:
            # MUL and DIV are both binary operators so they can be created by the same commands
            token = self.current_token
            self.eat(token.type)
            node = BinOp(node, token, self.repeated())
        return node

    def side(self):
        node = self.term()
        while self.current_token.type in [PLUS, MINUS]:
            # MINUS and PLUS are both binary operators so they can be created by the same commands
            token = self.current_token
            self.eat(token.type)
            node = BinOp(node, token, self.term())
        return node

    def comp(self):
        node = self.side()
        if self.current_token.type in [GREATER_OR_EQUAL, LESS_OR_EQUAL, GREATER, LESS, EQUAL, IN]:
            # store token for AST
            token = self.current_token
            self.eat(token.type)
            node = BinOp(node, token, self.side())
        return node

    def resolve(self):
        node = self.comp()
        if self.current_token.type == RES:
            # store token for AST
            token = self.current_token
            self.eat(RES)
            # cache node if tenary operator gets called
            new_node1 = self.comp()
            if self.current_token.type == ELSE:
                token2 = self.current_token
                self.eat(ELSE)
                node = TenOp(node, token, new_node1, token2, self._relative_branch_else(new_node1.token))
            else:
                # no tenery operator just normal resolve
                node = BinOp(node, token, new_node1)
        return node

    def pipeline_target(self, value):
        if self.current_token.type != ID:
            self.exception(
                "expected a function name after '$'",
                token=self.current_token,
                hint="Write a pipeline target like '$ mean' or '$ add(2)'.",
            )

        name = Val(self.current_token)
        self.eat(ID)
        args = [CallArg(value)]
        if self.current_token.type == LPAREN:
            return self.call(name, prefixed_args=args)
        return Call(name, args)

    def expr(self):
        node = self.resolve()
        while self.current_token.type == PIPE:
            self.eat(PIPE)
            node = self.pipeline_target(node)
        return node

    def statement(self):
        function_definition = self.try_function_definition()
        if function_definition:
            return function_definition
        if self.current_token.type == IMPORT:
            token = self.current_token
            self.eat(IMPORT)
            if self.current_token.type != STRING:
                self.exception(
                    "expected a string path after 'import'",
                    token=self.current_token,
                    hint='Use a quoted path like import "helpers".',
                )
            path = Val(self.current_token)
            self.eat(STRING)
            return Import(path, token)
        if self.current_token.type == ID and self.peek_token.type == ASSIGN:
            token = self.current_token
            self.eat(ID)
            left = Val(token)
            token = self.current_token
            self.eat(ASSIGN)
            return BinOp(left, token, self.expr())
        if self.current_token.type == PRINT:
            token = self.current_token
            self.eat(token.type)
            return UnOp(self.expr(), token)
        else:
            return self.expr()

    def program(self):
        nodes = []
        self.eat_zero_or_more(SEMI)
        while self.current_token.type != EOF:
            statement = self.statement()
            nodes.append(statement)
            if self.current_token.type == EOF:
                break
            if self.current_token.type == SEMI:
                self.eat_one_or_more(SEMI)
                self.eat_zero_or_more(SEMI)
                continue
            if type(statement).__name__ == "FunctionDef" and type(statement.body).__name__ == "BlockBody":
                continue
            self.exception(
                "expected a statement separator",
                token=self.current_token,
                hint="Separate top-level statements with a newline or ';'.",
            )
        if not nodes:
            self.exception(
                "expected a statement",
                token=self.current_token,
                hint="Programs can contain assignments, imports, function definitions, or expressions.",
            )
        if len(nodes) == 1:
            return nodes[0]
        return VarOp(Token(SEMI, ";"), nodes)

    def parse(self):
        node = self.program()
        if self.current_token.type != EOF:
            self.exception(
                "unexpected trailing input starting at {}".format(self.token_label(self.current_token)),
                token=self.current_token,
            )
        return node

if __name__ == "__main__":
    lexer = Lexer('a = "test"; render(a)')
    parser = DiceParser(lexer)
    ast = parser.parse()
    print(ast)
