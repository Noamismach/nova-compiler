# NOVA DSL Language Reference (Official)

This is the complete reference for NOVA syntax and behavior, aligned with the final AST, parser, semantic analyzer, and code generation pipeline.

## NOVA 2.0 Feature Set

This reference includes NOVA 2.0 capabilities:
- Multi-file import graph via `import "path";`
- Struct declarations, struct initialization, and member access
- Pattern dispatch via `match (...) { ... }` with wildcard arm requirement
- Value-producing `if` expressions
- Task declarations with decorators, plus `spawn`
- Declarative `bus` and `device` blocks for hardware wiring intent
- Explicit cast expressions via `as`
- Raw backend passthrough blocks via `unsafe { ... }`
- Native networking modules for Wi-Fi and HTTP serving (`wifi.myext`, `http.myext`)
- Native cryptography module for SHA-256 hashing (`crypto.myext`) via ESP-IDF `mbedtls`
- Live serial monitor workflow via `cli.py monitor`

## 1) Variables & Types

## Variable declarations (exact)

```nova
let name;
let name = expression;
let name: type;
let name: type = expression;
```

Rules:
- `let` is required.
- `;` is required.
- Type annotation is optional.
- If both declared type and initializer exist, assignment compatibility is validated.

## Supported primitive types

- `int`
- `float`
- `bool`
- `string`
- `Pin`
- `Duration`
- `void` (return type only)

## Literals

- Integer: `123`
- Float: `3.14`
- Boolean: `true`, `false`
- String: `"hello"`
- Duration: `10ms`, `250us`, `1s`

## Assignment expression

```nova
x = 10;
x = x + 1;
```

Rules:
- Left side must be an identifier.
- Assignment is type-checked.

Compound assignment and postfix update are supported:
- `+=`, `-=`, `*=`, `/=`
- `x++`, `x--`

## Explicit cast

```nova
let x:int = 3;
let y:float = x as float;
```

Rules:
- `as` currently supports primitive casts among `int`, `float`, `bool`, and `string`.

---

## 2) Control Flow

All blocks use `{ ... }`.

## `if` / `else` (exact)

```nova
if (condition) {
    // statements
}

if (condition) {
    // statements
} else {
    // statements
}
```

Rules:
- Parenthesized condition is required.
- `else` must be followed by a block.
- Condition must evaluate to `bool`.

## `if` expression (value form)

```nova
let x:int = if (flag) {
    1
} else {
    2
};
```

Rules:
- Both branches must produce a value.
- Branch result types must match.

## `while` (exact)

```nova
while (condition) {
    // statements
}
```

Rules:
- Parenthesized condition is required.
- Condition must evaluate to `bool`.

## `for` (exact)

```nova
for (initializer; condition; update) {
    // statements
}
```

Supported initializer forms:

```nova
for (let i:int = 0; i < 10; i = i + 1) {
    // statements
}

for (i = 0; i < 10; i = i + 1) {
    // statements
}

for (; i < 10; i = i + 1) {
    // statements
}
```

Rules:
- Clause separators (`; ;`) are mandatory.
- Condition, when present, must be `bool`.

## `loop` (exact)

```nova
loop {
    // statements
}
```

Semantics:
- `loop { ... }` maps to Arduino `loop()` body.
- Top-level executable statements outside `loop` map to Arduino `setup()`.

## `match` statement

```nova
match (state) {
    0 => { digitalWrite(2, 0); }
    1 => { digitalWrite(2, 1); }
    _ => { digitalWrite(2, 0); }
}
```

Rules:
- Each arm uses `pattern => { ... }`.
- `_` is the wildcard arm.
- Wildcard arm is required for exhaustiveness.

---

## 3) Hardware APIs (Exact Syntax)

These names are reserved tokens in the lexer/parser.

## `gpioMode`

```nova
gpioMode(pinExpression, out);
gpioMode(pinExpression, in);
```

Rules:
- Second argument is keyword token `out` or `in` (not a string).
- Pin expression must be `int`.

## `digitalWrite`

```nova
digitalWrite(pinExpression, valueExpression);
```

Rules:
- Pin expression must be `int`.
- Value expression must be numeric/bool (`int`, `float`, `bool` accepted by semantic check).

## `analogRead`

`analogRead` is an expression:

```nova
let reading:int = analogRead(pinExpression);
```

Rules:
- Pin expression must be `int`.
- Return type is `int`.

## `pwmWrite`

```nova
pwmWrite(pinExpression, dutyExpression);
pwmWrite(pinExpression, dutyExpression, channelExpression);
```

Rules:
- Pin expression must be `int`.
- Duty expression must be numeric.
- Optional third argument (`channelExpression`) must be numeric.

## `rgbWrite`

```nova
rgbWrite(pinExpression, redExpression, greenExpression, blueExpression);
```

Rules:
- Pin expression must be `int`.
- `red`, `green`, and `blue` expressions must be numeric.
- On `--target esp32`, this lowers to `neopixelWrite(pin, r, g, b);`.
- On unsupported targets (e.g., `--target generic`), transpilation fails with a clear codegen error.

## `delay`

```nova
delay(millisecondsExpression);
```

