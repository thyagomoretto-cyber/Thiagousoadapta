"""Small interactive coding executor backed directly by the OpenAI API.

It is intentionally a terminal program: Agentic IDE can run it like any other
workspace CLI, while authentication stays in Dodaios' API-key store.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from openai import OpenAI


def _key() -> str:
    from dodaios.core.config import get_jarvis_agent_secret
    key = get_jarvis_agent_secret("openai")
    if not key:
        raise RuntimeError("OpenAI API key is not configured in Dodaios")
    return key


def _run_shell(command: str) -> str:
    # Keep agent commands on the same supported runtime as the executor.
    env = os.environ.copy()
    env["PATH"] = os.path.join(sys.prefix, "bin") + os.pathsep + env.get("PATH", "")
    p = subprocess.run(command, shell=True, cwd=os.getcwd(), env=env, text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    return f"exit_code={p.returncode}\n{p.stdout[-20000:]}"


def _tool(name: str, args: dict[str, object]) -> str:
    if name == "run_shell":
        return _run_shell(str(args.get("command", "")))
    if name == "read_file":
        p = Path(str(args["path"])).expanduser()
        return p.read_text(encoding="utf-8")[-30000:]
    if name == "write_file":
        p = Path(str(args["path"])).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(args.get("content", "")), encoding="utf-8")
        return f"wrote {p}"
    if name == "list_files":
        root = Path(str(args.get("path", "."))).expanduser()
        return "\n".join(str(p) for p in sorted(root.rglob("*")) if p.is_file())[:30000]
    if name == "git_status":
        return _run_shell("git status --short --branch")
    if name == "git_diff":
        return _run_shell("git diff -- .")
    raise ValueError(f"unknown tool: {name}")


TOOLS = [
    {"type": "function", "name": "run_shell", "description": "Run a shell command in the workspace.", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"], "additionalProperties": False}},
    {"type": "function", "name": "read_file", "description": "Read a UTF-8 text file.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}},
    {"type": "function", "name": "write_file", "description": "Write a UTF-8 text file, creating parent directories.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"], "additionalProperties": False}},
    {"type": "function", "name": "list_files", "description": "List files below a directory.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "additionalProperties": False}},
    {"type": "function", "name": "git_status", "description": "Show git status.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"type": "function", "name": "git_diff", "description": "Show the current git diff.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
]


def main() -> int:
    client = OpenAI(api_key=_key())
    model = os.getenv("DODAIOS_OPENAI_EXECUTOR_MODEL", "gpt-4.1-mini")
    history: list[dict[str, object]] = []
    sys.stdout.write("OpenAI API executor ready (model: %s)\n› " % model)
    sys.stdout.flush()
    for line in sys.stdin:
        prompt = line.strip()
        if not prompt:
            sys.stdout.write("› "); sys.stdout.flush(); continue
        history.append({"role": "user", "content": prompt})
        for _ in range(24):
            response = client.responses.create(
                model=model,
                instructions=("You are a coding agent working directly in the current workspace. "
                              "Inspect before editing, make changes directly, run relevant tests, "
                              "and report concrete verification. Never claim success without tests."),
                input=history, tools=TOOLS, tool_choice="auto",
            )
            history.extend(item.model_dump() for item in response.output)
            calls = [item for item in response.output if getattr(item, "type", "") == "function_call"]
            if not calls:
                text = response.output_text or "(no response)"
                sys.stdout.write(text + "\n› "); sys.stdout.flush()
                break
            for call in calls:
                try:
                    result = _tool(call.name, json.loads(call.arguments or "{}"))
                except Exception as exc:  # noqa: BLE001
                    result = f"tool error: {exc}"
                history.append({"type": "function_call_output", "call_id": call.call_id, "output": result})
        else:
            sys.stdout.write("The API executor reached its turn limit.\n› "); sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
