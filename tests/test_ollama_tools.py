import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("compat", ROOT / "codex_bridge/compat/ollama_tools.py")
compat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compat)


def event(delta=None, finish=None):
    return b'data: ' + json.dumps({"choices": [{"delta": delta or {}, "finish_reason": finish}]}).encode() + b'\n\n'


class Stream:
    def __init__(self, chunks):
        self.chunks, self.closed = chunks, False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closed = True


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def convert(self, chunks):
        stream = Stream(chunks)
        result = [json.loads(chunk) async for chunk in compat.convert_stream(stream, "test")]
        self.assertTrue(stream.closed)
        return result

    async def test_text_and_fragmented_parallel_tools(self):
        chunks = [
            event({"content": "Checking."}),
            event({"tool_calls": [{"index": 1, "function": {"name": "Second", "arguments": '{"area":'}}]}),
            event({"tool_calls": [{"index": 0, "function": {"name": "Get", "arguments": '{"name":'}}]}),
            event({"tool_calls": [{"index": 0, "function": {"name": "State", "arguments": '"Kitchen"}'}}]}),
            event({"tool_calls": [{"index": 1, "function": {"arguments": '"Study"}'}}]}),
            event(finish="tool_calls"), b'data: [DONE]\n\n',
        ]
        # Force every byte boundary, including split Unicode and SSE frames.
        wire = b''.join(chunks)
        result = await self.convert([wire[i:i+1] for i in range(len(wire))])
        self.assertEqual(result[0]["message"]["content"], "Checking.")
        self.assertEqual(result[-1]["message"]["tool_calls"], [
            {"function": {"name": "GetState", "arguments": {"name": "Kitchen"}}},
            {"function": {"name": "Second", "arguments": {"area": "Study"}}},
        ])
        self.assertTrue(result[-1]["done"])
        self.assertEqual(result[-1]["done_reason"], "tool_calls")

    async def test_text_only(self):
        result = await self.convert([event({"content": "Hello"}), event(finish="stop"), b'data: [DONE]\n\n'])
        self.assertEqual(result[0]["message"]["content"], "Hello")
        self.assertNotIn("tool_calls", result[-1]["message"])

    async def test_tool_only(self):
        result = await self.convert([event({"tool_calls": [{"index": 0, "function": {"name": "GetState", "arguments": "{}"}}]}), event(finish="tool_calls"), b'data: [DONE]\n\n'])
        self.assertEqual(result[-1]["message"]["tool_calls"][0]["function"]["arguments"], {})

    async def test_invalid_or_incomplete_calls_never_complete(self):
        for arguments, finish, terminal in [('[]', 'tool_calls', True), ('{', 'tool_calls', True), ('{}', 'stop', True), ('{}', None, False)]:
            with self.subTest(arguments=arguments, finish=finish):
                chunks = [event({"tool_calls": [{"index": 0, "function": {"name": "GetState", "arguments": arguments}}]})]
                if finish:
                    chunks.append(event(finish=finish))
                if terminal:
                    chunks.append(b'data: [DONE]\n\n')
                result = await self.convert(chunks)
                self.assertIn("error", result[-1])
                self.assertFalse(any(row.get("done") for row in result))

    async def test_upstream_error(self):
        result = await self.convert([b'data: {"error":{"message":"rate limit"}}\n\n'])
        self.assertIn("rate limit", result[-1]["error"])

    def test_nonstream_native_arguments(self):
        result = compat.convert_response({"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [{"function": {"name": "GetState", "arguments": '{"area":"Kitchen"}'}}]}, "finish_reason": "tool_calls"}]}, "test")
        self.assertEqual(result["message"]["tool_calls"][0]["function"]["arguments"], {"area": "Kitchen"})

    def test_installer_only_replaces_adapters_and_refuses_changed_layout(self):
        spec = importlib.util.spec_from_file_location("installer", ROOT / "codex_bridge/compat/install.py")
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        source = 'async def _convert_openai_to_ollama_stream(response, model):\n    yield b"old"\n\ndef _convert_openai_to_ollama_response(response, model):\n    return {}\n\ndef unchanged():\n    return 42\n'
        patched = installer.patch(source)
        self.assertIn('as _convert_openai_to_ollama_stream', patched)
        self.assertIn('as _convert_openai_to_ollama_response', patched)
        self.assertTrue(patched.endswith('def unchanged():\n    return 42\n'))
        with self.assertRaises(ValueError):
            installer.patch('def different_version():\n    pass\n')


if __name__ == '__main__':
    unittest.main()