Rules:
- Argument must be numeric (integer milliseconds recommended).

---

## 4) Structs

## Declaration

```nova
struct Sensor {
    id: int;
    threshold: float;
    enabled: bool;
}
```

`let` before struct fields is optional and accepted.

## Initialization and member access

```nova
let s:Sensor = Sensor(id: 1, threshold: 0.8, enabled: true);
let en:bool = s.enabled;
```

Rules:
- Initializers are named (`field: value`).
- All required fields must be provided.
- Unknown or duplicate fields are rejected.

---

## 5) Tasks and Declarative Buses

## Task declaration and spawn

```nova
@core(1)
@rate(10ms)
task blinkTask() {
    digitalWrite(2, 1);
    delay(10ms);
}

spawn blinkTask();
```

Rules:
- `@core` must evaluate to `0` or `1` (ESP32 dual-core pinning model).
- `@rate` expects `Duration` or `int`.
- Spawn target must be a declared task.

## Bus and device declarations

```nova
bus I2C sensors {
    sda: 8;
    scl: 9;
    freq: 400k;

    device imu {
        address: 0x68;
    }
}
```

Rules:
- Supported bus types: `I2C`, `SPI`.
- `sda`, `scl`, and `freq` are required bus properties.
- Reserved board pins are rejected during semantic analysis.

---

## 6) Modules and Unsafe Blocks

## Imports

```nova
import "drivers/blink";
```

Rules:
- Imports are resolved through the module graph.
- Declarations are merged in dependency topological order.

## Unsafe block

```nova
unsafe {
    // Raw target C++ emitted verbatim in backend output
}
```

Use unsafe blocks for tightly scoped backend-specific escapes when no DSL construct exists.

---

## 7) Phase 2 Web Layer (Native Networking)

NOVA Phase 2 ships a standard networking layer for ESP32-class targets.

### Wi-Fi module

- `wifi.myext` defines `WiFiConfig` and `connectWiFi(cfg: WiFiConfig)`.
- `connectWiFi` blocks until `WL_CONNECTED` to guarantee networking readiness before dependent services start.

### HTTP server module

- `http.myext` provides `configureWebServer(port, htmlPayload)` and task `startWebServer()`.
- Server startup is race-safe: the task waits for `WiFi.status() == WL_CONNECTED` before calling `begin()`.
- `WebServer` is heap-allocated to avoid stack pressure inside FreeRTOS task contexts.

### Code generation behavior for networking

- Header includes are emitted at global scope.
- Codegen infers required includes from the AST/unsafe payload and injects `WiFi.h`, `WebServer.h`, and `Wire.h` only when needed.

---

## 8) Phase 3 Hardware Cryptography

NOVA Phase 3 adds a native cryptography layer for ESP32-class targets.

### Crypto module

- `crypto.myext` provides `hashSha256(payload: string)`.
- The current V1 implementation prints the 64-character lowercase hexadecimal digest via `Serial.println(...)`.

### Runtime backend behavior

- The SHA-256 flow uses `mbedtls_md_context_t` with `mbedtls_md_starts`, `mbedtls_md_update`, and `mbedtls_md_finish`.
- On ESP32-S3 targets, ESP-IDF's `mbedtls` integration can route digest operations through hardware cryptographic accelerators.

### Code generation behavior for cryptography

- Header includes are emitted at global scope.
- Codegen injects `mbedtls/md.h` when cryptography usage is inferred from AST symbols or unsafe payload markers.

---

## 9) Board Profiles and CLI Usage

NOVA semantic checks are board-aware through `--board`.

Supported boards:
- `esp32` (default)
- `esp32s3_n16r8`

Example checks/builds:

```powershell
python cli.py check blink.myext --target esp32 --board esp32s3_n16r8
python cli.py build blink.myext --target esp32 --board esp32s3_n16r8 --fqbn esp32:esp32:esp32s3 --upload --port COM6
python cli.py monitor --port COM6 --baud 115200
```

`esp32s3_n16r8` profile notes:
- Allows GPIO range up to 48.
- Reserves PSRAM pins 33–37 (disallowed for user IO).

---

## 9) Fully Working Blink Example (`rgbWrite`)

```nova
let PIXEL_PIN:int = 48;

gpioMode(PIXEL_PIN, out);

loop {
    rgbWrite(PIXEL_PIN, 32, 0, 0);
    delay(500);

    rgbWrite(PIXEL_PIN, 0, 0, 0);
    delay(500);
}
```

Build/upload example:

```powershell
python cli.py build blink.myext --target esp32 --board esp32s3_n16r8 --fqbn esp32:esp32:esp32s3 --upload --port COM6
```

---

## 10) Additional Syntax Notes

- Statements generally end with `;`.
- Block syntax is always `{ ... }`.
- Function declarations:

```nova
fn name(arg:type, other:type) -> returnType {
    // body
}
```

- Return statements:

```nova
return;
return expression;
```

- Comments supported by lexer:
  - Line: `// ...`
  - Block: `/* ... */`

---

## 11) Tooling Integration

- Official VS Code extension assets are maintained in `nova-vscode/`.
- The extension ships syntax grammar and language configuration aligned with this language reference.
