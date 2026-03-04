"""Abstract syntax tree nodes for the ESP32 DSL compiler frontend."""

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
    span: SourceSpan
    declarations: List[Decl] = field(default_factory=list)


@dataclass
class ImportDecl(Decl):
    span: SourceSpan
    module_path: str


@dataclass
class Param(Node):
    span: SourceSpan
    name: str
    type_name: str


@dataclass
class FunctionDecl(Decl):
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
    span: SourceSpan
    name: str
    type_name: Optional[str]
    initializer: Optional[Expr]
    is_mutable: bool = True


@dataclass
class BlockStmt(Stmt):
    span: SourceSpan
    statements: List[Stmt] = field(default_factory=list)


@dataclass
class IfStmt(Stmt):
    span: SourceSpan
    condition: Expr
    then_branch: BlockStmt
    else_branch: Optional[BlockStmt]


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
class AssignmentExpr(Expr):
    span: SourceSpan
    target: "IdentifierExpr"
    value: Expr


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
    span: SourceSpan
    raw_cpp: str


TResult = TypeVar("TResult")


@runtime_checkable
class AstVisitor(Protocol[TResult]):
    """Protocol for AST visitor implementations."""

    def visit_program(self, node: Program) -> TResult: ...

    def visit_import_decl(self, node: ImportDecl) -> TResult: ...

    def visit_function_decl(self, node: FunctionDecl) -> TResult: ...

    def visit_loop_block_decl(self, node: LoopBlockDecl) -> TResult: ...

    def visit_var_decl(self, node: VarDecl) -> TResult: ...

    def visit_block_stmt(self, node: BlockStmt) -> TResult: ...

    def visit_if_stmt(self, node: IfStmt) -> TResult: ...

    def visit_while_stmt(self, node: WhileStmt) -> TResult: ...

    def visit_for_stmt(self, node: ForStmt) -> TResult: ...

    def visit_return_stmt(self, node: ReturnStmt) -> TResult: ...

    def visit_expr_stmt(self, node: ExprStmt) -> TResult: ...

    def visit_assignment_expr(self, node: AssignmentExpr) -> TResult: ...

    def visit_binary_expr(self, node: BinaryExpr) -> TResult: ...

    def visit_unary_expr(self, node: UnaryExpr) -> TResult: ...

    def visit_literal_expr(self, node: LiteralExpr) -> TResult: ...

    def visit_identifier_expr(self, node: IdentifierExpr) -> TResult: ...

    def visit_call_expr(self, node: CallExpr) -> TResult: ...

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
