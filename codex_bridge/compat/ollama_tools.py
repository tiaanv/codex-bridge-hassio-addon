"""Narrow Ollama tool-call backport for the pinned GPTMock release."""
from __future__ import annotations

import datetime
import json


def native_tools(calls):
    result = []
    for call in calls:
        function = call.get("function", {})
        name = function.get("name")
        arguments = function.get("arguments", "{}")
        if isinstance(arguments, str):
            arguments = json.loads(arguments or "{}")
        if not isinstance(name, str) or not name or not isinstance(arguments, dict):
            raise ValueError("Invalid upstream tool call")
        result.append({"function": {"name": name, "arguments": arguments}})
    return result


def response_frame(message, model, done=False, reason=None):
    frame = {
        "model": model,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "message": message,
        "done": done,
    }
    if reason:
        frame["done_reason"] = reason
    return frame


def convert_response(response, model):
    choice = response.get("choices", [{}])[0]
    message = dict(choice.get("message") or {})
    message["content"] = message.get("content") or ""
    if message.get("tool_calls"):
        message["tool_calls"] = native_tools(message["tool_calls"])
    return response_frame(message, response.get("model") or model, True, choice.get("finish_reason", "stop"))


async def sse_events(response):
    """Buffer transport fragments; an SSE event may cross byte chunks."""
    pending = b""
    async for chunk in response:
        pending += chunk
        while b"\n\n" in pending:
            event, pending = pending.split(b"\n\n", 1)
            data = [line[5:].lstrip() for line in event.splitlines() if line.startswith(b"data:")]
            if data:
                yield b"\n".join(data)
    if pending.strip():
        raise ValueError("Upstream stream ended mid-event")


async def convert_stream(response, model):
    pending_tools = {}
    finish_reason = None
    terminal = False
    try:
        async for data in sse_events(response):
            if data == b"[DONE]":
                if finish_reason is None:
                    raise ValueError("Upstream stream ended without finish reason")
                message = {"role": "assistant", "content": ""}
                if pending_tools:
                    if finish_reason != "tool_calls":
                        raise ValueError("Upstream tool call did not complete")
                    message["tool_calls"] = native_tools([pending_tools[k] for k in sorted(pending_tools)])
                yield (json.dumps(response_frame(message, model, True, finish_reason)) + "\n").encode()
                terminal = True
                break
            chunk = json.loads(data)
            if chunk.get("error"):
                raise ValueError(str(chunk["error"].get("message", "Upstream error")))
            choices = chunk.get("choices", [])
            if not choices:
                continue
            choice = choices[0]
            finish_reason = choice.get("finish_reason") or finish_reason
            delta = choice.get("delta") or {}
            for call in delta.get("tool_calls") or []:
                index = call.get("index", 0)
                accumulated = pending_tools.setdefault(index, {"function": {"name": "", "arguments": ""}})
                function = call.get("function") or {}
                for field in ("name", "arguments"):
                    fragment = function.get(field)
                    if fragment is not None:
                        if not isinstance(fragment, str):
                            raise ValueError("Invalid upstream tool-call fragment")
                        accumulated["function"][field] += fragment
            content = delta.get("content")
            if content:
                yield (json.dumps(response_frame({"role": "assistant", "content": content}, model)) + "\n").encode()
        if not terminal:
            raise ValueError("Upstream stream ended before completion")
    except (ValueError, TypeError, KeyError) as error:
        # Never claim success or execute partial/malformed arguments.
        yield (json.dumps({"error": str(error)}) + "\n").encode()
    finally:
        if hasattr(response, "aclose"):
            await response.aclose()
