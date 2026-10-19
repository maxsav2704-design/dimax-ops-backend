"""Deterministic demo provider for stacks without a real model key.

It speaks the same Responses shape as the OpenAI provider (function calls and a
final message) so the runner, the tools, the proposals and the UI are exercised
end to end. It is not a model: it recognises a few intents by keywords and
always labels its answers as the demo provider. Status reports provider="mock".
"""
from __future__ import annotations

import json

LABEL = {
    "ru": "Демо-провайдер DIMAX AI: реальная модель не подключена, ответ собран по записям системы.",
    "he": "ספק הדגמה של DIMAX AI: מודל אמיתי אינו מחובר, התשובה נבנתה מרשומות המערכת.",
    "en": "DIMAX AI demo provider: no real model is connected, the answer is built from system records.",
}
ISSUE_WORDS = ("issue", "obstacle", "defect", "замечан", "проблем", "препятств", "дефект", "ליקוי", "בעיה", "מכשול")
UNFINISHED_WORDS = ("unfinished", "not installed", "remaining", "незаверш", "не установ", "остал", "לא הותקנ", "נותר")


def _call(name: str, arguments: dict, call_id: str) -> dict:
    return {"status": "completed", "output": [{"type": "function_call", "call_id": call_id, "name": name,
                                               "arguments": json.dumps(arguments)}]}


def _answer(text: str) -> dict:
    return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}


class MockProvider:
    name = "mock"

    def respond(self, *, instructions: str, items: list[dict], tools: list[dict], timeout: float) -> dict:
        lang = "ru" if "Requested language: ru" in instructions else "he" if "Requested language: he" in instructions else "en"
        names = {tool.get("name") for tool in tools}
        questions = [str(item.get("content", "")) for item in items
                     if isinstance(item, dict) and item.get("role") == "user" and not str(item.get("content", "")).startswith("Selected ")]
        message = questions[-1] if questions else ""
        low = message.lower()
        context = None
        for item in items:
            content = str(item.get("content", "")) if isinstance(item, dict) and item.get("role") == "user" else ""
            if content.startswith("Selected ") and ": " in content:
                try:
                    context = json.loads(content.split(": ", 1)[1])
                except ValueError:
                    context = None
        outputs = []
        for item in items:
            if isinstance(item, dict) and item.get("type") == "function_call_output":
                try:
                    outputs.append(json.loads(item.get("output") or "{}"))
                except ValueError:
                    outputs.append({})
        step = len(outputs) + 1
        wants_issue = any(word in low for word in ISSUE_WORDS)
        pick = lambda *candidates: next((name for name in candidates if name in names), None)  # noqa: E731
        doors_tool = pick("list_project_doors", "my_project_doors")
        comment_tool = pick("propose_issue_comment", "propose_my_issue_comment")
        report_tool = pick("propose_issue_report", "propose_my_issue_report")

        if not outputs:
            if isinstance(context, dict) and "door_status_counts" in context and doors_tool:
                return _call(doors_tool, {"project_id": context["id"], "status": "NOT_INSTALLED", "limit": 20, "offset": 0}, f"mock-{step}")
            if isinstance(context, dict) and "workflow_state" in context and wants_issue and comment_tool:
                return _call(comment_tool, {"issue_id": context["id"], "body": message[:2000]}, f"mock-{step}")
            if "search_projects" in names:
                return _call("search_projects", {"q": None, "limit": 10, "offset": 0}, f"mock-{step}")
            if "my_projects" in names:
                return _call("my_projects", {"limit": 10, "offset": 0}, f"mock-{step}")
            return _answer(self._text(lang, "no_tools") + "\n\n" + LABEL[lang])

        last = outputs[-1]
        if "proposal_id" in last:
            summary = last.get("preview", {}).get("summary", {})
            return _answer(self._text(lang, "proposed", summary) + "\n\n" + LABEL[lang])
        if "error" in last:
            return _answer(self._text(lang, "error", last["error"]) + "\n\n" + LABEL[lang])
        rows = last.get("items") or []
        if wants_issue and report_tool and rows and "unit_label" in rows[0]:
            door = next((row for row in rows if str(row.get("unit_label", "")).lower() in low), rows[0])
            arguments = {"door_id": door["id"], "title": message[:200], "details": None}
            if report_tool == "propose_issue_report":
                arguments["priority"] = "P3"
            return _call(report_tool, arguments, f"mock-{step}")
        labels = [str(row.get("unit_label") or row.get("name") or row.get("full_name") or row.get("title") or "") for row in rows[:10]]
        return _answer(self._text(lang, "listing", {"count": len(rows), "more": bool(last.get("has_more")), "labels": labels})
                       + "\n\n" + LABEL[lang])

    @staticmethod
    def _text(lang: str, kind: str, data=None) -> str:
        data = data or {}
        if kind == "no_tools":
            return {"ru": "Для этого вопроса у учётной записи нет доступных инструментов чтения.",
                    "he": "לחשבון זה אין כלי קריאה זמינים לשאלה זו.",
                    "en": "This account has no read tools available for this question."}[lang]
        if kind == "proposed":
            door = data.get("door") or data.get("issue_title") or ""
            return {"ru": f"Подготовлено предложение для позиции {door}. Ничего не сохранено: подтвердите или отклоните карточку действия.",
                    "he": f"הוכנה הצעה עבור הפריט {door}. דבר לא נשמר: אשר או דחה את כרטיס הפעולה.",
                    "en": f"A proposal was prepared for position {door}. Nothing is saved: confirm or reject the action card."}[lang]
        if kind == "error":
            return {"ru": f"Инструмент вернул ошибку: {data.get('code')}.", "he": f"הכלי החזיר שגיאה: {data.get('code')}.",
                    "en": f"The tool returned an error: {data.get('code')}."}[lang]
        labels = ", ".join(label for label in data.get("labels", []) if label)
        more = {"ru": " Есть ещё записи.", "he": " יש רשומות נוספות.", "en": " There are more records."}[lang] if data.get("more") else ""
        return {"ru": f"По записям системы найдено: {data.get('count')} ({labels}).{more}",
                "he": f"לפי רשומות המערכת נמצאו: {data.get('count')} ({labels}).{more}",
                "en": f"System records found: {data.get('count')} ({labels}).{more}"}[lang]
