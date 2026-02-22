from dataclasses import dataclass
from typing import List
from lexer import Token, TokenType 
class ASTNode:
    pass

@dataclass
class ProgramNode(ASTNode):
    statements: List[ASTNode]

@dataclass
class PinDeclNode(ASTNode):
    name: str
    pin_num: int
    mode: str

@dataclass
class LoopNode(ASTNode):
    body: List[ASTNode]

@dataclass
class MethodCallNode(ASTNode):
    object_name: str
    method_name: str
    
@dataclass
class SleepNode(ASTNode):
    duration_ms: int

class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    def current(self) -> Token:
        return self.tokens[self.pos]

    def consume(self, expected_type: TokenType, expected_value: str = None) -> Token:
        tok = self.current()
        if tok.type == expected_type and (expected_value is None or tok.value == expected_value):
            self.pos += 1
            return tok
            
        expected = expected_value if expected_value else expected_type.name
        raise SyntaxError(f"Syntax Error: Expected '{expected}' at line {tok.line}, got '{tok.value}'")

    def parse_program(self) -> ProgramNode:
        statements = []
        while self.current().type != TokenType.EOF:
            if self.current().value == "pin":
                statements.append(self.parse_pin_declaration())
            elif self.current().value == "loop":
                statements.append(self.parse_loop_statement())
            else:
                statements.append(self.parse_expression_statement())
        return ProgramNode(statements)

    def parse_pin_declaration(self) -> PinDeclNode:
        self.consume(TokenType.KEYWORD, "pin")
        name_tok = self.consume(TokenType.IDENTIFIER)
        self.consume(TokenType.SYMBOL, "=")
        self.consume(TokenType.KEYWORD, "Pin")
        self.consume(TokenType.SYMBOL, "(")
        pin_tok = self.consume(TokenType.NUMBER)
        self.consume(TokenType.SYMBOL, ",")
        
        mode_tok = self.current()
        if mode_tok.value not in ("in", "out"):
            raise SyntaxError(f"Syntax Error: Expected 'in' or 'out' at line {mode_tok.line}")
        self.consume(TokenType.KEYWORD)
        self.consume(TokenType.SYMBOL, ")")
        
        return PinDeclNode(name_tok.value, int(pin_tok.value), mode_tok.value)

    def parse_loop_statement(self) -> LoopNode:
        self.consume(TokenType.KEYWORD, "loop")
        self.consume(TokenType.SYMBOL, "{")
        
        body = []
        while self.current().value != "}":
            if self.current().type == TokenType.EOF:
                raise SyntaxError("Syntax Error: Unexpected EOF, missing closing '}' for loop block")
            body.append(self.parse_expression_statement())
            
        self.consume(TokenType.SYMBOL, "}")
        return LoopNode(body)

    def parse_expression_statement(self) -> ASTNode:
        tok = self.current()
        
        if tok.value == "sleep":
            self.consume(TokenType.KEYWORD, "sleep")
            self.consume(TokenType.SYMBOL, "(")
            time_tok = self.consume(TokenType.TIME_LITERAL)
            self.consume(TokenType.SYMBOL, ")")
            
            if time_tok.value.endswith("ms"):
                ms_val = int(time_tok.value[:-2])
            elif time_tok.value.endswith("s"):
                ms_val = int(time_tok.value[:-1]) * 1000
            return SleepNode(ms_val)
            
        elif tok.type == TokenType.IDENTIFIER:
            obj_name = self.consume(TokenType.IDENTIFIER).value
            self.consume(TokenType.SYMBOL, ".")
            method_name = self.consume(TokenType.IDENTIFIER).value
            self.consume(TokenType.SYMBOL, "(")
            self.consume(TokenType.SYMBOL, ")")
            return MethodCallNode(obj_name, method_name)
            
        raise SyntaxError(f"Syntax Error: Unexpected token '{tok.value}' at line {tok.line}")