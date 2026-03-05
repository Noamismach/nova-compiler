# NOVA

NOVA is a secure embedded domain-specific language (DSL) and compiler for ESP32-class systems.
It converts `.myext` programs into Arduino-compatible C++ while enforcing board-aware semantic safety before firmware is built.

## Why NOVA

- Security-first embedded authoring with explicit `unsafe` boundaries.
- Board-aware semantic validation to catch hardware misuse early.
- Fast iteration loop from language source to flashable firmware.
- Native standard library modules for networking and cryptography.

## NOVA V2.0 Capabilities

### Concurrency and Runtime

- Native FreeRTOS task generation via `task`, `@core(...)`, `@rate(...)`, and `spawn`.
- Deterministic lowering of task entrypoints with pinned-core execution support.

### Web Layer (Phase 2)

- `wifi.myext` provides typed station onboarding through `WiFiConfig` and `connectWiFi(...)`.
- `http.myext` provides `configureWebServer(...)` and `startWebServer()` task flow.
- Codegen auto-injects required global headers when web symbols are detected.

### Crypto Layer (Phase 3)

- `crypto.myext` provides `hashSha256(payload: string)`.
- SHA-256 is implemented through ESP-IDF `mbedtls` digest APIs.
- On ESP32-S3, the `mbedtls` path can leverage hardware crypto acceleration when available.
- Codegen auto-injects `#include <mbedtls/md.h>` from AST and unsafe-block inference.

### Language Tooling

- Official VS Code extension included in `nova-vscode/`.
- Syntax grammar and language configuration are bundled for editor support.

## Repository Layout

- `lexer.py`: tokenization and lexical diagnostics.
- `parser.py`: recursive descent parser and AST construction.
- `ast_nodes.py`: typed syntax model used by all compiler phases.
- `semantic.py`: type and board-profile validation.
- `codegen.py`: target-specific Arduino C++ emitters.
- `cli.py`: end-user commands (`check`, `transpile`, `build`, `monitor`).
- `compiler.py`: programmatic facade over the compile pipeline.
- `wifi.myext`, `http.myext`, `crypto.myext`: standard library modules.

## Quick Start

1. Create and activate a virtual environment.
2. Install dependencies from `requirements.txt`.
3. Run a semantic check:
   - `python cli.py check blink.myext --target esp32 --board esp32s3_n16r8`
4. Build and upload:
   - `python cli.py build blink.myext --target esp32 --board esp32s3_n16r8 --fqbn esp32:esp32:esp32s3 --upload --port COM6`

## CLI Commands

- `python cli.py check <input.myext> [--target ...] [--board ...]`
- `python cli.py transpile <input.myext> [--out ...] [--target ...] [--board ...]`
- `python cli.py build <input.myext> --fqbn <fqbn> [--upload --port <port>] [--target ...] [--board ...]`
- `python cli.py monitor --port <port> [--baud 115200]`

## Safety Model

NOVA keeps architecture-specific escape hatches explicit. Raw C++ can only enter through `unsafe { ... }` blocks, while regular DSL flows remain type-checked and hardware-profile validated.

## License

MIT License. See `LICENSE`.
