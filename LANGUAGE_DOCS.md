# NOVA DSL Language Reference (Official)

This is the complete reference for NOVA syntax and behavior, aligned with the final AST, parser, semantic analyzer, and code generation pipeline.

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
- `void` (return type only)

## Literals

- Integer: `123`
- Float: `3.14`
- Boolean: `true`, `false`
- String: `"hello"`

## Assignment expression

```nova
x = 10;
x = x + 1;
```

Rules:
- Left side must be an identifier.
- Assignment is type-checked.

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

## 4) Board Profiles and CLI Usage

NOVA semantic checks are board-aware through `--board`.

Supported boards:
- `esp32` (default)
- `esp32s3_n16r8`

Example checks/builds:

```powershell
python cli.py check blink.myext --target esp32 --board esp32s3_n16r8
python cli.py build blink.myext --target esp32 --board esp32s3_n16r8 --fqbn esp32:esp32:esp32s3 --upload --port COM6
```

`esp32s3_n16r8` profile notes:
- Allows GPIO range up to 48.
- Reserves PSRAM pins 33–37 (disallowed for user IO).

---

## 5) Fully Working Blink Example (`rgbWrite`)

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

## 6) Additional Syntax Notes

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
