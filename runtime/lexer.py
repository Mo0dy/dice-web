#!/usr/bin/env python3

"""Lexer for the "dice" language.

Is used to convert string input into a token stream"""


import re

from diagnostics import DEFAULT_SOURCE_NAME, LexerError, SourceDocument, SourceSpan

# Tokens
INTEGER = "INTEGER"                      # integer number
FLOAT = "FLOAT"                          # float number
ROLL = "ROLL"                            # "d"
GREATER_OR_EQUAL = "GREATER_OR_EQUAL"    # ">="
LESS_OR_EQUAL = "LESS_OR_EQUAL"          # "<="
LESS = "LESS"                            # "<"
GREATER = "GREATER"                      # ">"
EQUAL = "EQUAL"                          # "=="
IN = "IN"                                # "in"
PLUS = "PLUS"                            # "+"
MINUS = "MINUS"                          # "-"
MUL = "MUL"                              # "*"
DIV = "DIV"                              # "/"
FLOORDIV = "FLOORDIV"                    # "//"
RES = "RES"                              # "->"
PIPE = "PIPE"                            # "$"
AVG = "AVG"                              # "~"
PROP = "PROP"                            # "!"
ELSE = "ELSE"                            # "|"
LBRACK = "LBRACK"                        # "["
RBRACK = "RBRACK"                        # "]"
LBRACE = "LBRACE"                        # "{"
RBRACE = "RBRACE"                        # "}"
COMMA = "COMMA"                          # ","
COLON = "COLON"                          # ":"
AT = "AT"                                # "@"
RANGE = "RANGE"                          # ".."
RANGE_EXCLUSIVE = "RANGE_EXCLUSIVE"      # "..<"
ADV = "ADV"                              # "d+"
DIS = "DIS"                              # "d-"
LPAREN = "LPAREN"                        # "("
RPAREN = "RPAREN"                        # ")"
ELSEDIV = "ELSEDIV"                      # "|/"
ELSEFLOORDIV = "ELSEFLOORDIV"            # "|//"
HIGH = "HIGH"                            # "h"
LOW = "LOW"                              # "l"
EOF = "EOF"                              # end of file
SEMI = "SEMI"                            # "SEMI"
ID = "ID"                                # any valid variable defenition
ASSIGN = "ASSIGN"                        # "="
PRINT = "PRINT"                          # "print"
STRING = "STRING"                        # anything inside ""

MATCH = "MATCH"                          # "match"
AS = "AS"                                # "as"
OTHERWISE = "OTHERWISE"                  # "otherwise"
IMPORT = "IMPORT"                        # "import"



class Token(object):
    """Basic token for the interpreter. Holds type and value"""
    def __init__(self, type, value=None, span=None):
        self.type = type
        self.value = value
        self.span = span

    def __repr__(self):
        return "Token: {type}, {value}".format(type=self.type, value=self.value)

