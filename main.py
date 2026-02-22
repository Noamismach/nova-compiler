from lexer import Lexer
from parser import Parser
from semantic import SemanticAnalyzer
from generator import CppCodeGenerator 
def main():
    source_code = """
    pin led = Pin(2, out)
    loop {
        led.toggle()
        sleep(1s)
    }
    """

    print("=== Nova Compiler ===")
    
    my_lexer = Lexer(source_code)
    tokens = my_lexer.tokenize()

    my_parser = Parser(tokens)
    ast = my_parser.parse_program()
    
    analyzer = SemanticAnalyzer()
    analyzer.analyze(ast)
    print("Semantic Analysis Passed! Code is safe for ESP32.\n")
    
    print("Generating Optimized ESP32 C++ Code...\n")
    print("================ C++ OUTPUT ================\n")
    
    generator = CppCodeGenerator()
    cpp_code = generator.generate(ast)
    print(cpp_code)
    
    print("\n============================================")

if __name__ == "__main__":
    main()