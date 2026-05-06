import pytest
import ast
from pathlib import Path

def test_orchestrator_sse_event_schema():
    """
    Statically analyzes the orchestrator to ensure every yielded dictionary 
    strictly follows the SSE schema required by the frontend:
    { "event": "<event_type>", "data": <payload> }
    """
    orchestrator_path = Path("api/services/repair/orchestrator.py")
    tree = ast.parse(orchestrator_path.read_text(encoding="utf-8"))
    
    for node in ast.walk(tree):
        if isinstance(node, ast.Yield) and isinstance(node.value, ast.Dict):
            # Extract the keys from the yielded dictionary
            keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
            
            # Every yield must have 'event' and 'data'
            assert "event" in keys, f"Malformed SSE yield at line {node.lineno}: missing 'event' key. Keys found: {keys}"
            assert "data" in keys, f"Malformed SSE yield at line {node.lineno}: missing 'data' key. Keys found: {keys}"
            
            # The event type should be a string
            event_val_idx = keys.index("event")
            event_val_node = node.value.values[event_val_idx]
            assert isinstance(event_val_node, ast.Constant) and isinstance(event_val_node.value, str), \
                f"SSE 'event' value must be a string literal at line {node.lineno}"
