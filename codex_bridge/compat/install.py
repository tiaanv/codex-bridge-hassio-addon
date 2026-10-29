"""Apply only the two Ollama response adapters to the pinned source."""
import ast
from pathlib import Path
import sys


def patch(source):
    tree = ast.parse(source)
    targets = {"_convert_openai_to_ollama_stream": "convert_stream", "_convert_openai_to_ollama_response": "convert_response"}
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in targets]
    if len(nodes) != len(targets):
        raise ValueError("Pinned GPTMock adapter layout changed; refusing to patch")
    lines = source.splitlines(keepends=True)
    for node in sorted(nodes, key=lambda n: n.lineno, reverse=True):
        lines[node.lineno - 1:node.end_lineno] = [f"from gptmock.services.bridge_ollama_tools import {targets[node.name]} as {node.name}\n"]
    result = "".join(lines)
    compile(result, "ollama.py", "exec")
    return result


if __name__ == "__main__":
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text()))
