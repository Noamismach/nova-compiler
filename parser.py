"""Recursive descent LL(1)-style parser with error recovery for the ESP32 DSL."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from ast_nodes import (
    AssignmentExpr,
    BitwiseExpr,
    BinaryExpr,
    BlockStmt,
    BusDecl,
    CastExpr,
    CallExpr,
    DelayStmt,
    DeviceDecl,
    DigitalWriteStmt,
    Expr,
    ExprStmt,
    ForStmt,
    FunctionDecl,
    GpioModeStmt,
    IdentifierExpr,
    IfExpr,
    IfStmt,
    ImportDecl,
    LiteralExpr,
    LoopBlockDecl,
    MemberAccessExpr,
    MatchArm,
    MatchStmt,
    Param,
    PostfixExpr,
    Program,
    PwmWriteStmt,
    RgbWriteStmt,
    StructDecl,
    StructField,
    StructInitExpr,
    SpawnStmt,
    TaskDecl,
    TaskDecorator,
    ReturnStmt,
    SourceSpan,
    UnaryExpr,
    UnsafeBlockStmt,
    VarDecl,
    WhileStmt,
    WifiConnectStmt,
)
from lexer import Token, TokenType


@dataclass(frozen=True)
class ParseError:
    """Single parser diagnostic with source coordinates."""

    message: str
    line: int
    column: int


class Parser:
    """Hand-written parser that collects syntax errors and recovers."""

    def __init__(self, tokens: List[Token], file_path: str = "<input>") -> None:
        self.tokens = tokens
        self.file_path = file_path
        self.current = 0
        self.errors: List[ParseError] = []

    def parse(self) -> tuple[Program, List[ParseError]]:
        """Parse a full translation unit and return AST plus collected errors."""

        declarations = []
        while not self._is_at_end():
            decl = self._declaration()
            if decl is not None:
                declarations.append(decl)

        end = self._peek()
        program_span = SourceSpan(self.file_path, 1, 1, end.line, end.column)
        return Program(span=program_span, declarations=declarations), self.errors

    def _declaration(self):
        """Parse one declaration or statement entrypoint with synchronization on failure."""

        try:
            if self._match(TokenType.IMPORT):
                return self._import_decl()
            if self._check(TokenType.AT):
                decorators = self._task_decorators()
                self._consume(TokenType.TASK, "Expected 'task' after decorators")
                return self._task_decl(decorators)
            if self._match(TokenType.FN):
                return self._function_decl()
            if self._match(TokenType.TASK):
                return self._task_decl([])
            if self._match(TokenType.STRUCT):
                return self._struct_decl()
            if self._match(TokenType.BUS):
                return self._bus_decl()
            if self._match(TokenType.LOOP):
                return self._loop_decl()
            if self._check(TokenType.CONST):
                self._advance()
                is_volatile = self._match(TokenType.VOLATILE)
                self._match(TokenType.LET)
                return self._var_decl(require_semicolon=True, is_const=True, is_volatile=is_volatile)
            if self._check(TokenType.VOLATILE):
                self._advance()
                is_const = self._match(TokenType.CONST)
                self._match(TokenType.LET)
                return self._var_decl(require_semicolon=True, is_const=is_const, is_volatile=True)
            if self._match(TokenType.LET):
                return self._var_decl(require_semicolon=True, is_const=False, is_volatile=False)
            return self._statement()
        except _SyncError:
            self._synchronize()
            return None

    def _import_decl(self) -> ImportDecl:
        """Parse `import "path";` declarations."""

        token = self._consume(TokenType.STRING, "Expected module path string after import")
        semicolon = self._consume(TokenType.SEMICOLON, "Expected ';' after import declaration")
        span = self._span_from_tokens(token, semicolon)
        return ImportDecl(span=span, module_path=token.lexeme)

    def _function_decl(self) -> FunctionDecl:
        name_tok = self._consume(TokenType.IDENT, "Expected function name")
        self._consume(TokenType.LPAREN, "Expected '(' after function name")
        params: List[Param] = []

        if not self._check(TokenType.RPAREN):
            while True:
                p_name = self._consume(TokenType.IDENT, "Expected parameter name")
                self._consume(TokenType.COLON, "Expected ':' after parameter name")
                p_type = self._consume(TokenType.IDENT, "Expected parameter type")
                params.append(
                    Param(
                        span=self._span_from_tokens(p_name, p_type),
                        name=p_name.lexeme,
                        type_name=p_type.lexeme,
                    )
                )
                if not self._match(TokenType.COMMA):
                    break

        self._consume(TokenType.RPAREN, "Expected ')' after parameter list")
        self._consume(TokenType.ARROW, "Expected '->' before return type")
        ret_type = self._consume(TokenType.IDENT, "Expected return type")
        body = self._block()
        span = self._span_from_tokens(name_tok, body.span)
        return FunctionDecl(
            span=span,
            name=name_tok.lexeme,
            params=params,
            return_type=ret_type.lexeme,
            body=body,
        )

    def _task_decorators(self) -> List[TaskDecorator]:
        """Parse leading `@decorator(value)` nodes before a task declaration."""

        decorators: List[TaskDecorator] = []
        while self._match(TokenType.AT):
            at_tok = self._previous()
            name_tok = self._consume(TokenType.IDENT, "Expected decorator name after '@'")
            self._consume(TokenType.LPAREN, "Expected '(' after decorator name")
            value_expr = self._expression()
            right = self._consume(TokenType.RPAREN, "Expected ')' after decorator value")
            decorators.append(
                TaskDecorator(
                    span=SourceSpan(self.file_path, at_tok.line, at_tok.column, right.line, right.column),
                    name=name_tok.lexeme,
                    value=value_expr,
                )
            )
        return decorators

    def _task_decl(self, decorators: List[TaskDecorator]) -> TaskDecl:
        """Parse a task declaration and attach already parsed decorators."""

        name_tok = self._consume(TokenType.IDENT, "Expected task name")
        self._consume(TokenType.LPAREN, "Expected '(' after task name")
        self._consume(TokenType.RPAREN, "Expected ')' after task parameters")
        body = self._block()
        return TaskDecl(span=self._span_from_tokens(name_tok, body.span), name=name_tok.lexeme, decorators=decorators, body=body)

    def _bus_decl(self) -> BusDecl:
        """Parse a declarative bus block including nested device declarations."""

        start = self._previous()
        bus_type_tok = self._consume_any([TokenType.I2C, TokenType.SPI, TokenType.IDENT], "Expected bus type (I2C/SPI)")
        bus_name = self._consume(TokenType.IDENT, "Expected bus name")
        self._consume(TokenType.LBRACE, "Expected '{' to start bus declaration")

        sda_expr: Optional[Expr] = None
        scl_expr: Optional[Expr] = None
        freq_expr: Optional[Expr] = None
        devices: List[DeviceDecl] = []

        while not self._check(TokenType.RBRACE) and not self._is_at_end():
            if self._match(TokenType.DEVICE):
                devices.append(self._device_decl())
                continue

            key_tok = self._consume(TokenType.IDENT, "Expected bus property name or device declaration")
            self._consume(TokenType.COLON, "Expected ':' after bus property name")
            if key_tok.lexeme == "sda":
                sda_expr = self._expression()
            elif key_tok.lexeme == "scl":
                scl_expr = self._expression()
            elif key_tok.lexeme == "freq":
                freq_expr = self._bus_freq_expr()
            else:
                self._raise_error(key_tok, f"Unknown bus property '{key_tok.lexeme}'")
            self._consume(TokenType.SEMICOLON, "Expected ';' after bus property")

        right = self._consume(TokenType.RBRACE, "Expected '}' after bus declaration")
        if sda_expr is None or scl_expr is None or freq_expr is None:
            self._raise_error(right, "Bus declaration requires sda, scl, and freq properties")

        return BusDecl(
            span=SourceSpan(self.file_path, start.line, start.column, right.line, right.column),
            bus_type=bus_type_tok.lexeme,
            name=bus_name.lexeme,
            sda=sda_expr,
            scl=scl_expr,
            freq_hz=freq_expr,
            devices=devices,
        )

    def _device_decl(self) -> DeviceDecl:
        """Parse one `device` entry nested inside a `bus` declaration."""

        start = self._previous()
        device_name = self._consume(TokenType.IDENT, "Expected device name")
        self._consume(TokenType.LBRACE, "Expected '{' to start device declaration")
        prop = self._consume(TokenType.IDENT, "Expected device property name")
        if prop.lexeme != "address":
            self._raise_error(prop, "Only 'address' is supported in device declaration")
        self._consume(TokenType.COLON, "Expected ':' after device property")
        address_expr = self._expression()
        self._consume(TokenType.SEMICOLON, "Expected ';' after device address")
        right = self._consume(TokenType.RBRACE, "Expected '}' after device declaration")
        return DeviceDecl(
            span=SourceSpan(self.file_path, start.line, start.column, right.line, right.column),
            name=device_name.lexeme,
            address=address_expr,
        )

    def _bus_freq_expr(self) -> Expr:
        if self._match(TokenType.INT):
            number_tok = self._previous()
            freq_value = int(number_tok.lexeme, 0)
            end_tok = number_tok
            if self._check(TokenType.IDENT):
                unit_tok = self._peek()
                unit = unit_tok.lexeme.lower()
                if unit in {"k", "khz"}:
                    self._advance()
                    freq_value *= 1000
                    end_tok = unit_tok
                elif unit in {"m", "mhz"}:
                    self._advance()
                    freq_value *= 1000000
                    end_tok = unit_tok
            span = SourceSpan(self.file_path, number_tok.line, number_tok.column, end_tok.line, end_tok.column)
            return LiteralExpr(span=span, value=freq_value, type_name="int")
        return self._expression()

    def _struct_decl(self) -> StructDecl:
        """Parse a struct declaration with typed named fields."""

        name_tok = self._consume(TokenType.IDENT, "Expected struct name")
        self._consume(TokenType.LBRACE, "Expected '{' after struct name")
        fields: List[StructField] = []
        while not self._check(TokenType.RBRACE) and not self._is_at_end():
            self._match(TokenType.LET)
            field_name = self._consume(TokenType.IDENT, "Expected struct field name")
            self._consume(TokenType.COLON, "Expected ':' after struct field name")
            field_type = self._consume(TokenType.IDENT, "Expected struct field type")
            field_end = self._consume(TokenType.SEMICOLON, "Expected ';' after struct field")
            fields.append(
                StructField(
                    span=self._span_from_tokens(field_name, field_end),
                    name=field_name.lexeme,
                    type_name=field_type.lexeme,
                )
            )
        right = self._consume(TokenType.RBRACE, "Expected '}' after struct declaration")
        return StructDecl(span=self._span_from_tokens(name_tok, right), name=name_tok.lexeme, fields=fields)

    def _loop_decl(self) -> LoopBlockDecl:
        loop_tok = self._previous()
        body = self._block()
        span = SourceSpan(
            self.file_path,
            loop_tok.line,
            loop_tok.column,
            body.span.end_line,
            body.span.end_col,
        )
        return LoopBlockDecl(span=span, body=body)

    def _var_decl(self, require_semicolon: bool, is_const: bool, is_volatile: bool) -> VarDecl:
        name_tok = self._consume(TokenType.IDENT, "Expected variable name")
        var_type: Optional[str] = None
        if self._match(TokenType.COLON):
            var_type = self._consume(TokenType.IDENT, "Expected type name after ':'").lexeme

        initializer = None
        end_token = name_tok
        if self._match(TokenType.ASSIGN):
            initializer = self._expression()
            end_token = self._previous()

        if require_semicolon:
            end_token = self._consume(TokenType.SEMICOLON, "Expected ';' after variable declaration")

        return VarDecl(
            span=self._span_from_tokens(name_tok, end_token),
            name=name_tok.lexeme,
            type_name=var_type,
            initializer=initializer,
            is_mutable=not is_const,
            is_const=is_const,
            is_volatile=is_volatile,
        )

    def _statement(self):
        """Parse a non-declaration statement."""

        if self._match(TokenType.IF):
            return self._if_stmt()
        if self._match(TokenType.WHILE):
            return self._while_stmt()
        if self._match(TokenType.FOR):
            return self._for_stmt()
        if self._match(TokenType.MATCH):
            return self._match_stmt()
        if self._match(TokenType.SPAWN):
            return self._spawn_stmt()
        if self._match(TokenType.RETURN):
            return self._return_stmt()
        if self._check(TokenType.LBRACE):
            return self._block()
        if self._match(TokenType.GPIOMODE):
            return self._gpio_mode_stmt()
        if self._match(TokenType.DIGITALWRITE):
            return self._digital_write_stmt()
        if self._match(TokenType.PWMWRITE):
            return self._pwm_write_stmt()
        if self._match(TokenType.RGBWRITE):
            return self._rgb_write_stmt()
        if self._match(TokenType.WIFICONNECT):
            return self._wifi_connect_stmt()
        if self._match(TokenType.DELAY):
            return self._delay_stmt()
        if self._match(TokenType.UNSAFE):
            return self._unsafe_stmt()

        expr = self._expression()
        end = self._consume(TokenType.SEMICOLON, "Expected ';' after expression")
        return ExprStmt(span=self._span_from_expr_token(expr, end), expression=expr)

    def _if_stmt(self) -> IfStmt:
        self._consume(TokenType.LPAREN, "Expected '(' after if")
        condition = self._expression()
        self._consume(TokenType.RPAREN, "Expected ')' after condition")
        then_branch = self._block()
        else_branch = self._block() if self._match(TokenType.ELSE) else None
        span = SourceSpan(
            self.file_path,
            condition.span.start_line,
            condition.span.start_col,
            (else_branch or then_branch).span.end_line,
            (else_branch or then_branch).span.end_col,
        )
        return IfStmt(span=span, condition=condition, then_branch=then_branch, else_branch=else_branch)

    def _while_stmt(self) -> WhileStmt:
        self._consume(TokenType.LPAREN, "Expected '(' after while")
        condition = self._expression()
        self._consume(TokenType.RPAREN, "Expected ')' after condition")
        body = self._block()
        return WhileStmt(span=self._span_from_tokens(condition, body.span), condition=condition, body=body)

    def _for_stmt(self) -> ForStmt:
        self._consume(TokenType.LPAREN, "Expected '(' after for")
        init = None
        if self._match(TokenType.CONST):
            is_const = True
            is_volatile = self._match(TokenType.VOLATILE)
            self._match(TokenType.LET)
            init = self._var_decl(require_semicolon=False, is_const=is_const, is_volatile=is_volatile)
        elif self._match(TokenType.VOLATILE):
            is_const = self._match(TokenType.CONST)
            is_volatile = True
            self._match(TokenType.LET)
            init = self._var_decl(require_semicolon=False, is_const=is_const, is_volatile=is_volatile)
        elif self._match(TokenType.LET):
            init = self._var_decl(require_semicolon=False, is_const=False, is_volatile=False)
        elif not self._check(TokenType.SEMICOLON):
            init_expr = self._expression()
            init = ExprStmt(span=init_expr.span, expression=init_expr)

        self._consume(TokenType.SEMICOLON, "Expected ';' after for initializer")

        condition = None if self._check(TokenType.SEMICOLON) else self._expression()
        self._consume(TokenType.SEMICOLON, "Expected ';' after for condition")

        update = None if self._check(TokenType.RPAREN) else self._expression()
        self._consume(TokenType.RPAREN, "Expected ')' after for clauses")
        body = self._block()

        anchor = condition.span if condition is not None else body.span
        return ForStmt(span=self._span_from_tokens(anchor, body.span), init=init, condition=condition, update=update, body=body)

    def _spawn_stmt(self) -> SpawnStmt:
        start = self._previous()
        task_name = self._consume(TokenType.IDENT, "Expected task name after spawn")
        self._consume(TokenType.LPAREN, "Expected '(' after task name")
        self._consume(TokenType.RPAREN, "Expected ')' after task spawn arguments")
        semicolon = self._consume(TokenType.SEMICOLON, "Expected ';' after spawn statement")
        return SpawnStmt(
            span=SourceSpan(self.file_path, start.line, start.column, semicolon.line, semicolon.column),
            task_name=task_name.lexeme,
        )

    def _return_stmt(self) -> ReturnStmt:
        keyword = self._previous()
        value = None if self._check(TokenType.SEMICOLON) else self._expression()
        semicolon = self._consume(TokenType.SEMICOLON, "Expected ';' after return")
        if value is None:
            span = SourceSpan(self.file_path, keyword.line, keyword.column, semicolon.line, semicolon.column)
        else:
            span = self._span_from_tokens(value, semicolon)
        return ReturnStmt(span=span, value=value)

    def _match_stmt(self) -> MatchStmt:
        start = self._previous()
        self._consume(TokenType.LPAREN, "Expected '(' after match")
        match_value = self._expression()
        self._consume(TokenType.RPAREN, "Expected ')' after match value")
        self._consume(TokenType.LBRACE, "Expected '{' to start match arms")

        arms: List[MatchArm] = []
        while not self._check(TokenType.RBRACE) and not self._is_at_end():
            is_wildcard = False
            pattern: Optional[Expr]
            if self._check(TokenType.IDENT) and self._peek().lexeme == "_":
                wildcard_tok = self._advance()
                is_wildcard = True
                pattern = None
                pattern_end: Token | Expr = wildcard_tok
            else:
                pattern = self._expression()
                pattern_end = pattern

            self._consume(TokenType.FAT_ARROW, "Expected '=>' after match arm pattern")
            body = self._block()
            arms.append(
                MatchArm(
                    span=self._span_from_tokens(pattern_end, body.span),
                    pattern=pattern,
                    is_wildcard=is_wildcard,
                    body=body,
                )
            )

        right = self._consume(TokenType.RBRACE, "Expected '}' after match arms")
        return MatchStmt(span=SourceSpan(self.file_path, start.line, start.column, right.line, right.column), value=match_value, arms=arms)

    def _if_expr(self) -> IfExpr:
        start = self._previous()
        self._consume(TokenType.LPAREN, "Expected '(' after if")
        condition = self._expression()
        self._consume(TokenType.RPAREN, "Expected ')' after condition")

        then_block, then_value = self._value_block("if expression")
        self._consume(TokenType.ELSE, "Expected 'else' for if expression")
        else_block, else_value = self._value_block("else expression")
        return IfExpr(
            span=SourceSpan(self.file_path, start.line, start.column, else_block.span.end_line, else_block.span.end_col),
            condition=condition,
            then_block=then_block,
            then_value=then_value,
            else_block=else_block,
            else_value=else_value,
        )

    def _value_block(self, context_name: str) -> tuple[BlockStmt, Expr]:
        """Parse a value-producing block used by `if` expressions."""

        left = self._consume(TokenType.LBRACE, f"Expected '{{' to start {context_name} block")
        statements = []
        tail_expr: Optional[Expr] = None

        while not self._check(TokenType.RBRACE) and not self._is_at_end():
            if self._check(TokenType.IMPORT) or self._check(TokenType.FN) or self._check(TokenType.STRUCT) or self._check(TokenType.LOOP) or self._check(TokenType.BUS) or self._check(TokenType.TASK) or self._check(TokenType.AT):
                self._raise_error(self._peek(), "Top-level declaration is not allowed inside if expression block")

            if self._check(TokenType.LET) or self._check(TokenType.CONST) or self._check(TokenType.VOLATILE):
                decl = self._declaration()
                if decl is not None:
                    statements.append(decl)
                continue

            if self._check(TokenType.WHILE) or self._check(TokenType.FOR) or self._check(TokenType.MATCH) or self._check(TokenType.SPAWN) or self._check(TokenType.RETURN) or self._check(TokenType.LBRACE) or self._check(TokenType.GPIOMODE) or self._check(TokenType.DIGITALWRITE) or self._check(TokenType.PWMWRITE) or self._check(TokenType.RGBWRITE) or self._check(TokenType.WIFICONNECT) or self._check(TokenType.DELAY) or self._check(TokenType.UNSAFE):
                stmt = self._statement()
                if stmt is not None:
                    statements.append(stmt)
                continue

            expr = self._expression()
            if self._match(TokenType.SEMICOLON):
                statements.append(ExprStmt(span=self._span_from_expr_token(expr, self._previous()), expression=expr))
                continue

            tail_expr = expr
            break

        if tail_expr is None:
            self._raise_error(self._peek(), f"Expected value expression before closing {context_name} block")

        right = self._consume(TokenType.RBRACE, f"Expected '}}' to close {context_name} block")
        return BlockStmt(span=self._span_from_tokens(left, right), statements=statements), tail_expr

    def _block(self) -> BlockStmt:
        left = self._consume(TokenType.LBRACE, "Expected '{' to start block")
        statements = []
        while not self._check(TokenType.RBRACE) and not self._is_at_end():
            stmt = self._declaration()
            if stmt is not None:
                statements.append(stmt)
        right = self._consume(TokenType.RBRACE, "Expected '}' to close block")
        return BlockStmt(span=self._span_from_tokens(left, right), statements=statements)

    def _gpio_mode_stmt(self) -> GpioModeStmt:
        start = self._previous()
        self._consume(TokenType.LPAREN, "Expected '(' after gpioMode")
        pin = self._expression()
        self._consume(TokenType.COMMA, "Expected ',' after pin")
        mode_tok = self._consume_any([TokenType.OUT, TokenType.IN], "Expected pin mode 'out' or 'in'")
        self._consume(TokenType.RPAREN, "Expected ')' after gpioMode arguments")
        semicolon = self._consume(TokenType.SEMICOLON, "Expected ';' after gpioMode")
        return GpioModeStmt(
            span=SourceSpan(self.file_path, start.line, start.column, semicolon.line, semicolon.column),
            pin=pin,
            mode=mode_tok.lexeme,
        )

    def _digital_write_stmt(self) -> DigitalWriteStmt:
        start = self._previous()
        self._consume(TokenType.LPAREN, "Expected '(' after digitalWrite")
        pin = self._expression()
        self._consume(TokenType.COMMA, "Expected ',' after pin")
        value = self._expression()
        self._consume(TokenType.RPAREN, "Expected ')' after digitalWrite arguments")
        semicolon = self._consume(TokenType.SEMICOLON, "Expected ';' after digitalWrite")
        return DigitalWriteStmt(
            span=SourceSpan(self.file_path, start.line, start.column, semicolon.line, semicolon.column),
            pin=pin,
            value=value,
        )

    def _pwm_write_stmt(self) -> PwmWriteStmt:
        start = self._previous()
        self._consume(TokenType.LPAREN, "Expected '(' after pwmWrite")
        pin = self._expression()
        self._consume(TokenType.COMMA, "Expected ',' after pin")
        duty = self._expression()
        channel = None
        if self._match(TokenType.COMMA):
            channel = self._expression()
        self._consume(TokenType.RPAREN, "Expected ')' after pwmWrite arguments")
        semicolon = self._consume(TokenType.SEMICOLON, "Expected ';' after pwmWrite")
        return PwmWriteStmt(
            span=SourceSpan(self.file_path, start.line, start.column, semicolon.line, semicolon.column),
            pin=pin,
            duty=duty,
            channel=channel,
        )

    def _rgb_write_stmt(self) -> RgbWriteStmt:
        start = self._previous()
        self._consume(TokenType.LPAREN, "Expected '(' after rgbWrite")
        pin = self._expression()
        self._consume(TokenType.COMMA, "Expected ',' after rgbWrite pin")
        red = self._expression()
        self._consume(TokenType.COMMA, "Expected ',' after rgbWrite red")
        green = self._expression()
        self._consume(TokenType.COMMA, "Expected ',' after rgbWrite green")
        blue = self._expression()
        self._consume(TokenType.RPAREN, "Expected ')' after rgbWrite arguments")
        semicolon = self._consume(TokenType.SEMICOLON, "Expected ';' after rgbWrite")
        return RgbWriteStmt(
            span=SourceSpan(self.file_path, start.line, start.column, semicolon.line, semicolon.column),
            pin=pin,
            red=red,
            green=green,
            blue=blue,
        )

    def _wifi_connect_stmt(self) -> WifiConnectStmt:
        start = self._previous()
        self._consume(TokenType.LPAREN, "Expected '(' after wifiConnect")
        ssid = self._expression()
        self._consume(TokenType.COMMA, "Expected ',' after SSID")
        password = self._expression()
        self._consume(TokenType.RPAREN, "Expected ')' after wifiConnect arguments")
        semicolon = self._consume(TokenType.SEMICOLON, "Expected ';' after wifiConnect")
        return WifiConnectStmt(
            span=SourceSpan(self.file_path, start.line, start.column, semicolon.line, semicolon.column),
            ssid=ssid,
            password=password,
        )

    def _delay_stmt(self) -> DelayStmt:
        start = self._previous()
        self._consume(TokenType.LPAREN, "Expected '(' after delay")
        millis = self._expression()
        self._consume(TokenType.RPAREN, "Expected ')' after delay argument")
        semicolon = self._consume(TokenType.SEMICOLON, "Expected ';' after delay")
        return DelayStmt(
            span=SourceSpan(self.file_path, start.line, start.column, semicolon.line, semicolon.column),
            milliseconds=millis,
        )

    def _unsafe_stmt(self) -> UnsafeBlockStmt:
        start = self._previous()
        payload = self._consume(TokenType.UNSAFE_BLOCK, "Expected '{...}' raw block after unsafe")
        span = SourceSpan(
            self.file_path,
            start.line,
            start.column,
            payload.line,
            payload.column + max(1, len(payload.lexeme)),
        )
        return UnsafeBlockStmt(span=span, raw_cpp=payload.lexeme)

    def _expression(self) -> Expr:
        """Parse the highest-level expression production."""

        return self._assignment()

    def _assignment(self) -> Expr:
        expr = self._or_expr()
        if self._match(
            TokenType.ASSIGN,
            TokenType.PLUS_ASSIGN,
            TokenType.MINUS_ASSIGN,
            TokenType.STAR_ASSIGN,
            TokenType.SLASH_ASSIGN,
        ):
            equals = self._previous()
            value = self._assignment()
            if isinstance(expr, IdentifierExpr):
                return AssignmentExpr(
                    span=self._span_from_tokens(expr, value),
                    target=expr,
                    value=value,
                    operator=equals.lexeme,
                )
            if isinstance(expr, MemberAccessExpr):
                return AssignmentExpr(
                    span=self._span_from_tokens(expr, value),
                    target=expr,
                    value=value,
                    operator=equals.lexeme,
                )
            self._error_at_token(equals, "Invalid assignment target")
        return expr

    def _or_expr(self) -> Expr:
        expr = self._and_expr()
        while self._match(TokenType.OR):
            op = self._previous()
            right = self._and_expr()
            expr = BinaryExpr(span=self._span_from_tokens(expr, right), left=expr, operator=op.lexeme, right=right)
        return expr

    def _and_expr(self) -> Expr:
        expr = self._bit_or_expr()
        while self._match(TokenType.AND):
            op = self._previous()
            right = self._bit_or_expr()
            expr = BinaryExpr(span=self._span_from_tokens(expr, right), left=expr, operator=op.lexeme, right=right)
        return expr

    def _bit_or_expr(self) -> Expr:
        expr = self._bit_xor_expr()
        while self._match(TokenType.BIT_OR):
            op = self._previous()
            right = self._bit_xor_expr()
            expr = BitwiseExpr(span=self._span_from_tokens(expr, right), left=expr, operator=op.lexeme, right=right)
        return expr

    def _bit_xor_expr(self) -> Expr:
        expr = self._bit_and_expr()
        while self._match(TokenType.BIT_XOR):
            op = self._previous()
            right = self._bit_and_expr()
            expr = BitwiseExpr(span=self._span_from_tokens(expr, right), left=expr, operator=op.lexeme, right=right)
        return expr

    def _bit_and_expr(self) -> Expr:
        expr = self._equality()
        while self._match(TokenType.BIT_AND):
            op = self._previous()
            right = self._equality()
            expr = BitwiseExpr(span=self._span_from_tokens(expr, right), left=expr, operator=op.lexeme, right=right)
        return expr

    def _equality(self) -> Expr:
        expr = self._comparison()
        while self._match(TokenType.EQ, TokenType.NEQ):
            op = self._previous()
            right = self._comparison()
            expr = BinaryExpr(span=self._span_from_tokens(expr, right), left=expr, operator=op.lexeme, right=right)
        return expr

    def _comparison(self) -> Expr:
        expr = self._shift()
        while self._match(TokenType.GT, TokenType.GTE, TokenType.LT, TokenType.LTE):
            op = self._previous()
            right = self._shift()
            expr = BinaryExpr(span=self._span_from_tokens(expr, right), left=expr, operator=op.lexeme, right=right)
        return expr

    def _shift(self) -> Expr:
        expr = self._term()
        while self._match(TokenType.SHIFT_LEFT, TokenType.SHIFT_RIGHT):
            op = self._previous()
            right = self._term()
            expr = BitwiseExpr(span=self._span_from_tokens(expr, right), left=expr, operator=op.lexeme, right=right)
        return expr

    def _term(self) -> Expr:
        expr = self._factor()
        while self._match(TokenType.PLUS, TokenType.MINUS):
            op = self._previous()
            right = self._factor()
            expr = BinaryExpr(span=self._span_from_tokens(expr, right), left=expr, operator=op.lexeme, right=right)
        return expr

    def _factor(self) -> Expr:
        expr = self._unary()
        while self._match(TokenType.STAR, TokenType.SLASH, TokenType.MOD):
            op = self._previous()
            right = self._unary()
            expr = BinaryExpr(span=self._span_from_tokens(expr, right), left=expr, operator=op.lexeme, right=right)
        return expr

    def _unary(self) -> Expr:
        if self._match(TokenType.BANG, TokenType.MINUS, TokenType.BIT_NOT):
            op = self._previous()
            operand = self._unary()
            return UnaryExpr(span=self._span_from_tokens(op, operand), operator=op.lexeme, operand=operand)
        return self._postfix()

    def _postfix(self) -> Expr:
        expr = self._call()
        while True:
            if self._match(TokenType.INC, TokenType.DEC):
                op = self._previous()
                expr = PostfixExpr(span=self._span_from_tokens(expr, op), operand=expr, operator=op.lexeme)
                continue
            if self._match(TokenType.AS):
                type_tok = self._consume(TokenType.IDENT, "Expected type name after 'as'")
                expr = CastExpr(span=self._span_from_tokens(expr, type_tok), expression=expr, target_type=type_tok.lexeme)
                continue
            break
        return expr

    def _call(self) -> Expr:
        expr = self._primary()
        while True:
            if self._match(TokenType.LPAREN):
                expr = self._finish_call(expr)
            elif self._match(TokenType.DOT):
                member = self._consume(TokenType.IDENT, "Expected member name after '.'")
                expr = MemberAccessExpr(
                    span=self._span_from_tokens(expr, member),
                    object_expr=expr,
                    member_name=member.lexeme,
                )
            else:
                break
        return expr

    def _finish_call(self, callee: Expr) -> Expr:
        """Parse call arguments, including struct named-initializer syntax."""

        if isinstance(callee, IdentifierExpr) and self._check(TokenType.IDENT) and self._check_next(TokenType.COLON):
            # `Type(field: value, ...)` is interpreted as struct construction, not a function call.
            field_initializers: List[Tuple[str, Expr]] = []
            while True:
                field_name = self._consume(TokenType.IDENT, "Expected struct field name in initializer")
                self._consume(TokenType.COLON, "Expected ':' after struct field name")
                field_value = self._expression()
                field_initializers.append((field_name.lexeme, field_value))
                if not self._match(TokenType.COMMA):
                    break
            right_paren = self._consume(TokenType.RPAREN, "Expected ')' after struct initializer")
            return StructInitExpr(
                span=self._span_from_tokens(callee, right_paren),
                type_name=callee.name,
                field_initializers=field_initializers,
            )

        args: List[Expr] = []
        if not self._check(TokenType.RPAREN):
            while True:
                args.append(self._expression())
                if not self._match(TokenType.COMMA):
                    break
        right_paren = self._consume(TokenType.RPAREN, "Expected ')' after arguments")
        return CallExpr(span=self._span_from_tokens(callee, right_paren), callee=callee, args=args)

    def _primary(self) -> Expr:
        if self._match(TokenType.IF):
            return self._if_expr()
        if self._match(TokenType.FALSE):
            token = self._previous()
            return LiteralExpr(self._token_span(token), False, "bool")
        if self._match(TokenType.TRUE):
            token = self._previous()
            return LiteralExpr(self._token_span(token), True, "bool")
        if self._match(TokenType.INT):
            token = self._previous()
            return LiteralExpr(self._token_span(token), int(token.lexeme, 0), "int")
        if self._match(TokenType.DURATION):
            token = self._previous()
            if token.lexeme.endswith(("ms", "us")):
                unit = token.lexeme[-2:]
                amount = int(token.lexeme[:-2])
            else:
                unit = "s"
                amount = int(token.lexeme[:-1])
            return LiteralExpr(self._token_span(token), {"value": amount, "unit": unit}, "Duration")
        if self._match(TokenType.FLOAT):
            token = self._previous()
            return LiteralExpr(self._token_span(token), float(token.lexeme), "float")
        if self._match(TokenType.STRING):
            token = self._previous()
            return LiteralExpr(self._token_span(token), token.lexeme, "string")
        if self._match(TokenType.IDENT):
            token = self._previous()
            return IdentifierExpr(self._token_span(token), token.lexeme)
        if self._match(TokenType.ANALOGREAD):
            start = self._previous()
            self._consume(TokenType.LPAREN, "Expected '(' after analogRead")
            arg = self._expression()
            right = self._consume(TokenType.RPAREN, "Expected ')' after analogRead argument")
            return CallExpr(
                span=SourceSpan(self.file_path, start.line, start.column, right.line, right.column),
                callee=IdentifierExpr(self._token_span(start), "analogRead"),
                args=[arg],
            )
        if self._match(TokenType.LPAREN):
            expr = self._expression()
            self._consume(TokenType.RPAREN, "Expected ')' after expression")
            return expr

        self._raise_error(self._peek(), "Expected expression")

    def _match(self, *kinds: TokenType) -> bool:
        for kind in kinds:
            if self._check(kind):
                self._advance()
                return True
        return False

    def _check(self, kind: TokenType) -> bool:
        if self._is_at_end():
            return kind == TokenType.EOF
        return self._peek().kind == kind

    def _check_next(self, kind: TokenType) -> bool:
        if self.current + 1 >= len(self.tokens):
            return False
        return self.tokens[self.current + 1].kind == kind

    def _advance(self) -> Token:
        if not self._is_at_end():
            self.current += 1
        return self._previous()

    def _is_at_end(self) -> bool:
        return self._peek().kind == TokenType.EOF

    def _peek(self) -> Token:
        return self.tokens[self.current]

    def _previous(self) -> Token:
        return self.tokens[self.current - 1]

    def _consume(self, kind: TokenType, message: str) -> Token:
        if self._check(kind):
            return self._advance()
        self._raise_error(self._peek(), message)

    def _consume_any(self, kinds: List[TokenType], message: str) -> Token:
        for kind in kinds:
            if self._check(kind):
                return self._advance()
        self._raise_error(self._peek(), message)

    def _raise_error(self, token: Token, message: str):
        self._error_at_token(token, message)
        raise _SyncError()

    def _error_at_token(self, token: Token, message: str) -> None:
        self.errors.append(ParseError(message=message, line=token.line, column=token.column))

    def _synchronize(self) -> None:
        """Recover after a parse error by advancing to likely statement boundaries."""

        self._advance()
        while not self._is_at_end():
            if self._previous().kind == TokenType.SEMICOLON:
                return
            if self._peek().kind in {
                TokenType.FN,
                TokenType.LET,
                TokenType.CONST,
                TokenType.VOLATILE,
                TokenType.STRUCT,
                TokenType.TASK,
                TokenType.BUS,
                TokenType.AT,
                TokenType.IF,
                TokenType.WHILE,
                TokenType.FOR,
                TokenType.MATCH,
                TokenType.SPAWN,
                TokenType.LOOP,
                TokenType.RETURN,
                TokenType.RGBWRITE,
                TokenType.IMPORT,
                TokenType.UNSAFE,
            }:
                return
            self._advance()

    def _token_span(self, token: Token) -> SourceSpan:
        end_col = token.column + max(1, len(token.lexeme)) - 1
        return SourceSpan(self.file_path, token.line, token.column, token.line, end_col)

    def _span_from_tokens(self, start: Token | Expr | SourceSpan, end: Token | Expr | SourceSpan) -> SourceSpan:
        start_span = start if isinstance(start, SourceSpan) else start.span if hasattr(start, "span") else self._token_span(start)
        end_span = end if isinstance(end, SourceSpan) else end.span if hasattr(end, "span") else self._token_span(end)
        return SourceSpan(
            self.file_path,
            start_span.start_line,
            start_span.start_col,
            end_span.end_line,
            end_span.end_col,
        )

    def _span_from_expr_token(self, expr: Expr, token: Token) -> SourceSpan:
        tok_span = self._token_span(token)
        return SourceSpan(
            self.file_path,
            expr.span.start_line,
            expr.span.start_col,
            tok_span.end_line,
            tok_span.end_col,
        )


class _SyncError(Exception):
    """Internal control-flow exception for parser recovery."""
