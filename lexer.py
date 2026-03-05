"""Manual maximal-munch lexer for the ESP32 DSL."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, List, Optional


class TokenType(Enum):
    EOF = auto()
    IDENT = auto()
    INT = auto()
    FLOAT = auto()
    STRING = auto()
    TRUE = auto()
    FALSE = auto()

    LET = auto()
    CONST = auto()
    VOLATILE = auto()
    FN = auto()
    RETURN = auto()
    IF = auto()
    ELSE = auto()
    WHILE = auto()
    FOR = auto()
    LOOP = auto()
    STRUCT = auto()
    MATCH = auto()
    AS = auto()
    TASK = auto()
    SPAWN = auto()
    BUS = auto()
    DEVICE = auto()
    I2C = auto()
    SPI = auto()
    IMPORT = auto()
    UNSAFE = auto()
    UNSAFE_BLOCK = auto()

    GPIOMODE = auto()
    DIGITALWRITE = auto()
    PWMWRITE = auto()
    RGBWRITE = auto()
    ANALOGREAD = auto()
    WIFICONNECT = auto()
    DELAY = auto()

    OUT = auto()
    IN = auto()

    LPAREN = auto()
    RPAREN = auto()
    LBRACE = auto()
    RBRACE = auto()
    COMMA = auto()
    DOT = auto()
    SEMICOLON = auto()
    COLON = auto()
    ARROW = auto()
    FAT_ARROW = auto()
    AT = auto()

    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    MOD = auto()
    BIT_AND = auto()
    BIT_OR = auto()
    BIT_XOR = auto()
    SHIFT_LEFT = auto()
    SHIFT_RIGHT = auto()
    BIT_NOT = auto()
    BANG = auto()
    ASSIGN = auto()
    PLUS_ASSIGN = auto()
    MINUS_ASSIGN = auto()
    STAR_ASSIGN = auto()
    SLASH_ASSIGN = auto()
    INC = auto()
    DEC = auto()

    EQ = auto()
    NEQ = auto()
    LT = auto()
    LTE = auto()
    GT = auto()
    GTE = auto()
    AND = auto()
    OR = auto()
    DURATION = auto()


KEYWORDS: Dict[str, TokenType] = {
    "let": TokenType.LET,
    "const": TokenType.CONST,
    "volatile": TokenType.VOLATILE,
    "fn": TokenType.FN,
    "return": TokenType.RETURN,
    "if": TokenType.IF,
    "else": TokenType.ELSE,
    "while": TokenType.WHILE,
    "for": TokenType.FOR,
    "loop": TokenType.LOOP,
    "struct": TokenType.STRUCT,
    "match": TokenType.MATCH,
    "as": TokenType.AS,
    "task": TokenType.TASK,
    "spawn": TokenType.SPAWN,
    "bus": TokenType.BUS,
    "device": TokenType.DEVICE,
    "I2C": TokenType.I2C,
    "SPI": TokenType.SPI,
    "import": TokenType.IMPORT,
    "unsafe": TokenType.UNSAFE,
    "true": TokenType.TRUE,
    "false": TokenType.FALSE,
    "gpioMode": TokenType.GPIOMODE,
    "digitalWrite": TokenType.DIGITALWRITE,
    "pwmWrite": TokenType.PWMWRITE,
    "rgbWrite": TokenType.RGBWRITE,
    "analogRead": TokenType.ANALOGREAD,
    "wifiConnect": TokenType.WIFICONNECT,
    "delay": TokenType.DELAY,
    "out": TokenType.OUT,
    "in": TokenType.IN,
}


@dataclass(frozen=True)
class Token:
    """Single lexical token with exact source coordinates."""

    kind: TokenType
    lexeme: str
    line: int
    column: int


@dataclass(frozen=True)
class LexError:
    """Recoverable lexical diagnostic produced by the lexer."""

    message: str
    line: int
    column: int


class Lexer:
    """State-machine lexer with maximal munch and detailed coordinates."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.index = 0
        self.line = 1
        self.column = 1
        self.tokens: List[Token] = []
        self.errors: List[LexError] = []

    def tokenize(self) -> tuple[List[Token], List[LexError]]:
        """Tokenize the full input and return both tokens and lexing diagnostics."""

        while not self._is_at_end():
            self._scan_token()

        self.tokens.append(Token(TokenType.EOF, "", self.line, self.column))
        return self.tokens, self.errors

    def _scan_token(self) -> None:
        ch = self._peek()

        if ch in {" ", "\t", "\r"}:
            self._advance()
            return
        if ch == "\n":
            self._advance_newline()
            return

        if ch.isalpha() or ch == "_":
            self._scan_identifier()
            return

        if ch.isdigit():
            self._scan_number()
            return

        if ch == '"':
            self._scan_string()
            return

        line, column = self.line, self.column

        if ch == "/":
            next_ch = self._peek_next()
            if next_ch == "/":
                self._consume_line_comment()
                return
            if next_ch == "*":
                self._consume_block_comment()
                return

        two_char_map = {
            "->": TokenType.ARROW,
            "=>": TokenType.FAT_ARROW,
            "==": TokenType.EQ,
            "!=": TokenType.NEQ,
            "<=": TokenType.LTE,
            ">=": TokenType.GTE,
            "&&": TokenType.AND,
            "||": TokenType.OR,
            "<<": TokenType.SHIFT_LEFT,
            ">>": TokenType.SHIFT_RIGHT,
            "+=": TokenType.PLUS_ASSIGN,
            "-=": TokenType.MINUS_ASSIGN,
            "*=": TokenType.STAR_ASSIGN,
            "/=": TokenType.SLASH_ASSIGN,
            "++": TokenType.INC,
            "--": TokenType.DEC,
        }
        pair = ch + self._peek_next()
        if pair in two_char_map:
            self._advance()
            self._advance()
            self.tokens.append(Token(two_char_map[pair], pair, line, column))
            return

        one_char_map = {
            "(": TokenType.LPAREN,
            ")": TokenType.RPAREN,
            "{": TokenType.LBRACE,
            "}": TokenType.RBRACE,
            ",": TokenType.COMMA,
            ".": TokenType.DOT,
            ";": TokenType.SEMICOLON,
            ":": TokenType.COLON,
            "@": TokenType.AT,
            "+": TokenType.PLUS,
            "-": TokenType.MINUS,
            "*": TokenType.STAR,
            "/": TokenType.SLASH,
            "%": TokenType.MOD,
            "&": TokenType.BIT_AND,
            "|": TokenType.BIT_OR,
            "^": TokenType.BIT_XOR,
            "~": TokenType.BIT_NOT,
            "!": TokenType.BANG,
            "=": TokenType.ASSIGN,
            "<": TokenType.LT,
            ">": TokenType.GT,
        }
        token_kind = one_char_map.get(ch)
        if token_kind is not None:
            self._advance()
            self.tokens.append(Token(token_kind, ch, line, column))
            return

        self.errors.append(LexError(f"Unexpected character '{ch}'", line, column))
        self._advance()

    def _scan_identifier(self) -> None:
        line, column = self.line, self.column
        start = self.index
        while not self._is_at_end() and (self._peek().isalnum() or self._peek() == "_"):
            self._advance()

        lexeme = self.source[start : self.index]
        kind = KEYWORDS.get(lexeme, TokenType.IDENT)
        self.tokens.append(Token(kind, lexeme, line, column))
        if kind == TokenType.UNSAFE:
            self._scan_unsafe_block()

    def _scan_unsafe_block(self) -> None:
        """Capture raw `unsafe { ... }` payload as a single token for backend passthrough."""

        self._skip_whitespace_and_comments()

        if self._peek() != "{":
            self.errors.append(LexError("Expected '{' after unsafe", self.line, self.column))
            return

        block_line, block_col = self.line, self.column
        self._advance()
        depth = 1
        raw_chars: List[str] = []

        while not self._is_at_end() and depth > 0:
            ch = self._peek()

            if ch == '"' or ch == "'":
                raw_chars.append(self._advance())
                quote = ch
                while not self._is_at_end():
                    current = self._peek()
                    if current == "\\":
                        raw_chars.append(self._advance())
                        if not self._is_at_end():
                            raw_chars.append(self._advance())
                        continue
                    raw_chars.append(self._advance())
                    if current == quote:
                        break
                continue

            if ch == "/" and self._peek_next() == "/":
                raw_chars.append(self._advance())
                raw_chars.append(self._advance())
                while not self._is_at_end() and self._peek() != "\n":
                    raw_chars.append(self._advance())
                continue

            if ch == "/" and self._peek_next() == "*":
                raw_chars.append(self._advance())
                raw_chars.append(self._advance())
                while not self._is_at_end():
                    current = self._peek()
                    raw_chars.append(self._advance())
                    if current == "*" and self._peek() == "/":
                        raw_chars.append(self._advance())
                        break
                continue

            if ch == "{":
                depth += 1
                raw_chars.append(self._advance())
                continue

            if ch == "}":
                depth -= 1
                self._advance()
                if depth == 0:
                    break
                raw_chars.append("}")
                continue

            if ch == "\n":
                raw_chars.append("\n")
                self._advance_newline()
                continue

            raw_chars.append(self._advance())

        if depth != 0:
            self.errors.append(LexError("Unterminated unsafe block", block_line, block_col))
            return

        raw_payload = "".join(raw_chars)
        self.tokens.append(Token(TokenType.UNSAFE_BLOCK, raw_payload, block_line, block_col))

    def _skip_whitespace_and_comments(self) -> None:
        """Advance over trivia so grammar-level scanning can continue at significant tokens."""

        while not self._is_at_end():
            ch = self._peek()
            if ch in {" ", "\t", "\r"}:
                self._advance()
                continue
            if ch == "\n":
                self._advance_newline()
                continue
            if ch == "/" and self._peek_next() == "/":
                self._consume_line_comment()
                continue
            if ch == "/" and self._peek_next() == "*":
                self._consume_block_comment()
                continue
            break

    def _scan_number(self) -> None:
        """Scan int/float/base-prefixed literals and duration suffixes."""

        line, column = self.line, self.column
        start = self.index

        if self._peek() == "0" and self._peek_next() in {"x", "X"}:
            self._advance()
            self._advance()
            base_start = self.index
            while not self._is_at_end() and (self._peek().isdigit() or self._peek().lower() in {"a", "b", "c", "d", "e", "f"}):
                self._advance()
            if self.index == base_start:
                self.errors.append(LexError("Invalid hexadecimal literal", line, column))
            lexeme = self.source[start : self.index]
            self.tokens.append(Token(TokenType.INT, lexeme, line, column))
            return

        if self._peek() == "0" and self._peek_next() in {"b", "B"}:
            self._advance()
            self._advance()
            base_start = self.index
            while not self._is_at_end() and self._peek() in {"0", "1"}:
                self._advance()
            if self.index == base_start:
                self.errors.append(LexError("Invalid binary literal", line, column))
            lexeme = self.source[start : self.index]
            self.tokens.append(Token(TokenType.INT, lexeme, line, column))
            return

        while not self._is_at_end() and self._peek().isdigit():
            self._advance()

        is_float = False
        if self._peek() == "." and self._peek_next().isdigit():
            is_float = True
            self._advance()
            while not self._is_at_end() and self._peek().isdigit():
                self._advance()

        if not is_float:
            duration_start = self.index
            if self._peek() in {"m", "u"} and self._peek_next() == "s":
                self._advance()
                self._advance()
            elif self._peek() == "s":
                self._advance()

            if self.index != duration_start:
                # Keep duration suffixes strict to avoid swallowing identifiers.
                if self._peek().isalnum() or self._peek() == "_":
                    self.errors.append(LexError("Invalid duration literal suffix", line, column))
                lexeme = self.source[start : self.index]
                self.tokens.append(Token(TokenType.DURATION, lexeme, line, column))
                return

        lexeme = self.source[start : self.index]
        self.tokens.append(Token(TokenType.FLOAT if is_float else TokenType.INT, lexeme, line, column))

    def _scan_string(self) -> None:
        line, column = self.line, self.column
        self._advance()
        value_chars: List[str] = []

        while not self._is_at_end() and self._peek() != '"':
            ch = self._peek()
            if ch == "\n":
                self.errors.append(LexError("Unterminated string literal", line, column))
                return
            if ch == "\\":
                self._advance()
                escaped = self._peek()
                escaped_map = {
                    '"': '"',
                    "n": "\n",
                    "t": "\t",
                    "\\": "\\",
                }
                value_chars.append(escaped_map.get(escaped, escaped))
                self._advance()
            else:
                value_chars.append(ch)
                self._advance()

        if self._is_at_end():
            self.errors.append(LexError("Unterminated string literal", line, column))
            return

        self._advance()
        self.tokens.append(Token(TokenType.STRING, "".join(value_chars), line, column))

    def _consume_line_comment(self) -> None:
        self._advance()
        self._advance()
        while not self._is_at_end() and self._peek() != "\n":
            self._advance()

    def _consume_block_comment(self) -> None:
        self._advance()
        self._advance()
        while not self._is_at_end():
            if self._peek() == "*" and self._peek_next() == "/":
                self._advance()
                self._advance()
                return
            if self._peek() == "\n":
                self._advance_newline()
            else:
                self._advance()

        self.errors.append(LexError("Unterminated block comment", self.line, self.column))

    def _peek(self) -> str:
        return "\0" if self._is_at_end() else self.source[self.index]

    def _peek_next(self) -> str:
        if self.index + 1 >= len(self.source):
            return "\0"
        return self.source[self.index + 1]

    def _advance(self) -> str:
        ch = self.source[self.index]
        self.index += 1
        self.column += 1
        return ch

    def _advance_newline(self) -> None:
        self.index += 1
        self.line += 1
        self.column = 1

    def _is_at_end(self) -> bool:
        return self.index >= len(self.source)
