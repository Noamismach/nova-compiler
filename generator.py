from parser import ASTNode, ProgramNode, PinDeclNode, LoopNode, MethodCallNode, SleepNode

class CppCodeGenerator:
    def __init__(self):
        self.includes = ["#include <Arduino.h>"]
        self.globals = []
        self.setup_body = []
        self.loop_body = []
        self.pin_state_vars = []

    def generate(self, node: ProgramNode) -> str:
        for stmt in node.statements:
            self.visit(stmt)

        code = "\n".join(self.includes) + "\n\n"
        
        if self.globals or self.pin_state_vars:
            code += "// Global Pin Definitions and State Tracking\n"
            code += "\n".join(self.globals + self.pin_state_vars) + "\n\n"

        code += "void setup() {\n"
        if self.setup_body:
            code += "  " + "\n  ".join(self.setup_body) + "\n"
        code += "}\n\n"

        code += "void loop() {\n"
        if self.loop_body:
            code += "  " + "\n  ".join(self.loop_body) + "\n"
        code += "}\n"

        return code

    def visit(self, node: ASTNode):
        method_name = f'visit_{type(node).__name__}'
        visitor = getattr(self, method_name, self.generic_visit)
        return visitor(node)

    def generic_visit(self, node):
        raise Exception(f"Compiler Error: No visit_{type(node).__name__} method defined.")

    def visit_PinDeclNode(self, node: PinDeclNode):
        self.globals.append(f"const uint8_t {node.name}_pin = {node.pin_num};")
        self.pin_state_vars.append(f"bool {node.name}_state = false;")
        
        mode_str = "OUTPUT" if node.mode == "out" else "INPUT"
        self.setup_body.append(f"pinMode({node.name}_pin, {mode_str});")

    def visit_LoopNode(self, node: LoopNode):
        for stmt in node.body:
            self.loop_body.append(self.visit(stmt))

    def visit_MethodCallNode(self, node: MethodCallNode) -> str:
        if node.method_name == "toggle":
            return (f"{node.object_name}_state = !{node.object_name}_state;\n"
                    f"  if ({node.object_name}_state) {{\n"
                    f"    GPIO.out_w1ts = ((uint32_t)1 << {node.object_name}_pin);\n"
                    f"  }} else {{\n"
                    f"    GPIO.out_w1tc = ((uint32_t)1 << {node.object_name}_pin);\n"
                    f"  }}")

    def visit_SleepNode(self, node: SleepNode) -> str:
        return f"vTaskDelay({node.duration_ms} / portTICK_PERIOD_MS);"