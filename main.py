import argparse
import subprocess
import tempfile
import os
import json
import sys

from lexer import Lexer
from parser import Parser
from semantic import SemanticAnalyzer
from generator import CppCodeGenerator

def compile_and_flash(source_text: str, port: str):
    try:
        print("Starting Lexical and Syntax Analysis...")
        lexer = Lexer(source_text)
        parser = Parser(lexer.tokenize())
        ast = parser.parse_program()
        
        print("Running Semantic Hardware Validation...")
        SemanticAnalyzer().analyze(ast)
        
        print("Generating Optimized ESP32 C++ Code...")
        cpp_code = CppCodeGenerator().generate(ast)
        
    except (SyntaxError, ValueError, NameError, AttributeError) as e:
        print(f"\nCompilation Aborted.\n{str(e)}")
        sys.exit(1)

    print("\nTranspilation successful! Preparing build environment...")
    with tempfile.TemporaryDirectory() as temp_dir:
        sketch_name = "build"
        sketch_dir = os.path.join(temp_dir, sketch_name)
        os.mkdir(sketch_dir)
        sketch_path = os.path.join(sketch_dir, f"{sketch_name}.ino")
        
        with open(sketch_path, "w") as f:
            f.write(cpp_code)
            
        fqbn = "esp32:esp32:esp32"
        print(f"Invoking Xtensa toolchain for {fqbn}...")
        
        compile_cmd = [
            "arduino-cli", "compile",
            "--fqbn", fqbn,
            "--format", "json",
            sketch_dir
        ]
        
        try:
            result = subprocess.run(compile_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print("\nC++ Compilation Failed:")
                try:
                    err_data = json.loads(result.stdout)
                    print(err_data.get('compiler_out', result.stderr))
                except json.JSONDecodeError:
                    print(result.stderr)
                sys.exit(1)
                
            print("Compilation complete. Flashing binary to ESP32...")
            
            upload_cmd = [
                "arduino-cli", "upload",
                "-p", port,
                "--fqbn", fqbn,
                sketch_dir
            ]
            
            upload_result = subprocess.run(upload_cmd, capture_output=True, text=True)
            if upload_result.returncode == 0:
                print("\nSUCCESS: Firmware successfully flashed to ESP32! 🚀")
            else:
                print("\nFlashing Failed. Verify port connection and boot-mode.")
                sys.exit(1)
                
        except FileNotFoundError:
            print("\n[!] SUCCESS (Partial): Transpilation to C++ completed perfectly.")
            print("[!] However, 'arduino-cli' is not installed on this computer, so compilation to machine code was skipped.")
            print("\nHere is your generated C++ code:")
            print("=========================================")
            print(cpp_code)
            print("=========================================")

if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(description="Nova - ESP32 DSL Transpiler")
    arg_parser.add_argument("file", help="Source file containing Nova DSL code")
    arg_parser.add_argument("--port", required=True, help="Serial port (e.g., COM3 or /dev/ttyUSB0)")
    
    args = arg_parser.parse_args()
    
    if not os.path.exists(args.file):
        print(f"Error: File '{args.file}' not found.")
        sys.exit(1)
        
    with open(args.file, "r") as src_file:
        source_code = src_file.read()
        
    compile_and_flash(source_code, args.port)