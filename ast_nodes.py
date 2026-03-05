"""Abstract syntax tree nodes for the ESP32 DSL compiler frontend, including NOVA Phase 1 constructs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Protocol, Sequence, TypeVar, runtime_checkable


@dataclass(frozen=True)
class SourceSpan:
    """Represents a location range in a source file."""

    file_path: str
    start_line: int
    start_col: int
    end_line: int
    end_col: int


class Node:
    """Base AST node."""

    span: SourceSpan


class Decl(Node):
    """Base declaration node."""


class Stmt(Node):
    """Base statement node."""


class Expr(Node):
    """Base expression node."""


@dataclass
class Program(Node):
    """Root AST node representing a complete translation unit."""

    span: SourceSpan
    declarations: List[Decl] = field(default_factory=list)


@dataclass
class ImportDecl(Decl):
    span: SourceSpan
    module_path: str


@dataclass
class StructField(Node):
    span: SourceSpan
    name: str
    type_name: str


@dataclass
class StructDecl(Decl):
    """User-defined aggregate type declaration."""

    span: SourceSpan
    name: str
    fields: List[StructField] = field(default_factory=list)


@dataclass
class TaskDecorator(Node):
    span: SourceSpan
    name: str
    value: Expr


@dataclass
class TaskDecl(Decl):
    """FreeRTOS task declaration with optional decorators and task body."""

    span: SourceSpan
    name: str
    decorators: List[TaskDecorator] = field(default_factory=list)
    body: Optional["BlockStmt"] = None


@dataclass
class DeviceDecl(Node):
    span: SourceSpan
    name: str
    address: Expr


@dataclass
class BusDecl(Decl):
    span: SourceSpan
    bus_type: str
    name: str
    sda: Expr
    scl: Expr
    freq_hz: Expr
    devices: List[DeviceDecl] = field(default_factory=list)


@dataclass
class Param(Node):
    span: SourceSpan
    name: str
    type_name: str


@dataclass
class FunctionDecl(Decl):
    """Function declaration with typed parameters and a block body."""

    span: SourceSpan
    name: str
    params: List[Param]
    return_type: str
    body: "BlockStmt"


@dataclass
class LoopBlockDecl(Decl):
    span: SourceSpan
    body: "BlockStmt"


@dataclass
class VarDecl(Decl, Stmt):
    """Variable declaration statement/declaration with optional qualifiers."""

    span: SourceSpan
    name: str
    type_name: Optional[str]
    initializer: Optional[Expr]
    is_mutable: bool = True
    is_const: bool = False
    is_volatile: bool = False


@dataclass
class BlockStmt(Stmt):
    """Lexical block containing an ordered list of statements."""

    span: SourceSpan
    statements: List[Stmt] = field(default_factory=list)


@dataclass
class IfStmt(Stmt):
    span: SourceSpan
    condition: Expr
    then_branch: BlockStmt
    else_branch: Optional[BlockStmt]


@dataclass
class IfExpr(Expr):
    """Value-producing conditional expression with explicit branch blocks."""

    span: SourceSpan
    condition: Expr
    then_block: BlockStmt
    then_value: Expr
    else_block: BlockStmt
    else_value: Expr


@dataclass
class WhileStmt(Stmt):
    span: SourceSpan
    condition: Expr
    body: BlockStmt


@dataclass
class ForStmt(Stmt):
    span: SourceSpan
    init: Optional[Stmt]
    condition: Optional[Expr]
    update: Optional[Expr]
    body: BlockStmt


@dataclass
class ReturnStmt(Stmt):
    span: SourceSpan
    value: Optional[Expr]


@dataclass
class ExprStmt(Stmt):
    span: SourceSpan
    expression: Expr


@dataclass
class MatchArm(Node):
    span: SourceSpan
    pattern: Optional[Expr]
    is_wildcard: bool
    body: BlockStmt


@dataclass
class MatchStmt(Stmt):
    """Pattern dispatch statement lowered to backend switch/case forms."""

    span: SourceSpan
    value: Expr
    arms: List[MatchArm] = field(default_factory=list)


@dataclass
class SpawnStmt(Stmt):
    span: SourceSpan
    task_name: str


@dataclass
class AssignmentExpr(Expr):
    span: SourceSpan
    target: Expr
    value: Expr
    operator: str = "="


@dataclass
class BinaryExpr(Expr):
    span: SourceSpan
    left: Expr
    operator: str
    right: Expr


@dataclass
class UnaryExpr(Expr):
    span: SourceSpan
    operator: str
    operand: Expr


@dataclass
class PostfixExpr(Expr):
    span: SourceSpan
    operand: Expr
    operator: str


@dataclass
class BitwiseExpr(Expr):
    span: SourceSpan
    left: Expr
    operator: str
    right: Expr


@dataclass
class CastExpr(Expr):
    span: SourceSpan
    expression: Expr
    target_type: str


@dataclass
class LiteralExpr(Expr):
    span: SourceSpan
    value: object
    type_name: str


@dataclass
class IdentifierExpr(Expr):
    span: SourceSpan
    name: str


@dataclass
class CallExpr(Expr):
    span: SourceSpan
    callee: Expr
    args: List[Expr] = field(default_factory=list)


@dataclass
class StructInitExpr(Expr):
    """Named-field struct initialization expression."""

    span: SourceSpan
    type_name: str
    field_initializers: List[tuple[str, Expr]] = field(default_factory=list)


@dataclass
class MemberAccessExpr(Expr):
    span: SourceSpan
    object_expr: Expr
    member_name: str


@dataclass
class GpioModeStmt(Stmt):
    span: SourceSpan
    pin: Expr
    mode: str


@dataclass
class DigitalWriteStmt(Stmt):
    span: SourceSpan
    pin: Expr
    value: Expr


@dataclass
class PwmWriteStmt(Stmt):
    span: SourceSpan
    pin: Expr
    duty: Expr
    channel: Optional[Expr]


@dataclass
class RgbWriteStmt(Stmt):
    span: SourceSpan
    pin: Expr
    red: Expr
    green: Expr
    blue: Expr


@dataclass
class DelayStmt(Stmt):
    span: SourceSpan
    milliseconds: Expr


@dataclass
class WifiConnectStmt(Stmt):
    span: SourceSpan
    ssid: Expr
    password: Expr


@dataclass
class UnsafeBlockStmt(Stmt):
    """Raw backend code region that bypasses normal DSL semantic restrictions."""

    span: SourceSpan
    raw_cpp: str


TResult = TypeVar("TResult")


@runtime_checkable
class AstVisitor(Protocol[TResult]):
    """Protocol for AST visitor implementations."""

    def visit_program(self, node: Program) -> TResult: ...

    def visit_import_decl(self, node: ImportDecl) -> TResult: ...

    def visit_struct_decl(self, node: StructDecl) -> TResult: ...

    def visit_task_decl(self, node: TaskDecl) -> TResult: ...

    def visit_bus_decl(self, node: BusDecl) -> TResult: ...

    def visit_function_decl(self, node: FunctionDecl) -> TResult: ...

    def visit_loop_block_decl(self, node: LoopBlockDecl) -> TResult: ...

    def visit_var_decl(self, node: VarDecl) -> TResult: ...

    def visit_block_stmt(self, node: BlockStmt) -> TResult: ...

    def visit_if_stmt(self, node: IfStmt) -> TResult: ...

    def visit_if_expr(self, node: IfExpr) -> TResult: ...

    def visit_while_stmt(self, node: WhileStmt) -> TResult: ...

    def visit_for_stmt(self, node: ForStmt) -> TResult: ...

    def visit_return_stmt(self, node: ReturnStmt) -> TResult: ...

    def visit_expr_stmt(self, node: ExprStmt) -> TResult: ...

    def visit_match_stmt(self, node: MatchStmt) -> TResult: ...

    def visit_spawn_stmt(self, node: SpawnStmt) -> TResult: ...

    def visit_assignment_expr(self, node: AssignmentExpr) -> TResult: ...

    def visit_binary_expr(self, node: BinaryExpr) -> TResult: ...

    def visit_unary_expr(self, node: UnaryExpr) -> TResult: ...

    def visit_postfix_expr(self, node: PostfixExpr) -> TResult: ...

    def visit_bitwise_expr(self, node: BitwiseExpr) -> TResult: ...

    def visit_cast_expr(self, node: CastExpr) -> TResult: ...

    def visit_literal_expr(self, node: LiteralExpr) -> TResult: ...

    def visit_identifier_expr(self, node: IdentifierExpr) -> TResult: ...

    def visit_call_expr(self, node: CallExpr) -> TResult: ...

    def visit_struct_init_expr(self, node: StructInitExpr) -> TResult: ...

    def visit_member_access_expr(self, node: MemberAccessExpr) -> TResult: ...

    def visit_gpio_mode_stmt(self, node: GpioModeStmt) -> TResult: ...

    def visit_digital_write_stmt(self, node: DigitalWriteStmt) -> TResult: ...

    def visit_pwm_write_stmt(self, node: PwmWriteStmt) -> TResult: ...

    def visit_rgb_write_stmt(self, node: RgbWriteStmt) -> TResult: ...

    def visit_delay_stmt(self, node: DelayStmt) -> TResult: ...

    def visit_wifi_connect_stmt(self, node: WifiConnectStmt) -> TResult: ...

    def visit_unsafe_block_stmt(self, node: UnsafeBlockStmt) -> TResult: ...


def children_of_block(block: BlockStmt) -> Sequence[Stmt]:
    """Returns statements in a block; helper for passes that iterate blocks."""

    return block.statements
