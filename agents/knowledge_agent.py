import json
import logging
import os

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from core.llm_factory import extract_text_content, get_llm
from core.prompts import KNOWLEDGE_BASE
from workflow.memory import format_recent_conversation

logger = logging.getLogger("agent.knowledge")


def load_knowledge_ques() -> dict:
    if isinstance(KNOWLEDGE_BASE, str):
        return json.loads(KNOWLEDGE_BASE)
    return KNOWLEDGE_BASE


def get_help_documents() -> list[Document]:
    """Parse knowledge base into structured documents with source metadata."""
    kb = load_knowledge_ques()
    docs = []
    knowledge_dict = kb.get("jewellery_knowledge", {}) if isinstance(kb, dict) else {}
    for category, qas in knowledge_dict.items():
        category_title = category.replace("_", " ").title()
        qa_texts = []
        for item in qas:
            q = item.get("question", "")
            a = item.get("answer", "")
            qa_texts.append(f"Q: {q}\nA: {a}")
        content = f"Category: {category_title}\n" + "\n\n".join(qa_texts)
        docs.append(
            Document(
                page_content=content,
                metadata={"source": f"help_docs:{category}", "category": category},
            )
        )
    return docs


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
    logger.info("Knowledge agent handling query: '%.60s'", query)
    try:
        response = llm.invoke(prompt)
        text = extract_text_content(response.content)
        logger.info("Knowledge agent answered (len=%d) for query='%.60s'", len(text), query)
        help_docs = get_help_documents()
        return {"generation": text, "documents": help_docs}
    except Exception as exc:
        logger.error("Knowledge agent LLM call failed for query='%.60s': %s", query, exc, exc_info=True)
        raise
