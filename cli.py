"""CLI entrypoint for the ESP32 DSL compiler/transpiler."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from ast_nodes import ImportDecl, Program, SourceSpan
from codegen import CodegenError, SourceMapEntry, create_generator
from lexer import LexError
from module_graph import ModuleGraph, ModuleGraphResolver, ModuleIssue
from parser import ParseError
from semantic import HARDWARE_PROFILES, SemanticAnalyzer, SemanticIssue


@dataclass(frozen=True)
class CompilerMessage:
    stage: str
    severity: str
    message: str
    line: int
    column: int
    file_path: str


@dataclass
class CompileArtifacts:
    source_path: Path
    generated_cpp_path: Path
    messages: List[CompilerMessage]
    line_map: Dict[int, SourceMapEntry]
    target: str
    board: str


def build_arg_parser() -> argparse.ArgumentParser:
    """Create argument parser with build/transpile/check subcommands."""

    parser = argparse.ArgumentParser(prog="mycompiler", description="ESP32 DSL compiler")
    sub = parser.add_subparsers(dest="command", required=True)
    board_choices = sorted(HARDWARE_PROFILES.keys())

    check_cmd = sub.add_parser("check", help="Lex/parse/semantic-check a DSL file")
    check_cmd.add_argument("input", type=Path, help="Path to DSL main file")
    check_cmd.add_argument("--target", choices=["esp32", "generic"], default="esp32", help="Codegen target backend")
    check_cmd.add_argument("--board", choices=board_choices, default="esp32", help="Hardware profile for semantic checks")

    transpile_cmd = sub.add_parser("transpile", help="Generate Arduino C++ from DSL")
    transpile_cmd.add_argument("input", type=Path, help="Path to DSL main file")
    transpile_cmd.add_argument("--out", type=Path, default=Path("build/main.cpp"), help="Output C++ path")
    transpile_cmd.add_argument("--target", choices=["esp32", "generic"], default="esp32", help="Codegen target backend")
    transpile_cmd.add_argument("--board", choices=board_choices, default="esp32", help="Hardware profile for semantic checks")

    build_cmd = sub.add_parser("build", help="Compile (and optionally upload) using arduino-cli")
    build_cmd.add_argument("input", type=Path, help="Path to DSL main file")
    build_cmd.add_argument("--out", type=Path, default=Path("build/main.cpp"), help="Output C++ path")
    build_cmd.add_argument("--fqbn", default="esp32:esp32:esp32", help="Fully qualified board name")
    build_cmd.add_argument("--port", default=None, help="Upload port (optional)")
    build_cmd.add_argument("--upload", action="store_true", help="Upload after successful compile")
    build_cmd.add_argument("--target", choices=["esp32", "generic"], default="esp32", help="Codegen target backend")
    build_cmd.add_argument("--board", choices=board_choices, default="esp32", help="Hardware profile for semantic checks")

    return parser


def compile_to_cpp(input_path: Path, out_path: Path, target: str = "esp32", board: str = "esp32") -> CompileArtifacts:
    """Runs lexer/parser/semantic/codegen and writes generated C++."""

    resolver = ModuleGraphResolver(default_extension=".myext")
    graph = resolver.resolve(input_path)

    program = _merge_module_programs(graph)

    messages = [
        *_convert_module_graph_issues(graph.issues),
        *_convert_module_errors(graph),
    ]

    semantic = SemanticAnalyzer(board=board)
    semantic_issues = semantic.analyze(program)
    messages.extend(_convert_semantic_issues(input_path, semantic_issues))

    if any(msg.severity == "error" for msg in messages):
        return CompileArtifacts(
            source_path=input_path,
            generated_cpp_path=out_path,
            messages=messages,
            line_map={},
            target=target,
            board=board,
        )

    generator = create_generator(target)
    try:
        generated = generator.generate(program)
    except CodegenError as exc:
        span = exc.span or SourceSpan(str(input_path), 1, 1, 1, 1)
        messages.append(
            CompilerMessage(
                stage="codegen",
                severity="error",
                message=str(exc),
                line=span.start_line,
                column=span.start_col,
                file_path=span.file_path,
            )
        )
        return CompileArtifacts(
            source_path=input_path,
            generated_cpp_path=out_path,
            messages=messages,
            line_map={},
            target=target,
            board=board,
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(generated.code, encoding="utf-8")
    return CompileArtifacts(
        source_path=input_path,
        generated_cpp_path=out_path,
        messages=messages,
        line_map=generated.line_map,
        target=target,
        board=board,
    )


def _convert_lex_errors(path: Path, errors: Sequence[LexError]) -> List[CompilerMessage]:
    return [
        CompilerMessage("lex", "error", err.message, err.line, err.column, str(path))
        for err in errors
    ]


def _convert_parse_errors(path: Path, errors: Sequence[ParseError]) -> List[CompilerMessage]:
    return [
        CompilerMessage("parse", "error", err.message, err.line, err.column, str(path))
        for err in errors
    ]


def _convert_semantic_issues(path: Path, issues: Sequence[SemanticIssue]) -> List[CompilerMessage]:
    return [
        CompilerMessage(
            "semantic",
            issue.severity,
            issue.message,
            issue.line,
            issue.column,
            issue.file_path or str(path),
        )
        for issue in issues
    ]


def _convert_module_graph_issues(issues: Sequence[ModuleIssue]) -> List[CompilerMessage]:
    return [
        CompilerMessage(
            stage="module",
            severity=issue.severity,
            message=issue.message,
            line=issue.line,
            column=issue.column,
            file_path=issue.file_path,
        )
        for issue in issues
    ]


def _convert_module_errors(graph: ModuleGraph) -> List[CompilerMessage]:
    messages: List[CompilerMessage] = []
    for module_path, unit in graph.modules.items():
        messages.extend(_convert_lex_errors(module_path, unit.lex_errors))
        messages.extend(_convert_parse_errors(module_path, unit.parse_errors))
    return messages


def _merge_module_programs(graph: ModuleGraph) -> Program:
    declarations = []
    for module_path in graph.topo_order:
        unit = graph.modules[module_path]
        for decl in unit.program.declarations:
            if not isinstance(decl, ImportDecl):
                declarations.append(decl)

    if graph.entrypoint in graph.modules:
        span = graph.modules[graph.entrypoint].program.span
    else:
        span = SourceSpan(str(graph.entrypoint), 1, 1, 1, 1)
    return Program(span=span, declarations=declarations)


def print_messages(messages: Iterable[CompilerMessage]) -> None:
    """Print human-friendly diagnostics."""

    for msg in messages:
        print(
            f"[{msg.stage}:{msg.severity}] {msg.file_path}:{msg.line}:{msg.column} {msg.message}",
            file=sys.stderr if msg.severity == "error" else sys.stdout,
        )


def run_arduino_cli_compile(source_cpp: Path, fqbn: str, line_map: Dict[int, SourceMapEntry]) -> int:
    """Compile generated C++ using arduino-cli."""

    sketch_dir = materialize_arduino_sketch(source_cpp)

    cmd = [
        "arduino-cli",
        "compile",
        "--fqbn",
        fqbn,
        "--format",
        "json",
        str(sketch_dir),
    ]
    return _run_cli_with_json_diagnostics(cmd, line_map, sketch_dir)


def run_arduino_cli_upload(source_cpp: Path, fqbn: str, port: str, line_map: Dict[int, SourceMapEntry]) -> int:
    """Upload generated project using arduino-cli."""

    sketch_dir = materialize_arduino_sketch(source_cpp)

    cmd = [
        "arduino-cli",
        "upload",
        "--fqbn",
        fqbn,
        "--port",
        port,
        "--format",
        "json",
        str(sketch_dir),
    ]
    return _run_cli_with_json_diagnostics(cmd, line_map, sketch_dir)


def materialize_arduino_sketch(source_cpp: Path) -> Path:
    """Create an Arduino sketch directory with an .ino file from generated C++."""

    source_cpp = source_cpp.resolve()
    sketch_dir = source_cpp.parent / f"{source_cpp.stem}_sketch"
    sketch_dir.mkdir(parents=True, exist_ok=True)

    ino_path = sketch_dir / f"{sketch_dir.name}.ino"
    ino_path.write_text(source_cpp.read_text(encoding="utf-8"), encoding="utf-8")
    return sketch_dir


def _run_cli_with_json_diagnostics(
    cmd: Sequence[str],
    line_map: Dict[int, SourceMapEntry],
    sketch_dir: Path,
) -> int:
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        print(
            "[arduino-cli:error] 'arduino-cli' executable not found. Install Arduino CLI and ensure it is on PATH.",
            file=sys.stderr,
        )
        return 127

    def _print_stream(raw: str) -> None:
        for line in raw.splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                if line.strip():
                    _print_mapped_text(line, line_map, sketch_dir)
                continue

            if isinstance(payload, dict):
                message = payload.get("message") or payload.get("error") or str(payload)
                level = payload.get("level", "info")
            else:
                message = str(payload)
                level = "info"
            prefix = "error" if level in {"error", "fatal"} else "info"
            printed = _print_mapped_text(message, line_map, sketch_dir, prefix)
            if not printed:
                print(f"[arduino-cli:{prefix}] {message}")

    _print_stream(completed.stdout)
    _print_stream(completed.stderr)
    return completed.returncode


def _print_mapped_text(
    text: str,
    line_map: Dict[int, SourceMapEntry],
    sketch_dir: Path,
    level: Optional[str] = None,
) -> bool:
    pattern = re.compile(r"(?P<path>[A-Za-z]:[^:\n]+|[^:\n]+\.ino):(?P<line>\d+):(?P<col>\d+):\s*(?P<kind>error|warning):\s*(?P<msg>.*)")
    match = pattern.search(text)
    if match is None:
        return False

    source_path = Path(match.group("path")).resolve()
    try:
        source_path.relative_to(sketch_dir.resolve())
    except ValueError:
        if source_path.suffix != ".ino":
            return False

    gen_line = int(match.group("line"))
    gen_col = int(match.group("col"))
    kind = match.group("kind")
    message = match.group("msg")

    mapped = line_map.get(gen_line)
    if mapped is None:
        return False

    effective_level = level or kind
    print(
        f"[dsl-compile:{effective_level}] {mapped.file_path}:{mapped.line}:{mapped.column} {message}"
        f" (generated:{gen_line}:{gen_col})"
    )
    return True


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.command == "check":
        artifacts = compile_to_cpp(args.input, Path("build/main.cpp"), target=args.target, board=args.board)
        print_messages(artifacts.messages)
        return 1 if any(m.severity == "error" for m in artifacts.messages) else 0

    if args.command == "transpile":
        artifacts = compile_to_cpp(args.input, args.out, target=args.target, board=args.board)
        print_messages(artifacts.messages)
        if any(m.severity == "error" for m in artifacts.messages):
            return 1
        print(f"Generated C++: {artifacts.generated_cpp_path} (target={artifacts.target}, board={artifacts.board})")
        return 0

    if args.command == "build":
        artifacts = compile_to_cpp(args.input, args.out, target=args.target, board=args.board)
        print_messages(artifacts.messages)
        if any(m.severity == "error" for m in artifacts.messages):
            return 1

        result = run_arduino_cli_compile(artifacts.generated_cpp_path, args.fqbn, artifacts.line_map)
        if result != 0:
            return result

        if args.upload:
            if not args.port:
                print("--upload requires --port", file=sys.stderr)
                return 2
            result = run_arduino_cli_upload(artifacts.generated_cpp_path, args.fqbn, args.port, artifacts.line_map)
            if result != 0:
                return result

        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
