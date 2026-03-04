"""Backend strategy-based C++ generators for the ESP32 DSL."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    LiteralExpr,
    LoopBlockDecl,
    Program,
    PwmWriteStmt,
    RgbWriteStmt,
    ReturnStmt,
    SourceSpan,
    UnaryExpr,
    UnsafeBlockStmt,
    VarDecl,
    WhileStmt,
    WifiConnectStmt,
)


@dataclass(frozen=True)
class SourceMapEntry:
    file_path: str
    line: int
    column: int


@dataclass
class GeneratedOutput:
    code: str
    line_map: Dict[int, SourceMapEntry]


class CodegenError(Exception):
    """Raised when a DSL construct cannot be emitted for the selected backend."""

    def __init__(self, message: str, span: Optional[SourceSpan] = None) -> None:
        super().__init__(message)
        self.span = span


@dataclass
class EmittedLine:
    text: str
    span: Optional[SourceSpan] = None


@dataclass
class GenerationContext:
    globals: List[EmittedLine] = field(default_factory=list)
    setup_lines: List[EmittedLine] = field(default_factory=list)
    loop_lines: List[EmittedLine] = field(default_factory=list)
    functions: List[List[EmittedLine]] = field(default_factory=list)


class ArduinoGeneratorBase:
    """Base codegen strategy with overridable hardware hooks."""

    def __init__(self) -> None:
        self.ctx = GenerationContext()
        self.line_map: Dict[int, SourceMapEntry] = {}

    def generate(self, program: Program) -> GeneratedOutput:
        self.ctx.globals.extend(EmittedLine(line) for line in self._global_prelude_lines())

        for decl in program.declarations:
            if isinstance(decl, FunctionDecl):
                self.ctx.functions.append(self._emit_function(decl))
            elif isinstance(decl, LoopBlockDecl):
                self.ctx.loop_lines.extend(self._emit_block(decl.body))
            elif isinstance(decl, VarDecl):
                self.ctx.globals.append(EmittedLine(self._emit_var_decl(decl), decl.span))
            else:
                self.ctx.setup_lines.extend(self._emit_stmt(decl))

        code = self._compose_translation_unit()
        return GeneratedOutput(code=code, line_map=self.line_map)

    def _compose_translation_unit(self) -> str:
        all_lines: List[str] = []
        generated_line = 1

        def append_line(text: str, span: Optional[SourceSpan] = None) -> None:
            nonlocal generated_line
            all_lines.append(text)
            if span is not None:
                self.line_map[generated_line] = SourceMapEntry(
                    file_path=span.file_path,
                    line=span.start_line,
                    column=span.start_col,
                )
            generated_line += 1

        for item in self.ctx.globals:
            append_line(item.text, item.span)

        if self.ctx.globals:
            append_line("")

        for index, fn_lines in enumerate(self.ctx.functions):
            for line in fn_lines:
                append_line(line.text, line.span)
            if index < len(self.ctx.functions) - 1:
                append_line("")

        if self.ctx.functions:
            append_line("")

        append_line("void setup() {")
        if self.ctx.setup_lines:
            for line in self.ctx.setup_lines:
                append_line(f"  {line.text}", line.span)
        else:
            append_line("  // setup")
        append_line("}")
        append_line("")
        append_line("void loop() {")
        if self.ctx.loop_lines:
            for line in self.ctx.loop_lines:
                append_line(f"  {line.text}", line.span)
        else:
            append_line("  // loop")
        append_line("}")

        return "\n".join(all_lines) + "\n"

    def _global_prelude_lines(self) -> List[str]:
        return ["#include <Arduino.h>", "#include <WiFi.h>", ""]

    def _emit_function(self, fn: FunctionDecl) -> List[EmittedLine]:
        out: List[EmittedLine] = []
        ret = self._map_type(fn.return_type)
        params = ", ".join(f"{self._map_type(p.type_name)} {p.name}" for p in fn.params)
        out.append(EmittedLine(f"{ret} {fn.name}({params}) {{", fn.span))
        body = self._emit_block(fn.body)
        if body:
            for line in body:
                out.append(EmittedLine(f"  {line.text}", line.span))
        elif fn.return_type == "void":
            out.append(EmittedLine("  return;", fn.span))
        out.append(EmittedLine("}", fn.span))
        return out

    def _emit_block(self, block: BlockStmt) -> List[EmittedLine]:
        out: List[EmittedLine] = []
        for stmt in block.statements:
            out.extend(self._emit_stmt(stmt))
        return out

    def _emit_stmt(self, stmt) -> List[EmittedLine]:
        if isinstance(stmt, VarDecl):
            return [EmittedLine(self._emit_var_decl(stmt), stmt.span)]
        if isinstance(stmt, ExprStmt):
            return [EmittedLine(f"{self._emit_expr(stmt.expression)};", stmt.span)]
        if isinstance(stmt, ReturnStmt):
            line = "return;" if stmt.value is None else f"return {self._emit_expr(stmt.value)};"
            return [EmittedLine(line, stmt.span)]
        if isinstance(stmt, IfStmt):
            lines: List[EmittedLine] = [EmittedLine(f"if ({self._emit_expr(stmt.condition)}) {{", stmt.span)]
            lines.extend(EmittedLine(f"  {line.text}", line.span) for line in self._emit_block(stmt.then_branch))
            lines.append(EmittedLine("}", stmt.span))
            if stmt.else_branch is not None:
                lines.append(EmittedLine("else {", stmt.else_branch.span))
                lines.extend(EmittedLine(f"  {line.text}", line.span) for line in self._emit_block(stmt.else_branch))
                lines.append(EmittedLine("}", stmt.else_branch.span))
            return lines
        if isinstance(stmt, WhileStmt):
            lines: List[EmittedLine] = [EmittedLine(f"while ({self._emit_expr(stmt.condition)}) {{", stmt.span)]
            lines.extend(EmittedLine(f"  {line.text}", line.span) for line in self._emit_block(stmt.body))
            lines.append(EmittedLine("}", stmt.span))
            return lines
        if isinstance(stmt, ForStmt):
            init = self._emit_for_init(stmt.init)
            cond = self._emit_expr(stmt.condition) if stmt.condition is not None else "true"
            update = self._emit_expr(stmt.update) if stmt.update is not None else ""
            lines: List[EmittedLine] = [EmittedLine(f"for ({init}; {cond}; {update}) {{", stmt.span)]
            lines.extend(EmittedLine(f"  {line.text}", line.span) for line in self._emit_block(stmt.body))
            lines.append(EmittedLine("}", stmt.span))
            return lines
        if isinstance(stmt, GpioModeStmt):
            mode = "OUTPUT" if stmt.mode == "out" else "INPUT"
            return [EmittedLine(f"pinMode({self._emit_expr(stmt.pin)}, {mode});", stmt.span)]
        if isinstance(stmt, DigitalWriteStmt):
            return [EmittedLine(self._emit_digital_write(stmt), stmt.span)]
        if isinstance(stmt, PwmWriteStmt):
            return [EmittedLine(line, stmt.span) for line in self._emit_pwm_write(stmt)]
        if isinstance(stmt, RgbWriteStmt):
            return [EmittedLine(line, stmt.span) for line in self._emit_rgb_write(stmt)]
        if isinstance(stmt, WifiConnectStmt):
            return [EmittedLine(line, stmt.span) for line in self._emit_wifi_connect(stmt)]
        if isinstance(stmt, DelayStmt):
            return [EmittedLine(self._emit_delay(stmt), stmt.span)]
        if isinstance(stmt, UnsafeBlockStmt):
            lines = stmt.raw_cpp.splitlines() or [""]
            return [EmittedLine(line, stmt.span) for line in lines]
        if isinstance(stmt, BlockStmt):
            lines = [EmittedLine("{", stmt.span)]
            lines.extend(EmittedLine(f"  {line.text}", line.span) for line in self._emit_block(stmt))
            lines.append(EmittedLine("}", stmt.span))
            return lines
        return [EmittedLine("/* unsupported statement */", None)]

    def _emit_for_init(self, init_stmt) -> str:
        if init_stmt is None:
            return ""
        if isinstance(init_stmt, VarDecl):
            return self._emit_var_decl(init_stmt).rstrip(";")
        if isinstance(init_stmt, ExprStmt):
            return self._emit_expr(init_stmt.expression)
        return ""

    def _emit_var_decl(self, decl: VarDecl) -> str:
        cpp_type = self._map_type(decl.type_name or "int")
        init = ""
        if decl.initializer is not None:
            init = f" = {self._emit_expr(decl.initializer)}"
        return f"{cpp_type} {decl.name}{init};"

    def _emit_expr(self, expr: Expr) -> str:
        if isinstance(expr, IdentifierExpr):
            return expr.name
        if isinstance(expr, LiteralExpr):
            if expr.type_name == "string":
                return f'"{str(expr.value)}"'
            if expr.type_name == "bool":
                return "true" if bool(expr.value) else "false"
            return str(expr.value)
        if isinstance(expr, UnaryExpr):
            return f"({expr.operator}{self._emit_expr(expr.operand)})"
        if isinstance(expr, BinaryExpr):
            return f"({self._emit_expr(expr.left)} {expr.operator} {self._emit_expr(expr.right)})"
        if isinstance(expr, AssignmentExpr):
            return f"({expr.target.name} = {self._emit_expr(expr.value)})"
        if isinstance(expr, CallExpr):
            callee = self._emit_expr(expr.callee)
            args = ", ".join(self._emit_expr(arg) for arg in expr.args)
            return f"{callee}({args})"
        return "0"

    def _map_type(self, type_name: str) -> str:
        mapping = {
            "int": "int32_t",
            "float": "float",
            "bool": "bool",
            "string": "String",
            "void": "void",
        }
        return mapping.get(type_name, type_name)

    def _emit_digital_write(self, stmt: DigitalWriteStmt) -> str:
        return f"digitalWrite({self._emit_expr(stmt.pin)}, {self._emit_expr(stmt.value)});"

    def _emit_delay(self, stmt: DelayStmt) -> str:
        return f"delay({self._emit_expr(stmt.milliseconds)});"

    def _emit_pwm_write(self, stmt: PwmWriteStmt) -> List[str]:
        channel = self._emit_expr(stmt.channel) if stmt.channel is not None else "0"
        pin = self._emit_expr(stmt.pin)
        duty = self._emit_expr(stmt.duty)
        return [
            f"ledcAttachPin({pin}, {channel});",
            f"ledcWrite({channel}, {duty});",
        ]

    def _emit_wifi_connect(self, stmt: WifiConnectStmt) -> List[str]:
        ssid = self._emit_expr(stmt.ssid)
        password = self._emit_expr(stmt.password)
        return [
            f"WiFi.begin({ssid}, {password});",
            "while (WiFi.status() != WL_CONNECTED) { delay(100); }",
        ]

    def _emit_rgb_write(self, stmt: RgbWriteStmt) -> List[str]:
        raise CodegenError("rgbWrite is not supported on this target backend", stmt.span)


class ESP32Generator(ArduinoGeneratorBase):
    """ESP32-specific backend with fast GPIO and RTOS-safe delay."""

    def _global_prelude_lines(self) -> List[str]:
        return [
            "#include <Arduino.h>",
            "#include <WiFi.h>",
            "#include \"soc/gpio_struct.h\"",
            "",
            "static inline void __dsl_fast_write(uint8_t pin, bool high) {",
            "  if (pin < 32) {",
            "    if (high) GPIO.out_w1ts = (1UL << pin);",
            "    else GPIO.out_w1tc = (1UL << pin);",
            "  } else {",
            "    uint32_t bit = (1UL << (pin - 32));",
            "    if (high) GPIO.out1_w1ts.val = bit;",
            "    else GPIO.out1_w1tc.val = bit;",
            "  }",
            "}",
            "",
        ]

    def _emit_digital_write(self, stmt: DigitalWriteStmt) -> str:
        pin = self._emit_expr(stmt.pin)
        value = self._emit_expr(stmt.value)
        return f"__dsl_fast_write(static_cast<uint8_t>({pin}), static_cast<bool>({value}));"

    def _emit_delay(self, stmt: DelayStmt) -> str:
        return f"vTaskDelay(pdMS_TO_TICKS({self._emit_expr(stmt.milliseconds)}));"

    def _emit_wifi_connect(self, stmt: WifiConnectStmt) -> List[str]:
        ssid = self._emit_expr(stmt.ssid)
        password = self._emit_expr(stmt.password)
        return [
            f"WiFi.begin({ssid}, {password});",
            "while (WiFi.status() != WL_CONNECTED) { vTaskDelay(pdMS_TO_TICKS(100)); }",
        ]

    def _emit_pwm_write(self, stmt: PwmWriteStmt) -> List[str]:
        pin = self._emit_expr(stmt.pin)
        duty = self._emit_expr(stmt.duty)
        return [
            f"ledcAttach({pin}, 5000, 8);",
            f"ledcWrite({pin}, {duty});",
        ]

    def _emit_rgb_write(self, stmt: RgbWriteStmt) -> List[str]:
        pin = self._emit_expr(stmt.pin)
        red = self._emit_expr(stmt.red)
        green = self._emit_expr(stmt.green)
        blue = self._emit_expr(stmt.blue)
        return [f"neopixelWrite({pin}, {red}, {green}, {blue});"]


class GenericArduinoGenerator(ArduinoGeneratorBase):
    """Generic Arduino fallback backend with standard API calls."""

    def _global_prelude_lines(self) -> List[str]:
        return ["#include <Arduino.h>", "#include <WiFi.h>", ""]

    def _emit_digital_write(self, stmt: DigitalWriteStmt) -> str:
        return f"digitalWrite({self._emit_expr(stmt.pin)}, {self._emit_expr(stmt.value)});"

    def _emit_delay(self, stmt: DelayStmt) -> str:
        return f"delay({self._emit_expr(stmt.milliseconds)});"

    def _emit_pwm_write(self, stmt: PwmWriteStmt) -> List[str]:
        pin = self._emit_expr(stmt.pin)
        duty = self._emit_expr(stmt.duty)
        return [f"analogWrite({pin}, {duty});"]

    def _emit_rgb_write(self, stmt: RgbWriteStmt) -> List[str]:
        raise CodegenError(
            "rgbWrite is only supported on ESP32 targets with neopixelWrite capability. Use --target esp32.",
            stmt.span,
        )


def create_generator(target: str) -> ArduinoGeneratorBase:
    """Factory for backend generators."""

    normalized = target.strip().lower()
    if normalized == "esp32":
        return ESP32Generator()
    if normalized == "generic":
        return GenericArduinoGenerator()
    raise ValueError(f"Unknown codegen target '{target}'")
