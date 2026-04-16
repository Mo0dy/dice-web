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
    Match,
    MatchClause,
    Import,
    Named,
    RangeLiteral,
    MeasureEntry,
    MeasureLiteral,
    SweepLiteral,
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
    ELSEDIV,
    ELSEFLOORDIV,
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
    AS,
    OTHERWISE,
    IMPORT,
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
    DIV: "'/'",
    FLOORDIV: "'//'",
    ELSE: "'|'",
    ELSEDIV: "'|/'",
    ELSEFLOORDIV: "'|//'",
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
    ID: "identifier",
    PRINT: "'print'",
    STRING: "string",
    MATCH: "'match'",
    AS: "'as'",
    OTHERWISE: "'otherwise'",
    IMPORT: "'import'",
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
        resolve   :  comp (RES comp ((ELSE comp) | ELSEDIV | ELSEFLOORDIV)?)?
        comp      :  side ((GREATER_OR_EQUAL | LESS_OR_EQUAL | GREATER | LESS | EQUAL | IN) side)?
        side      :  term ((PLUS | MINUS) term)*
        term      :  roll ((MUL | DIV | FLOORDIV) roll)*
        roll      :  factor (ROLL factor ((HIGH | LOW) factor)?)?
        factor    :  INTEGER | FLOAT | STRING | ID | LPAREN expr RPAREN | sweep | measure | match | ROLL factor | DIS factor | ADV factor | AVG expr | PROP expr | MINUS factor
        sweep     :  LBRACK (ID COLON)? sweep_values RBRACK
        sweep_values : range_expr | expr (COMMA expr)*
        measure   :  LBRACE measure_entry (COMMA measure_entry)* RBRACE
        measure_entry : range_expr_or_expr (AT expr)?
        match     :  MATCH expr AS ID (SEMI)* match_clause ((SEMI)* match_clause)*
        match_clause : ELSE (OTHERWISE | expr) ASSIGN expr
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
        if self.current_token.type == COLON:
            legacy_token = self.current_token
            self.eat(COLON)
            value1 = RangeLiteral(value1, self.expr(), True, legacy_token)
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

    def match_expr(self):
        token = self.current_token
        self.eat(MATCH)
        value = self.expr()
        self.eat(AS)
        if self.current_token.type != ID:
            self.exception(
                "expected an identifier after 'as'",
                token=self.current_token,
                hint="Write a binding name like: match d20 as roll | roll == 20 = 10",
            )
        name = Val(self.current_token)
        self.eat(ID)
        self.eat_match_separators()
        clauses = []
        while self.current_token.type == ELSE:
            self.eat(ELSE)
            if self.current_token.type == OTHERWISE:
                self.eat(OTHERWISE)
                condition = None
                otherwise = True
            else:
                condition = self.expr()
                otherwise = False
            self.eat(ASSIGN)
            clauses.append(MatchClause(condition, self.expr(), otherwise=otherwise))
            self.eat_match_separators()
        if not clauses:
            self.exception(
                "expected at least one match clause",
                token=self.current_token,
                hint="Add a clause like '| otherwise = ...' or '| condition = ...'.",
            )
        return Match(value, name, clauses, token)

    def factor(self):
        if self.current_token.type == LBRACK:
            return self.sweep_literal()
        elif self.current_token.type == LBRACE:
            return self.measure_literal()
        elif self.current_token.type == MATCH:
            return self.match_expr()
        elif self.current_token.type == LPAREN:
            self.eat(LPAREN)
            node = self.expr()
            self.eat(RPAREN)
            return node
        elif self.current_token.type == ROLL:
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

    def call(self, name):
        self.eat(LPAREN)
        args = []
        if self.current_token.type != RPAREN:
            args.append(self.expr())
            while self.current_token.type == COMMA:
                self.eat(COMMA)
                args.append(self.expr())
        self.eat(RPAREN)
        return Call(name, args)

    def try_function_definition(self):
        if self.current_token.type != ID or self.peek_token.type != LPAREN:
            return None

        state = self.snapshot()
        try:
            name_token = self.current_token
            self.eat(ID)
            self.eat(LPAREN)
            params = []
            if self.current_token.type != RPAREN:
                if self.current_token.type != ID:
                    self.restore(state)
                    return None
                params.append(Val(self.current_token))
                self.eat(ID)
                while self.current_token.type == COMMA:
                    self.eat(COMMA)
                    if self.current_token.type != ID:
                        self.restore(state)
                        return None
                    params.append(Val(self.current_token))
                    self.eat(ID)
            self.eat(RPAREN)
            if self.current_token.type != ASSIGN:
                self.restore(state)
                return None
            self.eat(ASSIGN)
            return FunctionDef(Val(name_token), params, self.expr())
        except ParserError:
            self.restore(state)
            return None

    def roll(self):
        node = self.factor()
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

    def term(self):
        node = self.roll()
        while self.current_token.type in [MUL, DIV, FLOORDIV]:
            # MUL and DIV are both binary operators so they can be created by the same commands
            token = self.current_token
            self.eat(token.type)
            node = BinOp(node, token, self.roll())
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
                node = TenOp(node, token, new_node1, token2, self.comp())
            elif self.current_token.type == ELSEDIV:
                token2 = self.current_token
                self.eat(ELSEDIV)
                node = BinOp(node, token2, new_node1)
            elif self.current_token.type == ELSEFLOORDIV:
                token2 = self.current_token
                self.eat(ELSEFLOORDIV)
                node = BinOp(node, token2, new_node1)
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
        args = [value]
        if self.current_token.type == LPAREN:
            self.eat(LPAREN)
            if self.current_token.type != RPAREN:
                args.append(self.expr())
                while self.current_token.type == COMMA:
                    self.eat(COMMA)
                    args.append(self.expr())
            self.eat(RPAREN)
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
            nodes.append(self.statement())
            if self.current_token.type == EOF:
                break
            self.eat_one_or_more(SEMI)
            self.eat_zero_or_more(SEMI)
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
