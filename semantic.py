"""Semantic analysis for the ESP32 DSL with scope/type checks and hardware validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from ast_nodes import (
    AssignmentExpr,
    BinaryExpr,
    BlockStmt,
    CallExpr,
    DelayStmt,
    DigitalWriteStmt,
    Expr,
    ExprStmt,
    ForStmt,
    FunctionDecl,
    GpioModeStmt,
    IdentifierExpr,
    IfStmt,
    ImportDecl,
    LiteralExpr,
    LoopBlockDecl,
    Param,
    Program,
    PwmWriteStmt,
    RgbWriteStmt,
    ReturnStmt,
    UnaryExpr,
    VarDecl,
    WhileStmt,
    WifiConnectStmt,
)


@dataclass(frozen=True)
class HardwareProfile:
    """Board-specific GPIO/ADC capability and reservation model for semantic checks."""

    board: str
    valid_gpio_pins: set[int]
    input_only_pins: set[int]
    strapping_pins: set[int]
    flash_pins: set[int]
    reserved_pins: set[int]
    adc1_pins: set[int]
    adc2_pins: set[int]

    @property
    def adc_pins(self) -> set[int]:
        return self.adc1_pins | self.adc2_pins

    @property
    def pwm_pins(self) -> set[int]:
        return self.valid_gpio_pins - self.input_only_pins - self.flash_pins - self.reserved_pins


DEFAULT_ESP32_PROFILE = HardwareProfile(
    board="esp32",
    valid_gpio_pins={
        0,
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        21,
        22,
        23,
        25,
        26,
        27,
        32,
        33,
        34,
        35,
        36,
        39,
    },
    input_only_pins={34, 35, 36, 39},
    strapping_pins={0, 2, 4, 5, 12, 15},
    flash_pins={6, 7, 8, 9, 10, 11},
    reserved_pins=set(),
    adc1_pins={32, 33, 34, 35, 36, 39},
    adc2_pins={0, 2, 4, 12, 13, 14, 15, 25, 26, 27},
)


ESP32S3_N16R8_PROFILE = HardwareProfile(
    board="esp32s3_n16r8",
    valid_gpio_pins=set(range(0, 49)),
    input_only_pins=set(),
    strapping_pins={0, 3, 45, 46},
    flash_pins=set(),
    reserved_pins={33, 34, 35, 36, 37},
    adc1_pins=set(range(1, 11)),
    adc2_pins=set(range(11, 21)),
)


HARDWARE_PROFILES: Dict[str, HardwareProfile] = {
    "esp32": DEFAULT_ESP32_PROFILE,
    "esp32s3_n16r8": ESP32S3_N16R8_PROFILE,
}


@dataclass(frozen=True)
class SemanticIssue:
    """Single semantic diagnostic emitted during analysis."""

    severity: str
    message: str
    file_path: str
    line: int
    column: int


@dataclass
class Symbol:
    """Symbol table entry for variables, parameters, and functions."""

    name: str
    kind: str
    type_name: str
    param_types: Optional[List[str]] = None
    return_type: Optional[str] = None
    const_int_value: Optional[int] = None


class Scope:
    """Nested symbol scope."""

    def __init__(self, parent: Optional["Scope"] = None) -> None:
        self.parent = parent
        self.symbols: Dict[str, Symbol] = {}

    def define(self, symbol: Symbol) -> bool:
        if symbol.name in self.symbols:
            return False
        self.symbols[symbol.name] = symbol
        return True

    def resolve(self, name: str) -> Optional[Symbol]:
        if name in self.symbols:
            return self.symbols[name]
        if self.parent is not None:
            return self.parent.resolve(name)
        return None


class SemanticAnalyzer:
    """Performs name resolution, type checks, and ESP32 hardware rules."""

    def __init__(self, board: str = "esp32") -> None:
        self.issues: List[SemanticIssue] = []
        self.global_scope = Scope()
        self.current_scope = self.global_scope
        self.current_return_type = "void"
        self.current_file_path = "<input>"
        self.board = board.strip().lower()
        self.profile = HARDWARE_PROFILES.get(self.board, DEFAULT_ESP32_PROFILE)
        self._install_builtins()

    def analyze(self, program: Program) -> List[SemanticIssue]:
        for decl in program.declarations:
            if isinstance(decl, FunctionDecl):
                self._declare_function_signature(decl)

        for decl in program.declarations:
            self._visit_decl_or_stmt(decl)

        return self.issues

    def _install_builtins(self) -> None:
        builtins = [
            Symbol("analogRead", "function", "fn(int)->int", ["int"], "int"),
            Symbol("gpioMode", "function", "fn(int,string)->void", ["int", "string"], "void"),
            Symbol("digitalWrite", "function", "fn(int,int)->void", ["int", "int"], "void"),
            Symbol("pwmWrite", "function", "fn(int,int,int)->void", ["int", "int", "int"], "void"),
            Symbol("rgbWrite", "function", "fn(int,int,int,int)->void", ["int", "int", "int", "int"], "void"),
            Symbol("wifiConnect", "function", "fn(string,string)->bool", ["string", "string"], "bool"),
            Symbol("delay", "function", "fn(int)->void", ["int"], "void"),
        ]
        for sym in builtins:
            self.global_scope.define(sym)

    def _declare_function_signature(self, fn: FunctionDecl) -> None:
        if not self.global_scope.define(
            Symbol(
                name=fn.name,
                kind="function",
                type_name=f"fn({','.join(p.type_name for p in fn.params)})->{fn.return_type}",
                param_types=[p.type_name for p in fn.params],
                return_type=fn.return_type,
            )
        ):
            self._error(fn.span.start_line, fn.span.start_col, f"Function '{fn.name}' is already defined")

    def _visit_decl_or_stmt(self, node) -> None:
        self.current_file_path = node.span.file_path
        if isinstance(node, ImportDecl):
            return
        if isinstance(node, FunctionDecl):
            self._visit_function(node)
            return
        if isinstance(node, LoopBlockDecl):
            self._visit_loop_block(node)
            return
        if isinstance(node, VarDecl):
            self._visit_var_decl(node)
            return
        self._visit_stmt(node)

    def _visit_loop_block(self, loop_decl: LoopBlockDecl) -> None:
        self._visit_block(loop_decl.body)

    def _visit_function(self, fn: FunctionDecl) -> None:
        previous_scope = self.current_scope
        previous_return = self.current_return_type
        self.current_scope = Scope(previous_scope)
        self.current_return_type = fn.return_type

        for param in fn.params:
            if not self.current_scope.define(Symbol(param.name, "param", param.type_name)):
                self._error(param.span.start_line, param.span.start_col, f"Duplicate parameter '{param.name}'")

        self._visit_block(fn.body)

        self.current_scope = previous_scope
        self.current_return_type = previous_return

    def _visit_block(self, block: BlockStmt) -> None:
        prev = self.current_scope
        self.current_scope = Scope(prev)
        for stmt in block.statements:
            self._visit_decl_or_stmt(stmt)
        self.current_scope = prev

    def _visit_stmt(self, stmt) -> None:
        if isinstance(stmt, BlockStmt):
            self._visit_block(stmt)
        elif isinstance(stmt, IfStmt):
            self._expect_type(stmt.condition, "bool", "If condition must be bool")
            self._visit_block(stmt.then_branch)
            if stmt.else_branch is not None:
                self._visit_block(stmt.else_branch)
        elif isinstance(stmt, WhileStmt):
            self._expect_type(stmt.condition, "bool", "While condition must be bool")
            self._visit_block(stmt.body)
        elif isinstance(stmt, ForStmt):
            if stmt.init is not None:
                self._visit_decl_or_stmt(stmt.init)
            if stmt.condition is not None:
                self._expect_type(stmt.condition, "bool", "For condition must be bool")
            if stmt.update is not None:
                self._infer_expr_type(stmt.update)
            self._visit_block(stmt.body)
        elif isinstance(stmt, ReturnStmt):
            value_type = "void" if stmt.value is None else self._infer_expr_type(stmt.value)
            if not self._is_assignable(self.current_return_type, value_type):
                self._error(
                    stmt.span.start_line,
                    stmt.span.start_col,
                    f"Return type mismatch: expected '{self.current_return_type}', got '{value_type}'",
                )
        elif isinstance(stmt, ExprStmt):
            self._infer_expr_type(stmt.expression)
        elif isinstance(stmt, GpioModeStmt):
            self._validate_gpio_mode(stmt)
        elif isinstance(stmt, DigitalWriteStmt):
            self._validate_pin_expr(stmt.pin, "digitalWrite pin must be int")
            self._validate_output_capable_pin(stmt.pin, "digitalWrite")
            self._expect_numeric(stmt.value, "digitalWrite value must be int/bool")
        elif isinstance(stmt, PwmWriteStmt):
            self._validate_pin_expr(stmt.pin, "pwmWrite pin must be int")
            self._validate_pwm_capable_pin(stmt.pin)
            self._expect_numeric(stmt.duty, "pwmWrite duty must be numeric")
            if stmt.channel is not None:
                self._expect_numeric(stmt.channel, "pwmWrite channel must be numeric")
        elif isinstance(stmt, RgbWriteStmt):
            self._validate_pin_expr(stmt.pin, "rgbWrite pin must be int")
            self._validate_output_capable_pin(stmt.pin, "rgbWrite")
            self._expect_numeric(stmt.red, "rgbWrite red channel must be numeric")
            self._expect_numeric(stmt.green, "rgbWrite green channel must be numeric")
            self._expect_numeric(stmt.blue, "rgbWrite blue channel must be numeric")
        elif isinstance(stmt, WifiConnectStmt):
            self._expect_type(stmt.ssid, "string", "wifiConnect SSID must be string")
            self._expect_type(stmt.password, "string", "wifiConnect password must be string")
        elif isinstance(stmt, DelayStmt):
            self._expect_numeric(stmt.milliseconds, "delay expects an integer millisecond value")

    def _visit_var_decl(self, decl: VarDecl) -> None:
        inferred = "unknown"
        if decl.initializer is not None:
            inferred = self._infer_expr_type(decl.initializer)
        declared_type = decl.type_name or inferred
        if decl.type_name is not None and decl.initializer is not None and decl.type_name != inferred:
            if not self._is_assignable(decl.type_name, inferred):
                self._error(
                    decl.span.start_line,
                    decl.span.start_col,
                    f"Type mismatch for '{decl.name}': declared '{decl.type_name}', got '{inferred}'",
                )

        const_int_value: Optional[int] = None
        if isinstance(decl.initializer, LiteralExpr) and decl.initializer.type_name == "int":
            const_int_value = int(decl.initializer.value)

        if not self.current_scope.define(Symbol(decl.name, "var", declared_type, const_int_value=const_int_value)):
            self._error(decl.span.start_line, decl.span.start_col, f"Variable '{decl.name}' already declared in this scope")

    def _validate_gpio_mode(self, stmt: GpioModeStmt) -> None:
        self._validate_pin_expr(stmt.pin, "gpioMode pin must be int")
        pin_value = self._extract_const_int(stmt.pin)
        if pin_value is None:
            return

        if pin_value in self.profile.input_only_pins and stmt.mode == "out":
            self._error(
                stmt.span.start_line,
                stmt.span.start_col,
                f"GPIO{pin_value} is input-only on board '{self.profile.board}' and cannot be configured as 'out'",
            )

        if pin_value in self.profile.reserved_pins:
            self._error(
                stmt.span.start_line,
                stmt.span.start_col,
                f"GPIO{pin_value} is reserved on board '{self.profile.board}' and cannot be used for gpioMode",
            )

        if pin_value in self.profile.strapping_pins:
            self._warn(
                stmt.span.start_line,
                stmt.span.start_col,
                f"GPIO{pin_value} is a strapping pin; validate boot-state side effects",
            )

    def _validate_pin_expr(self, expr: Expr, message: str) -> None:
        if self._infer_expr_type(expr) != "int":
            self._error(expr.span.start_line, expr.span.start_col, message)
            return

        pin_value = self._extract_const_int(expr)
        if pin_value is None:
            return
        if pin_value not in self.profile.valid_gpio_pins:
            self._error(expr.span.start_line, expr.span.start_col, f"GPIO{pin_value} is not a valid GPIO pin on board '{self.profile.board}'")

        if pin_value in self.profile.reserved_pins:
            self._error(
                expr.span.start_line,
                expr.span.start_col,
                f"GPIO{pin_value} is reserved on board '{self.profile.board}' and cannot be used",
            )

    def _validate_output_capable_pin(self, expr: Expr, api_name: str) -> None:
        pin_value = self._extract_const_int(expr)
        if pin_value is None:
            return

        if pin_value in self.profile.input_only_pins:
            self._error(
                expr.span.start_line,
                expr.span.start_col,
                f"{api_name} cannot use GPIO{pin_value}; it is input-only on board '{self.profile.board}'",
            )

        if pin_value in self.profile.flash_pins:
            self._warn(
                expr.span.start_line,
                expr.span.start_col,
                f"GPIO{pin_value} is connected to SPI flash on most ESP32 modules; avoid using it for {api_name}",
            )

    def _validate_pwm_capable_pin(self, expr: Expr) -> None:
        pin_value = self._extract_const_int(expr)
        if pin_value is None:
            return

        if pin_value not in self.profile.pwm_pins:
            self._error(
                expr.span.start_line,
                expr.span.start_col,
                f"GPIO{pin_value} is not PWM-capable/safe for ledc on board '{self.profile.board}'",
            )

    def _validate_adc_capable_pin(self, expr: Expr) -> None:
        pin_value = self._extract_const_int(expr)
        if pin_value is None:
            return

        if pin_value not in self.profile.adc_pins:
            self._error(
                expr.span.start_line,
                expr.span.start_col,
                f"GPIO{pin_value} does not support ADC on board '{self.profile.board}'",
            )
            return

        if pin_value in self.profile.adc2_pins:
            self._warn(
                expr.span.start_line,
                expr.span.start_col,
                f"GPIO{pin_value} is on ADC2; analogRead may conflict when Wi-Fi is active",
            )

    def _expect_numeric(self, expr: Expr, message: str) -> None:
        t = self._infer_expr_type(expr)
        if t not in {"int", "float", "bool"}:
            self._error(expr.span.start_line, expr.span.start_col, message)

    def _expect_type(self, expr: Expr, expected: str, message: str) -> None:
        actual = self._infer_expr_type(expr)
        if not self._is_assignable(expected, actual):
            self._error(expr.span.start_line, expr.span.start_col, message)

    def _is_assignable(self, expected: str, actual: str) -> bool:
        if expected == actual:
            return True
        if expected == "float" and actual == "int":
            return True
        return False

    def _extract_const_int(self, expr: Expr) -> Optional[int]:
        if isinstance(expr, LiteralExpr) and expr.type_name == "int":
            return int(expr.value)
        if isinstance(expr, IdentifierExpr):
            symbol = self.current_scope.resolve(expr.name)
            if symbol is not None:
                return symbol.const_int_value
        return None

    def _infer_expr_type(self, expr: Expr) -> str:
        if isinstance(expr, LiteralExpr):
            return expr.type_name
        if isinstance(expr, IdentifierExpr):
            symbol = self.current_scope.resolve(expr.name)
            if symbol is None:
                self._error(expr.span.start_line, expr.span.start_col, f"Undefined symbol '{expr.name}'")
                return "unknown"
            return symbol.type_name
        if isinstance(expr, AssignmentExpr):
            target_type = self._infer_expr_type(expr.target)
            value_type = self._infer_expr_type(expr.value)
            if not self._is_assignable(target_type, value_type):
                self._error(expr.span.start_line, expr.span.start_col, "Assignment type mismatch")
            return target_type
        if isinstance(expr, UnaryExpr):
            operand_type = self._infer_expr_type(expr.operand)
            if expr.operator == "!":
                return "bool"
            if expr.operator == "-" and operand_type in {"int", "float"}:
                return operand_type
            return "unknown"
        if isinstance(expr, BinaryExpr):
            left = self._infer_expr_type(expr.left)
            right = self._infer_expr_type(expr.right)
            if expr.operator in {"+", "-", "*", "/", "%"}:
                if left == "float" or right == "float":
                    return "float"
                if left == "int" and right == "int":
                    return "int"
                return "unknown"
            if expr.operator in {"==", "!=", ">", "<", ">=", "<=", "&&", "||"}:
                return "bool"
            return "unknown"
        if isinstance(expr, CallExpr):
            if not isinstance(expr.callee, IdentifierExpr):
                self._error(expr.span.start_line, expr.span.start_col, "Only named functions are callable")
                return "unknown"

            symbol = self.current_scope.resolve(expr.callee.name)
            if symbol is None:
                self._error(expr.span.start_line, expr.span.start_col, f"Undefined function '{expr.callee.name}'")
                return "unknown"
            if symbol.kind != "function":
                self._error(expr.span.start_line, expr.span.start_col, f"Symbol '{expr.callee.name}' is not callable")
                return "unknown"

            expected_types = symbol.param_types or []
            if len(expr.args) != len(expected_types):
                self._error(
                    expr.span.start_line,
                    expr.span.start_col,
                    f"Function '{expr.callee.name}' expects {len(expected_types)} argument(s), got {len(expr.args)}",
                )
                for arg in expr.args:
                    self._infer_expr_type(arg)
                return symbol.return_type or "unknown"

            for index, (arg_expr, expected_type) in enumerate(zip(expr.args, expected_types), start=1):
                actual_type = self._infer_expr_type(arg_expr)
                if not self._is_assignable(expected_type, actual_type):
                    self._error(
                        arg_expr.span.start_line,
                        arg_expr.span.start_col,
                        f"Argument {index} of '{expr.callee.name}' expects '{expected_type}', got '{actual_type}'",
                    )

            if expr.callee.name == "analogRead" and expr.args:
                self._validate_adc_capable_pin(expr.args[0])

            return symbol.return_type or "unknown"
        return "unknown"

    def _error(self, line: int, column: int, message: str) -> None:
        self.issues.append(SemanticIssue("error", message, self.current_file_path, line, column))

    def _warn(self, line: int, column: int, message: str) -> None:
        self.issues.append(SemanticIssue("warning", message, self.current_file_path, line, column))
