# NOVA Language Reference

This document defines NOVA syntax and behavior for V2.0, including standard library networking and cryptography modules.

## 1. Core Model

NOVA compiles `.myext` sources into Arduino-compatible C++.
Compilation flow:
- Lexing and parsing into typed AST nodes.
- Semantic validation with board profiles.
- Target-specific code generation.

`unsafe { ... }` is the explicit escape hatch for raw backend C++.

## 2. Program Structure

Top-level declarations can include:
- `import "module.myext";`
- `struct` declarations
- `fn` functions
- `task` declarations (with optional decorators)
- `bus` declarations
- global `let` declarations
- `loop { ... }` block

Top-level executable statements outside `loop` are lowered into `setup()`.

## 3. Types and Variables

Primitive types:
- `int`
- `float`
- `bool`
- `string`
- `Pin`
- `Duration`
- `void` (return positions)

Variable forms:
- `let x;`
- `let x = expr;`
- `let x: type;`
- `let x: type = expr;`

## 4. Control Flow

Supported statements and expressions:
- `if (...) { ... } else { ... }`
- value-producing `if` expressions
- `while (...) { ... }`
- `for (init; cond; update) { ... }`
- `match (...) { ... }` with required wildcard arm `_`
- `return ...;`

## 5. Tasks and Scheduling

Task syntax:
- `task name() { ... }`
- decorators: `@core(...)`, `@rate(...)`
- launch via `spawn taskName();`

Codegen lowers tasks to FreeRTOS entrypoints and uses `xTaskCreatePinnedToCore(...)`.
A conservative stack size is reserved to reduce runtime instability for networking and TLS-heavy tasks.

## 6. Hardware and Built-ins

Built-in hardware primitives include:
- `gpioMode(pin, out|in);`
- `digitalWrite(pin, value);`
- `pwmWrite(pin, duty[, channel]);`
- `rgbWrite(pin, r, g, b);`
- `wifiConnect(ssid, password);`
- `delay(ms_or_duration);`

## 7. Standard Library Modules

### 7.1 `wifi.myext`

- `struct WiFiConfig { ssid: string; password: string; }`
- `fn connectWiFi(cfg: WiFiConfig) -> void`

Behavior:
- Initializes Serial for operational logging.
- Calls `WiFi.begin(...)`.
- Blocks until `WL_CONNECTED`.

### 7.2 `http.myext`

- `fn configureWebServer(port: int, htmlPayload: string) -> void`
- `task startWebServer()`

Behavior:
- Waits for Wi-Fi readiness.
- Starts `WebServer` on configured port.
- Handles client requests in a cooperative loop.

### 7.3 `crypto.myext`

- `fn hashSha256(payload: string) -> void`

Behavior:
- Uses `mbedtls_md_*` SHA-256 flow.
- Produces a 32-byte digest.
- Prints lowercase hexadecimal hash to Serial.

## 8. Unsafe Block Contract

`unsafe` blocks are intended for tightly scoped backend integration points.
Guidelines:
- Keep raw C++ minimal and focused.
- Avoid broad application logic inside unsafe sections when DSL constructs exist.
- Prefer stable APIs from Arduino/ESP-IDF wrappers.

## 9. Auto-Include Logic

NOVA codegen injects required C++ headers at global scope based on AST and unsafe payload inspection.

Detected examples:
- Wi-Fi usage: `#include <WiFi.h>`
- HTTP server usage: `#include <WebServer.h>`
- I2C usage: `#include <Wire.h>`
- Crypto usage: `#include <mbedtls/md.h>`

This keeps generated units deterministic and avoids putting preprocessor directives directly inside unsafe payloads.

## 10. CLI Workflows

- `python cli.py check app.myext --target esp32 --board esp32s3_n16r8`
- `python cli.py transpile app.myext --out build/main.cpp --target esp32 --board esp32s3_n16r8`
- `python cli.py build app.myext --target esp32 --board esp32s3_n16r8 --fqbn esp32:esp32:esp32s3 --upload --port COM6`
- `python cli.py monitor --port COM6 --baud 115200`

## 11. Board Profiles

Current semantic profiles include:
- `esp32`
- `esp32s3_n16r8`

Board profile selection influences pin/peripheral validation during semantic analysis.
