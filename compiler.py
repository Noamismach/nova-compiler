"""Core compiler facade for NOVA build/check workflows.

This module provides a stable import surface for tooling that needs the NOVA
compile pipeline without coupling to CLI command handling.
"""

from __future__ import annotations

from pathlib import Path

from cli import CompileArtifacts, compile_to_cpp


def compile_program(
    input_path: Path,
    out_path: Path,
    target: str = "esp32",
    board: str = "esp32",
) -> CompileArtifacts:
    """Compile a NOVA program to generated C++ artifacts.

    Args:
        input_path: Path to NOVA entrypoint source.
        out_path: Destination path for generated C++ translation unit.
        target: Backend target name (for example `esp32` or `generic`).
        board: Hardware profile used by semantic analysis.

    Returns:
        CompileArtifacts containing diagnostics and generated output metadata.
    """

    return compile_to_cpp(input_path=input_path, out_path=out_path, target=target, board=board)
