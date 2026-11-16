from typing import Annotated, TypedDict
from langchain_core.documents import Document
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class WorkflowState(TypedDict, total=False):
    query: str
    role: str
    login_token: str
    plan: str
    metric: str
    filters: dict
    documents: list[Document]
    generation: str
    messages: Annotated[list[BaseMessage], add_messages]
    conversation_summary: str
    active_results: list[dict]
    verification_status: str
    verification_feedback: str
    retry_count: int
