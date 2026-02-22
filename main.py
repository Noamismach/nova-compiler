from lexer import Lexer
from parser import Parser 
import pprint 
def main():
    source_code = """
    pin led = Pin(2, out)
    loop {
        led.toggle()
        sleep(1s)
    }
    """

    print("=== Nova Compiler ===")
    print("Reading source code...\n")
    
    my_lexer = Lexer(source_code)
    tokens = my_lexer.tokenize()
    
    print("--- Lexer Output ---")
    for tok in tokens:
        print(f"[{tok.line}:{tok.column}] {tok.type.name} -> '{tok.value}'")

    print("\n--- Parser Output (AST) ---")
    my_parser = Parser(tokens)
    ast = my_parser.parse_program() 
    
    pprint.pprint(ast)

if __name__ == "__main__":
    main()