"""Backend strategy-based C++ generators for the ESP32 DSL."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

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
    LiteralExpr,
    LoopBlockDecl,
    MemberAccessExpr,
    MatchStmt,
    PostfixExpr,
    Program,
    PwmWriteStmt,
    RgbWriteStmt,
    ReturnStmt,
    SourceSpan,
    StructDecl,
    StructInitExpr,
    SpawnStmt,
    TaskDecl,
    TaskDecorator,
    UnaryExpr,
    UnsafeBlockStmt,
    VarDecl,
    WhileStmt,
    WifiConnectStmt,
)


@dataclass(frozen=True)
class SourceMapEntry:
    """Maps one generated C++ line back to original DSL source coordinates."""

    file_path: str
    line: int
    column: int


@dataclass
class GeneratedOutput:
    """Final emitted C++ translation unit and generated-to-source line mapping."""

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
        self.struct_field_order: Dict[str, List[str]] = {}
        self.task_decl_map: Dict[str, TaskDecl] = {}
        self.required_headers: Set[str] = set()

    def generate(self, program: Program) -> GeneratedOutput:
        """Lower a parsed NOVA program into Arduino C++ for a concrete backend."""

        self.ctx = GenerationContext()
        self.line_map = {}
        self.struct_field_order = {}
        self.task_decl_map = {}
        self.required_headers = self._collect_required_headers(program)

        self.ctx.globals.extend(EmittedLine(line) for line in self._global_prelude_lines())

        # First pass: capture struct layouts so later struct literals can be ordered deterministically.
        for decl in program.declarations:
            if isinstance(decl, StructDecl):
                self.struct_field_order[decl.name] = [field.name for field in decl.fields]
                self.ctx.globals.extend(self._emit_struct_decl(decl))
                self.ctx.globals.append(EmittedLine(""))

        # Second pass: predeclare task entrypoints before setup()/loop() emission.
        for decl in program.declarations:
            if isinstance(decl, TaskDecl):
                self.task_decl_map[decl.name] = decl
                self.ctx.globals.append(EmittedLine(f"void __task_{decl.name}(void* pvParameters);", decl.span))

        if self.task_decl_map:
            self.ctx.globals.append(EmittedLine(""))

        for decl in program.declarations:
            if isinstance(decl, StructDecl):
                continue
            if isinstance(decl, TaskDecl):
                self.ctx.functions.append(self._emit_task_function(decl))
                self.ctx.setup_lines.append(EmittedLine(self._emit_task_spawn_line(decl.name), decl.span))
                continue
            if isinstance(decl, BusDecl):
                if decl.bus_type.upper() == "I2C":
                    self.ctx.setup_lines.append(
                        EmittedLine(
                            f"Wire.begin({self._emit_expr(decl.sda)}, {self._emit_expr(decl.scl)}, {self._emit_expr(decl.freq_hz)});",
                            decl.span,
                        )
                    )
                continue
            if isinstance(decl, FunctionDecl):
                self.ctx.functions.append(self._emit_function(decl))
            elif isinstance(decl, LoopBlockDecl):
                self.ctx.loop_lines.extend(self._emit_block(decl.body))
            elif isinstance(decl, VarDecl):
                self.ctx.globals.append(EmittedLine(self._emit_var_decl(decl, is_global=True), decl.span))
            else:
                self.ctx.setup_lines.extend(self._emit_stmt(decl))

        code = self._compose_translation_unit()
        return GeneratedOutput(code=code, line_map=self.line_map)

    def _compose_translation_unit(self) -> str:
        """Assemble all generated sections into one valid Arduino translation unit."""

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
        return self._global_include_lines()

    def _global_include_lines(self) -> List[str]:
        includes = ["#include <Arduino.h>"]
        if "WiFi.h" in self.required_headers:
            includes.append("#include <WiFi.h>")
        if "WebServer.h" in self.required_headers:
            includes.append("#include <WebServer.h>")
        if "Wire.h" in self.required_headers:
            includes.append("#include <Wire.h>")
        includes.append("")
        return includes

    def _collect_required_headers(self, program: Program) -> Set[str]:
        headers: Set[str] = set()
        for decl in program.declarations:
            self._collect_headers_from_decl(decl, headers)
        return headers

    def _collect_headers_from_decl(self, decl, headers: Set[str]) -> None:
        if isinstance(decl, TaskDecl):
            if decl.body is not None:
                self._collect_headers_from_block(decl.body, headers)
            return
        if isinstance(decl, FunctionDecl):
            self._collect_headers_from_block(decl.body, headers)
            return
        if isinstance(decl, LoopBlockDecl):
            self._collect_headers_from_block(decl.body, headers)
            return
        if isinstance(decl, VarDecl):
            if decl.initializer is not None:
                self._collect_headers_from_expr(decl.initializer, headers)
            return
        if isinstance(decl, BusDecl):
            if decl.bus_type.upper() == "I2C":
                headers.add("Wire.h")
            self._collect_headers_from_expr(decl.sda, headers)
            self._collect_headers_from_expr(decl.scl, headers)
            self._collect_headers_from_expr(decl.freq_hz, headers)
            return

    def _collect_headers_from_block(self, block: BlockStmt, headers: Set[str]) -> None:
        for stmt in block.statements:
            self._collect_headers_from_stmt(stmt, headers)

    def _collect_headers_from_stmt(self, stmt, headers: Set[str]) -> None:
        if isinstance(stmt, VarDecl):
            if stmt.initializer is not None:
                self._collect_headers_from_expr(stmt.initializer, headers)
            return
        if isinstance(stmt, ExprStmt):
            self._collect_headers_from_expr(stmt.expression, headers)
            return
        if isinstance(stmt, ReturnStmt):
            if stmt.value is not None:
                self._collect_headers_from_expr(stmt.value, headers)
            return
        if isinstance(stmt, IfStmt):
            self._collect_headers_from_expr(stmt.condition, headers)
            self._collect_headers_from_block(stmt.then_branch, headers)
            if stmt.else_branch is not None:
                self._collect_headers_from_block(stmt.else_branch, headers)
            return
        if isinstance(stmt, MatchStmt):
            self._collect_headers_from_expr(stmt.value, headers)
            for arm in stmt.arms:
                if arm.pattern is not None:
                    self._collect_headers_from_expr(arm.pattern, headers)
                self._collect_headers_from_block(arm.body, headers)
            return
        if isinstance(stmt, WhileStmt):
            self._collect_headers_from_expr(stmt.condition, headers)
            self._collect_headers_from_block(stmt.body, headers)
            return
        if isinstance(stmt, ForStmt):
            if stmt.init is not None:
                self._collect_headers_from_stmt(stmt.init, headers)
            if stmt.condition is not None:
                self._collect_headers_from_expr(stmt.condition, headers)
            if stmt.update is not None:
                self._collect_headers_from_expr(stmt.update, headers)
            self._collect_headers_from_block(stmt.body, headers)
            return
        if isinstance(stmt, GpioModeStmt):
            self._collect_headers_from_expr(stmt.pin, headers)
            return
        if isinstance(stmt, DigitalWriteStmt):
            self._collect_headers_from_expr(stmt.pin, headers)
            self._collect_headers_from_expr(stmt.value, headers)
            return
        if isinstance(stmt, PwmWriteStmt):
            self._collect_headers_from_expr(stmt.pin, headers)
            self._collect_headers_from_expr(stmt.duty, headers)
            if stmt.channel is not None:
                self._collect_headers_from_expr(stmt.channel, headers)
            return
        if isinstance(stmt, RgbWriteStmt):
            self._collect_headers_from_expr(stmt.pin, headers)
            self._collect_headers_from_expr(stmt.red, headers)
            self._collect_headers_from_expr(stmt.green, headers)
            self._collect_headers_from_expr(stmt.blue, headers)
            return
        if isinstance(stmt, DelayStmt):
            self._collect_headers_from_expr(stmt.milliseconds, headers)
            return
        if isinstance(stmt, WifiConnectStmt):
            headers.add("WiFi.h")
            self._collect_headers_from_expr(stmt.ssid, headers)
            self._collect_headers_from_expr(stmt.password, headers)
            return
        if isinstance(stmt, UnsafeBlockStmt):
            self._collect_headers_from_raw_cpp(stmt.raw_cpp, headers)
            return
        if isinstance(stmt, BlockStmt):
            self._collect_headers_from_block(stmt, headers)

    def _collect_headers_from_expr(self, expr: Expr, headers: Set[str]) -> None:
        if isinstance(expr, IfExpr):
            self._collect_headers_from_expr(expr.condition, headers)
            self._collect_headers_from_block(expr.then_block, headers)
            self._collect_headers_from_expr(expr.then_value, headers)
            self._collect_headers_from_block(expr.else_block, headers)
            self._collect_headers_from_expr(expr.else_value, headers)
            return
        if isinstance(expr, MemberAccessExpr):
            self._collect_headers_from_expr(expr.object_expr, headers)
            return
        if isinstance(expr, UnaryExpr):
            self._collect_headers_from_expr(expr.operand, headers)
            return
        if isinstance(expr, PostfixExpr):
            self._collect_headers_from_expr(expr.operand, headers)
            return
        if isinstance(expr, CastExpr):
            self._collect_headers_from_expr(expr.expression, headers)
            return
        if isinstance(expr, AssignmentExpr):
            self._collect_headers_from_expr(expr.target, headers)
            self._collect_headers_from_expr(expr.value, headers)
            return
        if isinstance(expr, BinaryExpr) or isinstance(expr, BitwiseExpr):
            self._collect_headers_from_expr(expr.left, headers)
            self._collect_headers_from_expr(expr.right, headers)
            return
        if isinstance(expr, CallExpr):
            self._collect_headers_from_expr(expr.callee, headers)
            for arg in expr.args:
                self._collect_headers_from_expr(arg, headers)
            return
        if isinstance(expr, StructInitExpr):
            for _, value_expr in expr.field_initializers:
                self._collect_headers_from_expr(value_expr, headers)

    def _collect_headers_from_raw_cpp(self, raw_cpp: str, headers: Set[str]) -> None:
        if "WebServer" in raw_cpp:
            headers.add("WebServer.h")
        if "WiFi" in raw_cpp or "WL_CONNECTED" in raw_cpp:
            headers.add("WiFi.h")
        if "Wire" in raw_cpp:
            headers.add("Wire.h")

    def _emit_task_function(self, task_decl: TaskDecl) -> List[EmittedLine]:
        out: List[EmittedLine] = [EmittedLine(f"void __task_{task_decl.name}(void* pvParameters) {{", task_decl.span)]
        out.append(EmittedLine("  for (;;) {", task_decl.span))
        if task_decl.body is not None:
            for line in self._emit_block(task_decl.body):
                out.append(EmittedLine(f"    {line.text}", line.span))
        out.append(EmittedLine(f"    vTaskDelay(pdMS_TO_TICKS({self._task_rate_ms_expr(task_decl)}));", task_decl.span))
        out.append(EmittedLine("  }", task_decl.span))
        out.append(EmittedLine("}", task_decl.span))
        return out

    def _emit_task_spawn_line(self, task_name: str) -> str:
        decl = self.task_decl_map.get(task_name)
        core_expr = self._task_core_expr(decl)
        return (
            f'xTaskCreatePinnedToCore(__task_{task_name}, "{task_name}", 8192, nullptr, 1, nullptr, {core_expr});'
        )

    def _task_core_expr(self, task_decl: Optional[TaskDecl]) -> str:
        if task_decl is None:
            return "tskNO_AFFINITY"
        for decorator in task_decl.decorators:
            if decorator.name == "core":
                return self._emit_expr(decorator.value)
        return "tskNO_AFFINITY"

    def _task_rate_ms_expr(self, task_decl: TaskDecl) -> str:
        for decorator in task_decl.decorators:
            if decorator.name != "rate":
                continue
            value = decorator.value
            if isinstance(value, LiteralExpr):
                if value.type_name == "int":
                    return str(int(value.value))
                if value.type_name.lower() == "duration" and isinstance(value.value, dict):
                    unit = str(value.value.get("unit", "ms"))
                    amount = int(value.value.get("value", 0))
                    if unit == "us":
                        return str(max(1, amount // 1000))
                    if unit == "s":
                        return str(amount * 1000)
                    return str(amount)
            return self._emit_expr(value)
        return "1"

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
        """Lower one statement node into one or more C++ lines."""

        if isinstance(stmt, StructDecl) or isinstance(stmt, TaskDecl) or isinstance(stmt, BusDecl):
            return []
        if isinstance(stmt, SpawnStmt):
            return [EmittedLine(self._emit_task_spawn_line(stmt.task_name), stmt.span)]
        if isinstance(stmt, VarDecl):
            return [EmittedLine(self._emit_var_decl(stmt, is_global=False), stmt.span)]
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
        if isinstance(stmt, MatchStmt):
            lines: List[EmittedLine] = [EmittedLine(f"switch ({self._emit_expr(stmt.value)}) {{", stmt.span)]
            for arm in stmt.arms:
                if arm.is_wildcard:
                    lines.append(EmittedLine("default: {", arm.span))
                else:
                    pattern_text = self._emit_expr(arm.pattern) if arm.pattern is not None else "0"
                    lines.append(EmittedLine(f"case {pattern_text}: {{", arm.span))
                lines.extend(EmittedLine(f"  {line.text}", line.span) for line in self._emit_block(arm.body))
                lines.append(EmittedLine("  break;", arm.span))
                lines.append(EmittedLine("}", arm.span))
            lines.append(EmittedLine("}", stmt.span))
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
            lines = [EmittedLine("{", stmt.span)]
            for line in (stmt.raw_cpp.splitlines() or [""]):
                lines.append(EmittedLine(f"  {line}", stmt.span))
            lines.append(EmittedLine("}", stmt.span))
            return lines
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
            return self._emit_var_decl(init_stmt, is_global=False).rstrip(";")
        if isinstance(init_stmt, ExprStmt):
            return self._emit_expr(init_stmt.expression)
        return ""

    def _emit_var_decl(self, decl: VarDecl, is_global: bool) -> str:
        cpp_type = self._map_type(decl.type_name or "int")
        qualifiers: List[str] = []
        if decl.is_const:
            qualifiers.append("const")
        if decl.is_volatile:
            qualifiers.append("volatile")
        qualifier_prefix = " ".join(qualifiers)
        if qualifier_prefix:
            qualifier_prefix += " "

        init = ""
        if decl.initializer is not None:
            if isinstance(decl.initializer, StructInitExpr):
                init_values = ", ".join(self._emit_expr(value_expr) for value_expr in self._ordered_struct_values(decl.initializer))
                init = f" = {{{init_values}}}"
            else:
                init = f" = {self._emit_expr(decl.initializer)}"

        progmem = " PROGMEM" if is_global and decl.is_const else ""
        return f"{qualifier_prefix}{cpp_type} {decl.name}{progmem}{init};"

    def _emit_expr(self, expr: Expr) -> str:
        """Lower expression nodes to C++ expression text."""

        if isinstance(expr, IdentifierExpr):
            return expr.name
        if isinstance(expr, MemberAccessExpr):
            return f"({self._emit_expr(expr.object_expr)}.{expr.member_name})"
        if isinstance(expr, IfExpr):
            cond = self._emit_expr(expr.condition)
            then_value = self._emit_expr(expr.then_value)
            else_value = self._emit_expr(expr.else_value)

            if not expr.then_block.statements and not expr.else_block.statements:
                return f"(({cond}) ? ({then_value}) : ({else_value}))"

            then_prelude = self._emit_expr_block_prelude(expr.then_block)
            else_prelude = self._emit_expr_block_prelude(expr.else_block)
            return (
                "([&]() { "
                f"if ({cond}) {{ {then_prelude}return {then_value}; }} "
                f"else {{ {else_prelude}return {else_value}; }} "
                "})()"
            )
        if isinstance(expr, LiteralExpr):
            if expr.type_name == "string":
                return f'"{str(expr.value)}"'
            if expr.type_name == "bool":
                return "true" if bool(expr.value) else "false"
            if expr.type_name.lower() == "duration" and isinstance(expr.value, dict):
                return str(int(expr.value.get("value", 0)))
            return str(expr.value)
        if isinstance(expr, UnaryExpr):
            return f"({expr.operator}{self._emit_expr(expr.operand)})"
        if isinstance(expr, PostfixExpr):
            return f"({self._emit_expr(expr.operand)}{expr.operator})"
        if isinstance(expr, BinaryExpr):
            return f"({self._emit_expr(expr.left)} {expr.operator} {self._emit_expr(expr.right)})"
        if isinstance(expr, BitwiseExpr):
            return f"({self._emit_expr(expr.left)} {expr.operator} {self._emit_expr(expr.right)})"
        if isinstance(expr, CastExpr):
            return f"(({self._map_type(expr.target_type)})({self._emit_expr(expr.expression)}))"
        if isinstance(expr, AssignmentExpr):
            value = self._emit_expr(expr.value)
            target = self._emit_assignment_target(expr.target)
            if expr.operator == "=":
                return f"({target} = {value})"

            op_map = {
                "+=": "+",
                "-=": "-",
                "*=": "*",
                "/=": "/",
            }
            lowered = op_map.get(expr.operator)
            if lowered is None:
                return f"({target} {expr.operator} {value})"
            return f"({target} = ({target} {lowered} {value}))"
        if isinstance(expr, StructInitExpr):
            init_values = ", ".join(self._emit_expr(value_expr) for value_expr in self._ordered_struct_values(expr))
            return f"{self._map_type(expr.type_name)}{{{init_values}}}"
        if isinstance(expr, CallExpr):
            callee = self._emit_expr(expr.callee)
            args = ", ".join(self._emit_expr(arg) for arg in expr.args)
            return f"{callee}({args})"
        return "0"

    def _emit_assignment_target(self, target: Expr) -> str:
        if isinstance(target, IdentifierExpr):
            return target.name
        if isinstance(target, MemberAccessExpr):
            return f"{self._emit_expr(target.object_expr)}.{target.member_name}"
        return self._emit_expr(target)

    def _emit_expr_block_prelude(self, block: BlockStmt) -> str:
        emitted_chunks: List[str] = []
        for stmt in block.statements:
            for line in self._emit_stmt(stmt):
                emitted_chunks.append(line.text)
        if not emitted_chunks:
            return ""
        return " ".join(emitted_chunks) + " "

    def _ordered_struct_values(self, init_expr: StructInitExpr) -> List[Expr]:
        provided = {field_name: field_value for field_name, field_value in init_expr.field_initializers}
        expected_order = self.struct_field_order.get(init_expr.type_name)
        if not expected_order:
            return [value for _, value in init_expr.field_initializers]
        return [provided[name] for name in expected_order if name in provided]

    def _emit_struct_decl(self, decl: StructDecl) -> List[EmittedLine]:
        lines: List[EmittedLine] = [EmittedLine(f"struct {decl.name} {{", decl.span)]
        for field in decl.fields:
            lines.append(EmittedLine(f"  {self._map_type(field.type_name)} {field.name};", field.span))
        lines.append(EmittedLine("};", decl.span))
        return lines

    def _map_type(self, type_name: str) -> str:
        mapping = {
            "int": "int32_t",
            "float": "float",
            "bool": "bool",
            "string": "String",
            "void": "void",
            "pin": "uint8_t",
            "duration": "uint32_t",
        }
        return mapping.get(type_name.lower(), type_name)

    def _emit_digital_write(self, stmt: DigitalWriteStmt) -> str:
        return f"digitalWrite({self._emit_expr(stmt.pin)}, {self._emit_expr(stmt.value)});"

    def _emit_delay(self, stmt: DelayStmt) -> str:
        if isinstance(stmt.milliseconds, LiteralExpr) and stmt.milliseconds.type_name.lower() == "duration":
            raw_value = stmt.milliseconds.value
            if isinstance(raw_value, dict):
                unit = str(raw_value.get("unit", "ms"))
                value = int(raw_value.get("value", 0))
                if unit == "us":
                    return f"delayMicroseconds({value});"
                if unit == "s":
                    return f"delay({value * 1000});"
                return f"delay({value});"
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
        return self._global_include_lines() + [
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
        return super()._emit_delay(stmt)

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
        return self._global_include_lines()

    def _emit_digital_write(self, stmt: DigitalWriteStmt) -> str:
        return f"digitalWrite({self._emit_expr(stmt.pin)}, {self._emit_expr(stmt.value)});"

    def _emit_delay(self, stmt: DelayStmt) -> str:
        return super()._emit_delay(stmt)

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
