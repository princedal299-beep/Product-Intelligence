import asyncio
import logging
import uuid
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from agents.catalog_agent import catalog_agent
from agents.composer_agent import composer_agent
from agents.knowledge_agent import knowledge_agent
from agents.router_agent import route_query
from agents.verifier_agent import verify_answer
from workflow.memory import checkpoint_saver, summarize_history_node
from workflow.state import WorkflowState

logger = logging.getLogger("workflow.graph")

MAX_RETRIES = 2


async def route_node(state):
    feedback = state.get("verification_feedback")
    route_state = {
        "query": state["query"],
        "role": state.get("role"),
        "messages": state.get("messages", []),
        "conversation_summary": state.get("conversation_summary", ""),
        "active_results": state.get("active_results", []),
    }
    if feedback:
        logger.info("Retrying routing with feedback: %s", feedback)
        route_state["query"] = f"{state['query']}\n\nPrevious answer failed verification: {feedback}"
    else:
        logger.info("Routing query for role=%s: '%.60s'", state.get("role"), state.get("query", ""))
    decision = await asyncio.to_thread(route_query, route_state)
    logger.info(
        "Router decision: plan=%s, metric=%s, filters=%s",
        decision.get("plan"),
        decision.get("metric"),
        decision.get("filters"),
    )
    return decision


async def knowledge_node(state):
    return await asyncio.to_thread(knowledge_agent, state)


async def composer_node(state):
    return await asyncio.to_thread(composer_agent, state)


async def verifier_node(state):
    res = await asyncio.to_thread(verify_answer, state)
    logger.info(
        "Verifier evaluated answer: status=%s, retry_count=%s, feedback=%s",
        res.get("verification_status"),
        res.get("retry_count"),
        res.get("verification_feedback"),
    )
    return res


def route_to_agent(state):
    route = state.get("plan")
    if route in {"product_search", "product_details", "catalog_analytics"}:
        target = "catalog_agent"
    elif route == "jewellery_help":
        target = "knowledge_agent"
    else:
        target = "safe_response"
    logger.info("Routing to agent node: '%s' (based on plan '%s')", target, route)
    return target


def after_verification(state):
    status = state.get("verification_status")
    retries = state.get("retry_count", 0)
    if status == "PASS":
        logger.info("Verification PASSED -> finishing turn")
        return "end"
    if retries < MAX_RETRIES:
        logger.warning("Verification FAILED (retries=%d/%d) -> retrying router", retries, MAX_RETRIES)
        return "retry"
    logger.warning("Verification FAILED max retries reached (%d) -> safe_response", retries)
    return "safe_response"


def safe_response(state):
    if state.get("retry_count", 0) >= MAX_RETRIES:
        msg = "Sorry, I could not confirm this answer."
    else:
        msg = "I can't help with that request."
    return {"generation": msg}


def initialize_turn(state):
    query = state.get("query", "").strip()
    updates = {
        "retry_count": 0,
        "verification_feedback": "",
        "verification_status": "",
        "documents": [],
        "generation": "",
        "login_token": state.get("login_token", ""),
        "role": state.get("role", "Shopper"),
    }
    existing_messages = state.get("messages", [])
    if query and (not existing_messages or getattr(existing_messages[-1], "content", "") != query):
        updates["messages"] = [HumanMessage(content=query, id=str(uuid.uuid4()))]
    return updates


def finish_turn(state):
    generation = state.get("generation", "")
    updates = {"login_token": ""}
    if generation:
        updates["messages"] = [AIMessage(content=generation, id=str(uuid.uuid4()))]
    return updates


def build_graph():
    workflow = StateGraph(WorkflowState)
    workflow.add_node("initialize_turn", initialize_turn)
    workflow.add_node("router", route_node)
    workflow.add_node("catalog_agent", catalog_agent)
    workflow.add_node("composer", composer_node)
    workflow.add_node("knowledge_agent", knowledge_node)
    workflow.add_node("verifier", verifier_node)
    workflow.add_node("safe_response", safe_response)
    workflow.add_node("finish_turn", finish_turn)
    workflow.add_node("summarize_history", summarize_history_node)

    workflow.add_edge(START, "initialize_turn")
    workflow.add_edge("initialize_turn", "router")
    workflow.add_conditional_edges(
        "router",
        route_to_agent,
        {
            "catalog_agent": "catalog_agent",
            "knowledge_agent": "knowledge_agent",
            "safe_response": "safe_response",
        },
    )
    workflow.add_edge("catalog_agent", "composer")
    workflow.add_edge("composer", "verifier")
    workflow.add_edge("knowledge_agent", "finish_turn")
    workflow.add_conditional_edges(
        "verifier",
        after_verification,
        {
            "end": "finish_turn",
            "retry": "router",
            "safe_response": "safe_response",
        },
    )
    workflow.add_edge("safe_response", "finish_turn")
    workflow.add_edge("finish_turn", "summarize_history")
    workflow.add_edge("summarize_history", END)
    return workflow.compile(checkpointer=checkpoint_saver)


app_graph = build_graph()


async def run_workflow(
    query,
    role,
    login_token,
    thread_id="default",
):
    config = {"configurable": {"thread_id": str(thread_id)}}
    initial_state = {
        "query": query,
        "role": role,
        "login_token": login_token,
    }

    logger.info(
        "Starting workflow run: thread_id=%s, role=%s, query='%.60s'",
        thread_id,
        role,
        query,
    )
    try:
        result = await app_graph.ainvoke(initial_state, config=config)
        generation = result.get("generation", "No response generated.")
        logger.info("Workflow completed successfully: thread_id=%s, gen_len=%d", thread_id, len(generation))
        return result
    except Exception as exc:
        logger.error(
            "Workflow execution failed: thread_id=%s, query='%.60s': %s",
            thread_id,
            query,
            exc,
            exc_info=True,
        )
        raise
