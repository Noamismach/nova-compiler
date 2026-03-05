"""Semantic analysis for the ESP32 DSL with scope/type checks and hardware validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

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
    MatchStmt,
    Param,
    PostfixExpr,
    Program,
    SpawnStmt,
    StructDecl,
    StructInitExpr,
    TaskDecl,
    PwmWriteStmt,
    RgbWriteStmt,
    ReturnStmt,
    UnaryExpr,
    UnsafeBlockStmt,
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
    is_const: bool = False
    is_volatile: bool = False


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
        self.struct_defs: Dict[str, List[tuple[str, str]]] = {}
        self.task_decls: Dict[str, TaskDecl] = {}
        self.in_unsafe_block = False
        self._install_builtins()

    def analyze(self, program: Program) -> List[SemanticIssue]:
        """Run declaration and body validation passes and collect semantic issues."""

        # Pass ordering matters: type and callable signatures must exist before body checks.
        for decl in program.declarations:
            if isinstance(decl, StructDecl):
                self._declare_struct_blueprint(decl)
            if isinstance(decl, TaskDecl):
                self._declare_task_signature(decl)

        for decl in program.declarations:
            if isinstance(decl, FunctionDecl):
                self._declare_function_signature(decl)

        for decl in program.declarations:
            self._visit_decl_or_stmt(decl)

        return self.issues

    def _install_builtins(self) -> None:
        """Seed the global scope with intrinsic APIs exposed by the runtime backend."""

        builtins = [
            Symbol("analogRead", "function", "fn(int)->int", ["int"], "int"),
            Symbol("gpioMode", "function", "fn(Pin,string)->void", ["Pin", "string"], "void"),
            Symbol("digitalWrite", "function", "fn(Pin,int)->void", ["Pin", "int"], "void"),
            Symbol("pwmWrite", "function", "fn(Pin,int,int)->void", ["Pin", "int", "int"], "void"),
            Symbol("rgbWrite", "function", "fn(Pin,int,int,int)->void", ["Pin", "int", "int", "int"], "void"),
            Symbol("wifiConnect", "function", "fn(string,string)->bool", ["string", "string"], "bool"),
            Symbol("delay", "function", "fn(Duration)->void", ["Duration"], "void"),
        ]
        for sym in builtins:
            self.global_scope.define(sym)

    def _declare_function_signature(self, fn: FunctionDecl) -> None:
        if not self.global_scope.define(
            Symbol(
                name=fn.name,
                kind="function",
                type_name=f"fn({','.join(p.type_name for p in fn.params)})->{fn.return_type}",
                param_types=[self._normalize_type(p.type_name) for p in fn.params],
                return_type=self._normalize_type(fn.return_type),
            )
        ):
            self._error(fn.span.start_line, fn.span.start_col, f"Function '{fn.name}' is already defined")

    def _declare_struct_blueprint(self, struct_decl: StructDecl) -> None:
        if struct_decl.name in self.struct_defs:
            self._error(struct_decl.span.start_line, struct_decl.span.start_col, f"Struct '{struct_decl.name}' is already defined")
            return

        field_entries: List[tuple[str, str]] = []
        seen_field_names: set[str] = set()
        for field in struct_decl.fields:
            if field.name in seen_field_names:
                self._error(field.span.start_line, field.span.start_col, f"Duplicate field '{field.name}' in struct '{struct_decl.name}'")
                continue
            seen_field_names.add(field.name)
            field_entries.append((field.name, self._normalize_type(field.type_name)))

        self.struct_defs[struct_decl.name] = field_entries
        if not self.global_scope.define(Symbol(struct_decl.name, "struct", struct_decl.name)):
            self._error(struct_decl.span.start_line, struct_decl.span.start_col, f"Symbol '{struct_decl.name}' conflicts with an existing declaration")

    def _declare_task_signature(self, task_decl: TaskDecl) -> None:
        if task_decl.name in self.task_decls:
            self._error(task_decl.span.start_line, task_decl.span.start_col, f"Task '{task_decl.name}' is already defined")
            return
        self.task_decls[task_decl.name] = task_decl
        if not self.global_scope.define(Symbol(task_decl.name, "task", "task")):
            self._error(task_decl.span.start_line, task_decl.span.start_col, f"Task '{task_decl.name}' conflicts with an existing symbol")

    def _visit_decl_or_stmt(self, node) -> None:
        self.current_file_path = node.span.file_path
        if isinstance(node, ImportDecl):
            return
        if isinstance(node, FunctionDecl):
            self._visit_function(node)
            return
        if isinstance(node, StructDecl):
            return
        if isinstance(node, TaskDecl):
            self._visit_task_decl(node)
            return
        if isinstance(node, BusDecl):
            self._visit_bus_decl(node)
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
        self.current_return_type = self._normalize_type(fn.return_type)

        for param in fn.params:
            if not self.current_scope.define(Symbol(param.name, "param", self._normalize_type(param.type_name))):
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
        """Validate executable statements and dispatch statement-specific checks."""

        if isinstance(stmt, BlockStmt):
            self._visit_block(stmt)
        elif isinstance(stmt, IfStmt):
            self._expect_type(stmt.condition, "bool", "If condition must be bool")
            self._visit_block(stmt.then_branch)
            if stmt.else_branch is not None:
                self._visit_block(stmt.else_branch)
        elif isinstance(stmt, MatchStmt):
            self._validate_match_stmt(stmt)
        elif isinstance(stmt, SpawnStmt):
            self._visit_spawn_stmt(stmt)
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
            actual = self._infer_expr_type(stmt.milliseconds)
            if not self._is_assignable("Duration", actual):
                self._error(
                    stmt.milliseconds.span.start_line,
                    stmt.milliseconds.span.start_col,
                    "delay expects a Duration or int value",
                )
        elif isinstance(stmt, UnsafeBlockStmt):
            previous = self.in_unsafe_block
            self.in_unsafe_block = True
            self.in_unsafe_block = previous

    def _visit_task_decl(self, task_decl: TaskDecl) -> None:
        core_values: List[int] = []
        for decorator in task_decl.decorators:
            name = decorator.name
            if name == "core":
                value = self._extract_const_int(decorator.value)
                if value is None:
                    self._error(decorator.span.start_line, decorator.span.start_col, "@core decorator requires an integer literal")
                else:
                    core_values.append(value)
                    if value not in {0, 1}:
                        self._error(decorator.span.start_line, decorator.span.start_col, "@core must be 0 or 1 on ESP32-S3")
            elif name == "rate":
                rate_type = self._infer_expr_type(decorator.value)
                if rate_type not in {"Duration", "int"}:
                    self._error(decorator.span.start_line, decorator.span.start_col, "@rate decorator expects a Duration/int value")
            else:
                self._error(decorator.span.start_line, decorator.span.start_col, f"Unknown task decorator '@{name}'")

        if len(core_values) > 1:
            self._error(task_decl.span.start_line, task_decl.span.start_col, "Task may only define @core once")

        if task_decl.body is not None:
            self._visit_block(task_decl.body)

    def _visit_spawn_stmt(self, spawn_stmt: SpawnStmt) -> None:
        task_symbol = self.global_scope.resolve(spawn_stmt.task_name)
        if task_symbol is None or task_symbol.kind != "task":
            self._error(spawn_stmt.span.start_line, spawn_stmt.span.start_col, f"Spawn target '{spawn_stmt.task_name}' is not a declared task")

    def _visit_bus_decl(self, bus_decl: BusDecl) -> None:
        bus_type = bus_decl.bus_type.upper()
        if bus_type not in {"I2C", "SPI"}:
            self._error(bus_decl.span.start_line, bus_decl.span.start_col, f"Unsupported bus type '{bus_decl.bus_type}'")

        sda_pin = self._extract_const_int(bus_decl.sda)
        scl_pin = self._extract_const_int(bus_decl.scl)
        if sda_pin is None or scl_pin is None:
            self._error(bus_decl.span.start_line, bus_decl.span.start_col, "Bus sda/scl must be compile-time integer pins")
        else:
            for label, pin in (("sda", sda_pin), ("scl", scl_pin)):
                if pin in self.profile.reserved_pins:
                    self._error(
                        bus_decl.span.start_line,
                        bus_decl.span.start_col,
                        f"Bus {label} pin GPIO{pin} conflicts with reserved pins on board '{self.profile.board}'",
                    )

        freq_type = self._infer_expr_type(bus_decl.freq_hz)
        if freq_type not in {"int", "float"}:
            self._error(bus_decl.span.start_line, bus_decl.span.start_col, "Bus freq must be numeric")

        for device in bus_decl.devices:
            self._visit_device_decl(device)

    def _visit_device_decl(self, device_decl: DeviceDecl) -> None:
        address_type = self._infer_expr_type(device_decl.address)
        if address_type != "int":
            self._error(device_decl.span.start_line, device_decl.span.start_col, f"Device '{device_decl.name}' address must be int")

    def _validate_match_stmt(self, stmt: MatchStmt) -> None:
        match_type = self._infer_expr_type(stmt.value)
        has_wildcard = False

        for arm in stmt.arms:
            if arm.is_wildcard:
                has_wildcard = True
            else:
                if arm.pattern is None:
                    self._error(arm.span.start_line, arm.span.start_col, "Non-wildcard match arm must define a pattern")
                else:
                    pattern_type = self._infer_expr_type(arm.pattern)
                    if pattern_type != match_type:
                        self._error(
                            arm.span.start_line,
                            arm.span.start_col,
                            f"Match arm pattern type '{pattern_type}' is not compatible with '{match_type}'",
                        )
            self._visit_block(arm.body)

        if not has_wildcard:
            self._error(stmt.span.start_line, stmt.span.start_col, "Match statement must include wildcard arm '_' for exhaustiveness")

    def _visit_var_decl(self, decl: VarDecl) -> None:
        inferred = "unknown"
        if decl.initializer is not None:
            inferred = self._infer_expr_type(decl.initializer)
        declared_type = self._normalize_type(decl.type_name or inferred)
        if declared_type != "unknown" and not self._is_known_type(declared_type):
            self._error(decl.span.start_line, decl.span.start_col, f"Unknown type '{decl.type_name or declared_type}'")
        if decl.type_name is not None and decl.initializer is not None and self._normalize_type(decl.type_name) != inferred:
            if not self._is_assignable(self._normalize_type(decl.type_name), inferred):
                self._error(
                    decl.span.start_line,
                    decl.span.start_col,
                    f"Type mismatch for '{decl.name}': declared '{decl.type_name}', got '{inferred}'",
                )

        const_int_value: Optional[int] = None
        if isinstance(decl.initializer, LiteralExpr) and decl.initializer.type_name == "int":
            const_int_value = int(decl.initializer.value)

        if not self.current_scope.define(
            Symbol(
                decl.name,
                "var",
                declared_type,
                const_int_value=const_int_value,
                is_const=decl.is_const,
                is_volatile=decl.is_volatile,
            )
        ):
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
        if self._infer_expr_type(expr) not in {"int", "Pin"}:
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
        expected = self._normalize_type(expected)
        actual = self._normalize_type(actual)
        if expected == actual:
            return True
        if expected == "float" and actual == "int":
            return True
        if expected == "Pin" and actual == "int":
            return True
        if expected == "Duration" and actual == "int":
            return True
        return False

    def _normalize_type(self, type_name: str) -> str:
        cleaned = type_name.strip()
        lowered = cleaned.lower()
        primitive_map = {
            "int": "int",
            "float": "float",
            "bool": "bool",
            "string": "string",
            "void": "void",
            "pin": "Pin",
            "duration": "Duration",
            "unknown": "unknown",
        }
        return primitive_map.get(lowered, cleaned)

    def _is_known_type(self, type_name: str) -> bool:
        return type_name in {"int", "float", "bool", "string", "void", "Pin", "Duration", "unknown"} or type_name in self.struct_defs

    def _extract_const_int(self, expr: Expr) -> Optional[int]:
        if isinstance(expr, LiteralExpr) and expr.type_name == "int":
            return int(expr.value)
        if isinstance(expr, IdentifierExpr):
            symbol = self.current_scope.resolve(expr.name)
            if symbol is not None:
                return symbol.const_int_value
        return None

    def _infer_expr_type(self, expr: Expr) -> str:
        """Infer expression type while emitting diagnostics for invalid operations."""

        if isinstance(expr, LiteralExpr):
            return self._normalize_type(expr.type_name)
        if isinstance(expr, IdentifierExpr):
            symbol = self.current_scope.resolve(expr.name)
            if symbol is None:
                self._error(expr.span.start_line, expr.span.start_col, f"Undefined symbol '{expr.name}'")
                return "unknown"
            return symbol.type_name
        if isinstance(expr, AssignmentExpr):
            self._validate_assignment_target_mutability(expr.target)

            target_type = self._infer_expr_type(expr.target)
            value_type = self._infer_expr_type(expr.value)
            if expr.operator == "=":
                if not self._is_assignable(target_type, value_type):
                    self._error(expr.span.start_line, expr.span.start_col, "Assignment type mismatch")
            else:
                if target_type == "Pin":
                    self._error(expr.span.start_line, expr.span.start_col, f"Operator '{expr.operator}' is not supported for {target_type}")
                if value_type == "Pin":
                    self._error(expr.span.start_line, expr.span.start_col, f"Operator '{expr.operator}' is not supported with {value_type}")
                if target_type == "Duration" or value_type == "Duration":
                    if expr.operator not in {"+=", "-="} or target_type != "Duration" or value_type != "Duration":
                        self._error(expr.span.start_line, expr.span.start_col, "Only '+=' and '-=' are supported for Duration operands")
                elif target_type not in {"int", "float"} or value_type not in {"int", "float", "bool"}:
                    self._error(expr.span.start_line, expr.span.start_col, "Compound assignment requires numeric operands")
            return target_type
        if isinstance(expr, CastExpr):
            src_type = self._infer_expr_type(expr.expression)
            dst_type = self._normalize_type(expr.target_type)
            primitive_types = {"int", "float", "bool", "string"}
            if src_type not in primitive_types or dst_type not in primitive_types:
                self._error(expr.span.start_line, expr.span.start_col, f"Explicit cast from '{src_type}' to '{dst_type}' is not allowed")
                return "unknown"
            return dst_type
        if isinstance(expr, MemberAccessExpr):
            object_type = self._infer_expr_type(expr.object_expr)
            if object_type not in self.struct_defs:
                self._error(expr.span.start_line, expr.span.start_col, f"Type '{object_type}' has no member '{expr.member_name}'")
                return "unknown"

            field_map = {field_name: field_type for field_name, field_type in self.struct_defs[object_type]}
            field_type = field_map.get(expr.member_name)
            if field_type is None:
                self._error(expr.span.start_line, expr.span.start_col, f"Struct '{object_type}' has no field '{expr.member_name}'")
                return "unknown"
            return field_type
        if isinstance(expr, IfExpr):
            self._expect_type(expr.condition, "bool", "If expression condition must be bool")
            self._visit_block(expr.then_block)
            self._visit_block(expr.else_block)
            then_type = self._infer_expr_type(expr.then_value)
            else_type = self._infer_expr_type(expr.else_value)
            if then_type != else_type:
                self._error(
                    expr.span.start_line,
                    expr.span.start_col,
                    f"If expression branches must return same type, got '{then_type}' and '{else_type}'",
                )
                return "unknown"
            return then_type
        if isinstance(expr, StructInitExpr):
            struct_fields = self.struct_defs.get(expr.type_name)
            if struct_fields is None:
                self._error(expr.span.start_line, expr.span.start_col, f"Unknown struct type '{expr.type_name}'")
                for _, field_expr in expr.field_initializers:
                    self._infer_expr_type(field_expr)
                return "unknown"

            expected_map = {field_name: field_type for field_name, field_type in struct_fields}
            seen_fields: set[str] = set()
            for field_name, field_expr in expr.field_initializers:
                if field_name in seen_fields:
                    self._error(expr.span.start_line, expr.span.start_col, f"Duplicate initializer for field '{field_name}'")
                    self._infer_expr_type(field_expr)
                    continue
                seen_fields.add(field_name)
                if field_name not in expected_map:
                    self._error(expr.span.start_line, expr.span.start_col, f"Struct '{expr.type_name}' has no field '{field_name}'")
                    self._infer_expr_type(field_expr)
                    continue

                actual_type = self._infer_expr_type(field_expr)
                expected_type = expected_map[field_name]
                if not self._is_assignable(expected_type, actual_type):
                    self._error(
                        field_expr.span.start_line,
                        field_expr.span.start_col,
                        f"Field '{field_name}' expects '{expected_type}', got '{actual_type}'",
                    )

            missing_fields = [field_name for field_name, _ in struct_fields if field_name not in seen_fields]
            if missing_fields:
                self._error(
                    expr.span.start_line,
                    expr.span.start_col,
                    f"Missing struct field initializer(s): {', '.join(missing_fields)}",
                )
            return expr.type_name
        if isinstance(expr, PostfixExpr):
            if not isinstance(expr.operand, IdentifierExpr):
                self._error(expr.span.start_line, expr.span.start_col, "Postfix operators require an identifier target")
                return "unknown"
            symbol = self.current_scope.resolve(expr.operand.name)
            if symbol is None:
                self._error(expr.span.start_line, expr.span.start_col, f"Undefined symbol '{expr.operand.name}'")
                return "unknown"
            if symbol.is_const:
                self._error(expr.span.start_line, expr.span.start_col, f"Cannot mutate const variable '{expr.operand.name}'")
            if symbol.type_name not in {"int", "float"}:
                self._error(expr.span.start_line, expr.span.start_col, "Postfix operators require numeric operand")
            return symbol.type_name
        if isinstance(expr, UnaryExpr):
            operand_type = self._infer_expr_type(expr.operand)
            if expr.operator == "!":
                return "bool"
            if expr.operator == "~":
                if operand_type != "int":
                    self._error(expr.span.start_line, expr.span.start_col, "Bitwise not requires int operand")
                    return "unknown"
                return "int"
            if expr.operator == "-" and operand_type in {"int", "float"}:
                return operand_type
            return "unknown"
        if isinstance(expr, BitwiseExpr):
            left = self._infer_expr_type(expr.left)
            right = self._infer_expr_type(expr.right)
            if left == "Pin" or right == "Pin":
                self._error(expr.span.start_line, expr.span.start_col, "Math/bitwise operations are not allowed on Pin values")
                return "unknown"
            if left != "int" or right != "int":
                self._error(expr.span.start_line, expr.span.start_col, f"Operator '{expr.operator}' requires int operands")
                return "unknown"
            return "int"
        if isinstance(expr, BinaryExpr):
            left = self._infer_expr_type(expr.left)
            right = self._infer_expr_type(expr.right)
            if expr.operator in {"+", "-", "*", "/", "%"}:
                if left == "Pin" or right == "Pin":
                    self._error(expr.span.start_line, expr.span.start_col, "Math operations are not allowed on Pin values")
                    return "unknown"
                if left == "Duration" or right == "Duration":
                    if expr.operator in {"+", "-"} and left == "Duration" and right == "Duration":
                        return "Duration"
                    self._error(expr.span.start_line, expr.span.start_col, "Only Duration +/- Duration is supported")
                    return "unknown"
                if left == "float" or right == "float":
                    return "float"
                if left == "int" and right == "int":
                    return "int"
                return "unknown"
            if expr.operator in {"==", "!=", ">", "<", ">=", "<="}:
                if (left == "Duration" or right == "Duration") and not (left == "Duration" and right == "Duration"):
                    self._error(expr.span.start_line, expr.span.start_col, "Duration comparisons require both operands to be Duration")
                    return "unknown"
                return "bool"
            if expr.operator in {"&&", "||"}:
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

    def _validate_assignment_target_mutability(self, target: Expr) -> None:
        if isinstance(target, IdentifierExpr):
            symbol = self.current_scope.resolve(target.name)
            if symbol is not None and symbol.is_const:
                self._error(target.span.start_line, target.span.start_col, f"Cannot reassign const variable '{target.name}'")
            return

        if isinstance(target, MemberAccessExpr):
            owner = target.object_expr
            if isinstance(owner, IdentifierExpr):
                owner_symbol = self.current_scope.resolve(owner.name)
                if owner_symbol is not None and owner_symbol.is_const:
                    self._error(target.span.start_line, target.span.start_col, f"Cannot mutate field of const variable '{owner.name}'")
            else:
                self._validate_assignment_target_mutability(owner)

    def _error(self, line: int, column: int, message: str) -> None:
        if self.in_unsafe_block:
            return
        self.issues.append(SemanticIssue("error", message, self.current_file_path, line, column))

    def _warn(self, line: int, column: int, message: str) -> None:
        self.issues.append(SemanticIssue("warning", message, self.current_file_path, line, column))
