# Contributing to NOVA

Thanks for your interest in contributing to NOVA! 🚀

This guide explains how to set up your environment, work on DSL/compiler features, and submit high-quality Pull Requests.

## 1) Development Setup

## Prerequisites

- Python 3.x
- Arduino CLI (for build/upload workflows)
- VS Code (recommended)

## Local setup

```powershell
git clone https://github.com/Noamismach/nova-compiler.git
cd nova-compiler
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Optional Arduino setup:

```powershell
arduino-cli core update-index
arduino-cli core install esp32:esp32
```

---

## 2) Project Areas

- `lexer.py` — tokenization
- `parser.py` — AST construction
- `semantic.py` — type + board-aware hardware checks
- `codegen.py` — target backend generation
- `cli.py` — command flow and diagnostics
- `LANGUAGE_DOCS.md` + `DSL_GRAMMAR.ebnf` — language specification

When adding language features, update **all relevant layers**:

1. Grammar (`DSL_GRAMMAR.ebnf`)
2. Lexer tokenization
3. AST node definitions
4. Parser rules
5. Semantic checks
6. Code generation
7. Documentation

---

## 3) Working with DSL Changes

Before opening a PR for DSL/compiler logic:

- Add or update example `.myext` source demonstrating the change.
- Run semantic checks and transpilation paths for affected targets.
- Ensure unsupported-target behavior is explicit and user-friendly.

Suggested commands:

```powershell
python cli.py check .\blink.myext --target esp32 --board esp32s3_n16r8
python cli.py transpile .\blink.myext --target esp32 --board esp32s3_n16r8 --out .\build\blink.cpp
python cli.py build .\blink.myext --target esp32 --board esp32s3_n16r8 --fqbn esp32:esp32:esp32s3
```

---

## 4) Coding Standards

- Keep changes focused and minimal.
- Prefer clear names over short/ambiguous names.
- Add docstrings for new key classes/functions.
- Preserve existing architecture patterns (frontend → semantic → backend).
- Do not mix unrelated refactors in feature PRs.

---

## 5) Pull Request Process

1. Fork the repository.
2. Create a feature branch:
   - `feature/<short-name>` or `fix/<short-name>`
3. Commit with clear messages.
4. Push to your fork.
5. Open a Pull Request against `main`.

Include in your PR description:

- **What changed**
- **Why it changed**
- **How it was validated** (commands/results)
- **Any compatibility notes** (target/board behavior)

---

## 6) Issue Reporting

When filing an issue, please include:

- NOVA command used
- Input `.myext` snippet
- `--target` and `--board` values
- Full diagnostic output
- Environment notes (OS, Python, Arduino CLI version)

---

## 7) Community Guidelines

- Be respectful and constructive.
- Assume good intent.
- Focus discussions on actionable technical outcomes.

Thanks for helping make NOVA better 💙
