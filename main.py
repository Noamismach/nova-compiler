from lexer import Lexer

def main():
    source_code = """
    pin led = Pin(2, out)
    loop{
        led.toggle()
        sleep(1s)
    }
    """
    print("=== Nova Compiler ===")
    print("Reading source code...\n")

    my_lexer = Lexer(source_code)
    tokens = my_lexer.tokenize()

    print("Generated Tokens:")
    for tok in tokens:
        print(f"[{tok.line}:{tok.column}] {tok.type.name} -> '{tok.value}'")

if __name__ == "__main__":
    main()
          
