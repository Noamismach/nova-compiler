import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import List

class TokenType(Enum):
    KEYWORD = auto()
    IDENTIFIER = auto()
    NUMBER = auto()
    TIME_LITERAL = auto()
    SYMBOL = auto()
    EOF = auto()

@dataclass
class Token:
    type: TokenType
    value: str
    line: int
    column: int

class Lexer:
    KEYWORDS = {"pin", "Pin", "out", "in", "loop", "sleep"}
    
    def __init__(self, source_code: str):
        self.source = source_code
        self.pos = 0
        self.line = 1
        self.column = 1
    def advance(self) -> str:
        if self.pos >= len(self.source):
            return '\0'
        char = self.source[self.pos]
        self.pos += 1

        if char == '\n':
            self.line += 1
            self.column = 1
        else:
            self.column += 1
    
        return char

    def peek(self, offset: int = 0) -> str:
        if self.pos + offset >= len(self.source):
            return '\0'
        return self.source[self.pos + offset]
    
    def next_token(self) -> Token:
        while self.peek().isspace():
            self.advance()
            
        char = self.peek()
        start_col = self.column

        if char == '\0':
            return Token(TokenType.EOF, "", self.line, self.column)
        
        if char.isalpha() or char == '_':
            value = ""
            while self.peek().isalnum() or self.peek() == '_':
                value += self.advance()
            
            tok_type = TokenType.KEYWORD if value in self.KEYWORDS else TokenType.IDENTIFIER
            return Token(tok_type, value, self.line, start_col)
            
        if char.isdigit():
            value = ""
            while self.peek().isdigit():
                value += self.advance()
            
            if self.peek() == 'm' and self.peek(1) == 's':
                value += self.advance() + self.advance()
                return Token(TokenType.TIME_LITERAL, value, self.line, start_col)
            elif self.peek() == 's':
                value += self.advance()
                return Token(TokenType.TIME_LITERAL, value, self.line, start_col)
                
            return Token(TokenType.NUMBER, value, self.line, start_col)

        if char in "={}(),.":
            return Token(TokenType.SYMBOL, self.advance(), self.line, start_col)
            
        raise SyntaxError(f"Lexical Error: Unexpected character '{char}' at line {self.line}, col {self.column}")
    def tokenize(self) -> List[Token]:
        tokens = []
        while True:
            tok = self.next_token()
            tokens.append(tok)
            if tok.type == TokenType.EOF:
                break
        return tokens