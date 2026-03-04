"""Multi-file module graph resolution for the ESP32 DSL compiler."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set

from ast_nodes import ImportDecl, Program, SourceSpan
from lexer import LexError, Lexer
from parser import ParseError, Parser


@dataclass(frozen=True)
class ModuleIssue:
    severity: str
    message: str
    file_path: str
    line: int
    column: int


@dataclass
class ModuleUnit:
    path: Path
    source: str
    program: Program
    lex_errors: List[LexError] = field(default_factory=list)
    parse_errors: List[ParseError] = field(default_factory=list)
    imports: List["ImportEdge"] = field(default_factory=list)


@dataclass(frozen=True)
class ImportEdge:
    module_path: str
    span: SourceSpan


@dataclass
class ModuleGraph:
    entrypoint: Path
    modules: Dict[Path, ModuleUnit]
    topo_order: List[Path]
    issues: List[ModuleIssue]


class ModuleGraphResolver:
    """Resolves imports into an acyclic module graph and parses each module."""

    def __init__(self, default_extension: str = ".myext") -> None:
        self.default_extension = default_extension
        self.modules: Dict[Path, ModuleUnit] = {}
        self.topo_order: List[Path] = []
        self.issues: List[ModuleIssue] = []
        self._visiting: Set[Path] = set()
        self._visited: Set[Path] = set()

    def resolve(self, entrypoint: Path) -> ModuleGraph:
        root = entrypoint.resolve()
        self._dfs(root)
        return ModuleGraph(
            entrypoint=root,
            modules=self.modules,
            topo_order=self.topo_order,
            issues=self.issues,
        )

    def _dfs(self, module_path: Path) -> None:
        if module_path in self._visited:
            return
        if module_path in self._visiting:
            self.issues.append(
                ModuleIssue(
                    severity="error",
                    message=f"Circular import detected at '{module_path.name}'",
                    file_path=str(module_path),
                    line=1,
                    column=1,
                )
            )
            return

        self._visiting.add(module_path)

        if not module_path.exists():
            self.issues.append(
                ModuleIssue(
                    severity="error",
                    message="Module file not found",
                    file_path=str(module_path),
                    line=1,
                    column=1,
                )
            )
            self._visiting.remove(module_path)
            return

        source = module_path.read_text(encoding="utf-8")
        lexer = Lexer(source)
        tokens, lex_errors = lexer.tokenize()

        parser = Parser(tokens, file_path=str(module_path))
        program, parse_errors = parser.parse()

        imports = [
            ImportEdge(module_path=decl.module_path, span=decl.span)
            for decl in program.declarations
            if isinstance(decl, ImportDecl)
        ]

        unit = ModuleUnit(
            path=module_path,
            source=source,
            program=program,
            lex_errors=lex_errors,
            parse_errors=parse_errors,
            imports=imports,
        )
        self.modules[module_path] = unit

        for import_edge in imports:
            target = self._resolve_import_path(module_path.parent, import_edge.module_path)
            if target is None:
                self.issues.append(
                    ModuleIssue(
                        severity="error",
                        message=f"Unable to resolve import '{import_edge.module_path}'",
                        file_path=str(module_path),
                        line=import_edge.span.start_line,
                        column=import_edge.span.start_col,
                    )
                )
                continue
            if target in self._visiting:
                self.issues.append(
                    ModuleIssue(
                        severity="error",
                        message=f"Circular import detected while importing '{import_edge.module_path}'",
                        file_path=str(module_path),
                        line=import_edge.span.start_line,
                        column=import_edge.span.start_col,
                    )
                )
                continue
            self._dfs(target)

        self._visiting.remove(module_path)
        self._visited.add(module_path)
        self.topo_order.append(module_path)

    def _resolve_import_path(self, base_dir: Path, import_path: str) -> Path | None:
        raw = Path(import_path)
        candidates: List[Path] = []

        if raw.suffix:
            candidates.append((base_dir / raw).resolve())
        else:
            candidates.append((base_dir / f"{import_path}{self.default_extension}").resolve())
            candidates.append((base_dir / f"{import_path}.nova").resolve())
            candidates.append((base_dir / import_path).resolve())

        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None
