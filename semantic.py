from parser import ASTNode, ProgramNode, PinDeclNode, LoopNode, MethodCallNode, SleepNode

class SemanticAnalyzer:
    INPUT_ONLY_PINS = (34, 35, 36, 39)
    STRAPPING_PINS = {0, 2, 4, 5, 12, 15}

    def __init__(self):
        self.symbol_table = {}

    def analyze(self, node: ASTNode):
        
        if isinstance(node, ProgramNode):
            for stmt in node.statements:
                self.analyze(stmt)
                
        elif isinstance(node, PinDeclNode):
            if node.pin_num in self.INPUT_ONLY_PINS and node.mode == "out":
                raise ValueError(
                    f"Hardware Error: ESP32 GPIO {node.pin_num} is an input-only "
                    "pin and physically cannot be set to 'out' mode."
                )
            
            if node.pin_num in self.STRAPPING_PINS:
                print(
                    f"Warning: GPIO {node.pin_num} is a strapping pin. Ensure external "
                    "circuitry does not pull it high/low during boot, or the ESP32 may hang."
                )
                
            if node.name in self.symbol_table:
                raise NameError(f"Semantic Error: Pin '{node.name}' is already defined.")
            
            self.symbol_table[node.name] = node
            
        elif isinstance(node, MethodCallNode):
            if node.object_name not in self.symbol_table:
                raise NameError(f"Semantic Error: Undefined pin reference '{node.object_name}'.")
            
            if node.method_name != "toggle":
                raise AttributeError(
                    f"Semantic Error: Method '{node.method_name}' is not supported on Pin objects."
                )
                
        elif isinstance(node, LoopNode):
            for stmt in node.body:
                self.analyze(stmt)