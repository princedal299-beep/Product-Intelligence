import os
from langchain_core.messages import HumanMessage, RemoveMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from core.llm_factory import extract_text_content, get_llm
from workflow.state import WorkflowState

checkpoint_saver = InMemorySaver()

SUMMARY_TRIGGER_COUNT = 6
RECENT_COUNT_TO_KEEP = 4


def format_recent_conversation(messages: list, current_query: str = "", limit: int = 4) -> str:
    if not messages:
        return ""

    formatted = []
    for m in messages:
        m_type = getattr(m, "type", "")
        content = str(getattr(m, "content", "")).strip()
        if not content:
            continue
        if m_type == "human" and content == current_query.strip():
            continue

        role = "User" if m_type == "human" else "Assistant"
        if m_type != "human" and len(content) > 300:
            content = content[:300].rstrip() + "..."

        formatted.append(f"{role}: {content}")

    recent = formatted[-limit:]
    if not recent:
        return ""
    return "\n\nRecent conversation (last 4 messages):\n" + "\n".join(recent)


def summarize_history_node(state: WorkflowState) -> dict:
    messages = state.get("messages", [])
    valid_messages = [
        m for m in messages
        if getattr(m, "type", "") in {"human", "ai"}
    ]

    if len(valid_messages) < SUMMARY_TRIGGER_COUNT:
        return {}

    old_messages = valid_messages[:-RECENT_COUNT_TO_KEEP]
    if not old_messages:
        return {}

    conversation_lines = []
    for m in old_messages:
        role = "User" if getattr(m, "type", "") == "human" else "Assistant"
        txt = str(getattr(m, "content", "")).strip()
        if txt:
            if len(txt) > 200:
                txt = txt[:200] + "..."
            conversation_lines.append(f"{role}: {txt}")
    old_conversation = "\n".join(conversation_lines)

    summarizer_model = os.getenv("SUMMARIZER_LLM_MODEL", "gemini-3.5-flash-lite")
    llm = get_llm(model_name=summarizer_model, temperature=0)
    response = llm.invoke(
        [
            SystemMessage(
                content=(
                    "You are a concise memory compressor for a fine jewelry assistant.\n"
                    "Summarize the conversation history strictly within 150 to 200 words.\n"
                    "Focus strictly on:\n"
                    "- Active user preferences (gemstone, metal, jewelry category, budget, style)\n"
                    "- Specific product IDs, SKUs, or items viewed\n"
                    "- Pending questions or unresolved criteria\n"
                    "Discard chit-chat, greetings, and resolved queries.\n"
                    "If older details exceed ~400 words, prune the oldest resolved topics and retain only active preferences."
                )
            ),
            HumanMessage(
                content=(
                    f"Existing summary:\n{state.get('conversation_summary', '')}\n\n"
                    f"Older user questions to incorporate:\n{old_conversation}"
                )
            ),
        ]
    )

    new_summary = extract_text_content(response.content).strip()

    if len(new_summary.split()) >= 300:
        condenser_prompt = [
            SystemMessage(
                content=(
                    "You are a concise memory compressor for a fine jewelry assistant.\n"
                    "The conversation summary has reached over 300 words. Re-compress it into a strictly shorter summary of 100 to 150 words.\n"
                    "Retain only active user preferences (budget, metal, gemstone, style) and viewed product SKUs.\n"
                    "Drop resolved questions and non-essential history."
                )
            ),
            HumanMessage(content=new_summary),
        ]
        condensed_resp = llm.invoke(condenser_prompt)
        new_summary = extract_text_content(condensed_resp.content).strip()

    removals = [
        RemoveMessage(id=m.id)
        for m in old_messages
        if getattr(m, "id", None)
    ]
    return {
        "conversation_summary": new_summary,
        "messages": removals,
    }
