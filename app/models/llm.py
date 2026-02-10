from langchain_openai import ChatOpenAI
from app.config import settings

def get_llm(streaming: bool = False):
    return ChatOpenAI(
        api_key=settings.OPENAI_API_KEY,
        model=settings.OPENAI_MODEL,
        temperature=0,
        streaming=streaming
    )
