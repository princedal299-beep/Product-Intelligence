import json
import os

from langchain_core.messages import HumanMessage, SystemMessage
from core.llm_factory import extract_text_content, get_llm
from core.prompts import KNOWLEDGE_BASE
from workflow.memory import format_recent_conversation


def load_knowledge_ques() -> dict:
    if isinstance(KNOWLEDGE_BASE, str):
        return json.loads(KNOWLEDGE_BASE)
    return KNOWLEDGE_BASE


def knowledge_agent(state: dict) -> dict:
    query = state.get("query", "").strip()
    if not query:
        return {"generation": "I don't have a question to answer."}

    messages = state.get("messages", [])
    summary = state.get("conversation_summary", "")
    summary_text = (
        f"\n\nOlder conversation summary:\n{summary}"
        if summary
        else ""
    )
    recent_chat = format_recent_conversation(messages, current_query=query, limit=4)

    knowledge_model = os.getenv("KNOWLEDGE_LLM_MODEL", "gemini-3.5-flash-lite")
    llm = get_llm(model_name=knowledge_model, temperature=0)
    knowledge_context = (
        KNOWLEDGE_BASE
        if isinstance(KNOWLEDGE_BASE, str)
        else json.dumps(KNOWLEDGE_BASE, ensure_ascii=False)
    )
    prompt = [
        SystemMessage(
            content=(
                "You are a jewellery care and customer support assistant.\n"
                "Answer the user's questions using ONLY the provided knowledge base.\n"
                "Use the previous conversation to understand follow-up references.\n"
                "If the information is unavailable, say that you don't have enough "
                "information in the help documentation.\n\n"
                f"Knowledge base:\n{knowledge_context}\n\n"
                f"{summary_text}{recent_chat}"
            )
        ),
        HumanMessage(content=query),
    ]
    response = llm.invoke(prompt)
    return {"generation": extract_text_content(response.content)}
