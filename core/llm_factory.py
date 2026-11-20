import os
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq


def get_llm(
    model_name: str | None = None,
    temperature: float = 0.0,
    max_retries: int = 2,
    llm_class=None,
):
    if llm_class is not None and llm_class is not ChatGroq:
        return llm_class(temperature=temperature, max_retries=max_retries)

    target_model = model_name or os.getenv("DEFAULT_LLM_MODEL", "gemini-3.5-flash-lite")

    if target_model.startswith("gemini-"):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not configured in the environment.")
        return ChatGoogleGenerativeAI(
            model=target_model,
            temperature=temperature,
            max_retries=max_retries,
            google_api_key=api_key.strip('"\''),
            reasoning_effort="low",
        )

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY is not configured in the environment.")

    return ChatGroq(
        model_name=target_model,
        temperature=temperature,
        max_retries=max_retries,
        api_key=api_key.strip('"\''),
    )


def extract_text_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            elif hasattr(item, "text"):
                parts.append(str(getattr(item, "text")))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)
