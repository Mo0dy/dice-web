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
CARET = "CARET"                          # "^"
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
HIGH = "HIGH"                            # "h"
LOW = "LOW"                              # "l"
EOF = "EOF"                              # end of file
SEMI = "SEMI"                            # "SEMI"
INDENT = "INDENT"                        # increased indentation
DEDENT = "DEDENT"                        # decreased indentation
ID = "ID"                                # any valid variable defenition
ASSIGN = "ASSIGN"                        # "="
PRINT = "PRINT"                          # "print"
STRING = "STRING"                        # anything inside ""

MATCH = "MATCH"                          # "match"
SPLIT = "SPLIT"                          # "split"
AS = "AS"                                # "as"
OTHERWISE = "OTHERWISE"                  # "otherwise"
IMPORT = "IMPORT"                        # "import"
SPLITZERO = "SPLITZERO"                  # "||"



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
        self.pending_tokens = []
        self.indent_stack = [0]
        self.at_line_start = True
        self.expect_indent = False

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

    def _indent_width(self, text):
        width = 0
        for char in text:
            if char == "\t":
                width += 4 - (width % 4)
            else:
                width += 1
        return width

    def _emit_pending_dedent(self):
        self.indent_stack.pop()
        return Token(DEDENT, None, span=self.current_span())

    def _consume_line_comment(self):
        comment_end = 0
        while comment_end < len(self.string_input) and self.string_input[comment_end] != "\n":
            comment_end += 1
        self._consume(comment_end)

    def _consume_indentation(self):
        indentation = 0
        while indentation < len(self.string_input) and self.string_input[indentation] in [" ", "\t"]:
            indentation += 1
        return self.string_input[:indentation], indentation

    def _handle_line_start(self):
        while True:
            if not self.string_input:
                if len(self.indent_stack) > 1:
                    return self._emit_pending_dedent()
                return None

            indentation_text, indentation_count = self._consume_indentation()
            next_char = self.string_input[indentation_count:indentation_count + 1]

            if next_char == "#":
                if indentation_count:
                    self._consume(indentation_count)
                self._consume_line_comment()
                continue

            if next_char == "\n":
                if indentation_count:
                    self._consume(indentation_count)
                start_index = self.location
                start_line = self.line
                start_column = self.column
                consumed = self._consume(1)
                self.at_line_start = True
                return Token(SEMI, consumed, span=self._span_from_consumed(start_index, start_line, start_column, consumed))

            indentation_width = self._indent_width(indentation_text)
            if indentation_count:
                self._consume(indentation_count)
            current_indent = self.indent_stack[-1]
            if indentation_width > current_indent:
                if not self.expect_indent:
                    if current_indent == 0:
                        self.at_line_start = False
                        return None
                    self.exception("unexpected indentation", hint="Only function bodies introduce indentation blocks.")
                self.indent_stack.append(indentation_width)
                self.expect_indent = False
                self.at_line_start = False
                return Token(INDENT, None, span=self.current_span())
            if indentation_width < current_indent:
                while len(self.indent_stack) > 1 and indentation_width < self.indent_stack[-1]:
                    self.pending_tokens.append(self._emit_pending_dedent())
                if indentation_width != self.indent_stack[-1]:
                    self.exception("inconsistent indentation", hint="Align the block indentation with an earlier line.")
                self.at_line_start = False
                if self.pending_tokens:
                    return self.pending_tokens.pop(0)
            self.at_line_start = False
            return None

    def next_token(self):
        """Returns next token in tokenstream"""
        if self.pending_tokens:
            return self.pending_tokens.pop(0)

        if self.at_line_start:
            token = self._handle_line_start()
            if token is not None:
                return token

        while self.string_input and self.string_input[0] in [" ", "\t"]:
            self._consume(1)

        if self.string_input.startswith("#"):
            self._consume_line_comment()
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
            [r"split\b", lambda x: Token(SPLIT, x)],
            [r"as\b", lambda x: Token(AS, x)],
            [r"otherwise\b", lambda x: Token(OTHERWISE, x)],
            [r"import\b", lambda x: Token(IMPORT, x)],
            [r"in\b", lambda x: Token(IN, x)],
            # d+ needed to not confuse indexing (d20.20)
            [r"\n",    lambda x: Token(SEMI, x)],
            [r"\;",    lambda x: Token(SEMI, x)],
            [r"h(?=\b|\s|\d|\(|\[|\{|\"|\!|\~|\-)", lambda x: Token(HIGH, x)],
            [r"l(?=\b|\s|\d|\(|\[|\{|\"|\!|\~|\-)", lambda x: Token(LOW, x)],
            [r"\|\|", lambda x: Token(SPLITZERO, x)],
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
            [r"\^",   lambda x: Token(CARET, x)],
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
                if token.type == SEMI:
                    self.at_line_start = True
                elif token.type == COLON:
                    self.at_line_start = False
                    self.expect_indent = True
                else:
                    self.at_line_start = False
                    self.expect_indent = False
                return token

        # can't find anything anymore but still input string
        if self.string_input:
            snippet = self.string_input.split("\n", 1)[0]
            self.exception(
                "could not tokenize input starting at {!r}".format(snippet),
                hint="Check for an unsupported character or a missing quote.",
            )

        # end of token stream
        if len(self.indent_stack) > 1:
            return self._emit_pending_dedent()
        return Token(EOF, "EOF", span=self.current_span())