class Lexer(object):
    """Generate tokensteam from string input for dice language"""

    def __init__(self, string_input, source_name=DEFAULT_SOURCE_NAME):
        """test = complete text to be interpreted"""
        normalized_text = self.normalize_input(string_input)
        # stores the string that has yet to interpreted
        self.string_input = normalized_text
        # keep the original text in case needed
        self.original_text = normalized_text
        self.source_document = SourceDocument(source_name, normalized_text)
        self.location = 0
        self.line = 1
        self.column = 1

    def exception(self, message="", hint=None, span=None):
        """Raises a lexer exception"""
        span = self.current_span() if span is None else span
        raise LexerError(message, span=span, hint=hint)

    def normalize_input(self, expression):
        """Normalizes line endings while preserving ordinary spaces."""
        return expression.replace("\r\n", "\n").replace("\r", "\n")

    def current_span(self):
        return SourceSpan(
            self.source_document,
            self.location,
            self.location,
            self.line,
            self.column,
            self.line,
            self.column,
        )

    def _advance(self, text):
        for char in text:
            self.location += 1
            if char == "\n":
                self.line += 1
                self.column = 1
            else:
                self.column += 1

    def _consume(self, count):
        consumed = self.string_input[:count]
        self.string_input = self.string_input[count:]
        self._advance(consumed)
        return consumed

    def _span_from_consumed(self, start_index, start_line, start_column, consumed):
        if not consumed:
            return SourceSpan(
                self.source_document,
                start_index,
                start_index,
                start_line,
                start_column,
                start_line,
                start_column,
            )
        return SourceSpan(
            self.source_document,
            start_index,
            self.location,
            start_line,
            start_column,
            self.line,
            self.column,
        )

    def next_token(self):
        """Returns next token in tokenstream"""
        while self.string_input and self.string_input[0] in [" ", "\t"]:
            self._consume(1)

        if self.string_input.startswith("#"):
            comment_end = 1
            while comment_end < len(self.string_input) and self.string_input[comment_end] != "\n":
                comment_end += 1
            self._consume(comment_end)
            return self.next_token()

        if self.string_input.startswith('"'):
            next_quote = self.string_input.find('"', 1)
            next_newline = self.string_input.find("\n", 1)
            if next_quote == -1 or (next_newline != -1 and next_quote > next_newline):
                self.exception(
                    "unterminated string literal",
                    hint='Close the string with a matching double quote, for example "fire bolt".',
                )

        # Matches tokens with regex

        # all regular expressions for tokens and funcitons generating them from the matched string
        # NOTE: more complex symbols need to be matched first if they contain less complex symbols
        # e.g. -> before -
        # NOTE: no need to match beginning of string because re.match is used
        token_re_list = [
            [r'".*?"', lambda x: Token(STRING, x[1:-1])],
            [r"print\b", lambda x: Token(PRINT, x)],
            [r"match\b", lambda x: Token(MATCH, x)],
            [r"as\b", lambda x: Token(AS, x)],
            [r"otherwise\b", lambda x: Token(OTHERWISE, x)],
            [r"import\b", lambda x: Token(IMPORT, x)],
            [r"in\b", lambda x: Token(IN, x)],
            # d+ needed to not confuse indexing (d20.20)
            [r"\n",    lambda x: Token(SEMI, x)],
            [r"\;",    lambda x: Token(SEMI, x)],
            [r"h(?=\b|\s|\d|\(|\[|\{|\"|\!|\~|\-)", lambda x: Token(HIGH, x)],
            [r"l(?=\b|\s|\d|\(|\[|\{|\"|\!|\~|\-)", lambda x: Token(LOW, x)],
            [r"\|//", lambda x: Token(ELSEFLOORDIV, x)],
            [r"\|\/", lambda x: Token(ELSEDIV, x)],
            [r"\(",   lambda x: Token(LPAREN, x)],
            [r"\)",   lambda x: Token(RPAREN, x)],
            [r"\{",   lambda x: Token(LBRACE, x)],
            [r"\}",   lambda x: Token(RBRACE, x)],
            [r"d\-",  lambda x: Token(DIS, x)],
            [r"d\+",  lambda x: Token(ADV, x)],
            [r"\.\.<", lambda x: Token(RANGE_EXCLUSIVE, x)],
            [r"\.\.", lambda x: Token(RANGE, x)],
            [r"//",   lambda x: Token(FLOORDIV, x)],
            [r"\:",   lambda x: Token(COLON, x)],
            [r"@",    lambda x: Token(AT, x)],
            [r"\,",   lambda x: Token(COMMA, x)],
            [r"\[",   lambda x: Token(LBRACK, x)],
            [r"\]",   lambda x: Token(RBRACK, x)],
            [r"\-\>", lambda x: Token(RES, x)],
            [r"\$",   lambda x: Token(PIPE, x)],
            [r"~",    lambda x: Token(AVG, x)],
            [r"\!",   lambda x: Token(PROP, x)],
            [r"\|",   lambda x: Token(ELSE, x)],
            [r"d(?=\b|\s|\d|\(|\[|\{|\"|\!|\~|\-)", lambda x: Token(ROLL, x)],
            [r"\>=",  lambda x: Token(GREATER_OR_EQUAL, x)],
            [r"\<=",  lambda x: Token(LESS_OR_EQUAL, x)],
            [r"\<",   lambda x: Token(LESS, x)],
            [r">",    lambda x: Token(GREATER, x)],
            [r"==",   lambda x: Token(EQUAL, x)],
            [r"\+",   lambda x: Token(PLUS, x)],
            [r"\-",   lambda x: Token(MINUS, x)],
            [r"\*",   lambda x: Token(MUL, x)],
            [r"/",    lambda x: Token(DIV, x)],
            [r"\=",   lambda x: Token(ASSIGN, x)],
            # try to match anything else to a variable or number
            [r"\d+\.\d+",  lambda x: Token(FLOAT, float(x))],
            [r"\d+",  lambda x: Token(INTEGER, int(x))],
            [r"\w+",  lambda x: Token(ID, x)],
        ]

        # check tokens in order
        for regex, token_gen in token_re_list:
            # match only matches from the beginning of the string
            match = re.match(regex, self.string_input)
            if match:
                start_index = self.location
                start_line = self.line
                start_column = self.column
                consumed = self._consume(len(match[0]))
                span = self._span_from_consumed(start_index, start_line, start_column, consumed)
                # generate token from generating function
                token = token_gen(match.group(0))
                token.span = span
                return token

        # can't find anything anymore but still input string
        if self.string_input:
            snippet = self.string_input.split("\n", 1)[0]
            self.exception(
                "could not tokenize input starting at {!r}".format(snippet),
                hint="Check for an unsupported character or a missing quote.",
            )

        # end of token stream
        return Token(EOF, "EOF", span=self.current_span())
