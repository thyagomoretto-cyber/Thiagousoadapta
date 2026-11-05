"""Pergunta ao dono por voz e na tela quando o agente nao sabe como seguir.

Vale para qualquer tarefa e aprendizado. O que o dono confirma fica salvo e nao
e perguntado de novo. Risk tier: ``safe`` — so fala e espera a resposta.
"""
from __future__ import annotations

import asyncio
from typing import Any

from dodaios.core import agent_questions as questions
from dodaios.core.protocols import ExecutionContext, ToolResult


class AskOwnerTool:
    name: str = "ask_owner"
    risk_tier: str = "safe"
    description: str = (
        "Asks the owner a question out loud and on screen, then waits for the answer. Use it when you are "
        "stuck, when something differs from what you were taught, or when a decision is the owner's: an "
        "unknown button, an unexpected dialog, a choice you cannot verify. Never guess in those cases. "
        "Write the question in the owner's language, say what you see and what you need. Give `topic` for "
        "a situation that can repeat, so a confirmed answer is saved and reused."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "What to ask, in one or two spoken sentences."},
            "options": {"type": "array", "items": {"type": "string"}, "description": "Optional short answers to offer as buttons."},
            "topic": {"type": "string", "description": "Stable name of a situation that can repeat, for reusing the answer."},
        },
        "required": ["question"],
    }

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        question = str(args.get("question") or "").strip()
        if not question:
            return ToolResult(success=False, output=None, error="question is missing")
        topic = str(args.get("topic") or "").strip()
        known = questions.learned(f"tarefa|{topic}") if topic else None
        if known:
            return ToolResult(success=True, output={"answer": known["valor"], "source": "saved"})
        options = [str(item) for item in args.get("options") or []]
        answer = await asyncio.to_thread(questions.ask_owner, question, options)
        if not answer:
            return ToolResult(success=False, output=None, error="The owner did not answer. Stop this step and report what is pending.")
        saved = False
        if topic and not questions.forbidden_click(answer):
            keep = await asyncio.to_thread(questions.ask_owner, f"entendi: {answer[:120]}. Salvo para fazer sempre assim?", ["Sim", "Não"], 90)
            if questions.interpret(keep)["acao"] == "sim":
                questions.learn(f"tarefa|{topic}", {"acao": "texto", "valor": answer})
                saved = True
        return ToolResult(success=True, output={"answer": answer, "source": "owner", "saved": saved})
