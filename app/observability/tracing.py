import os
from langsmith import Client
from app.config import settings

def init_tracing():
    """
    Initializes LangSmith tracing if configuration is present.
    """
    if settings.LANGCHAIN_TRACING_V2:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.LANGCHAIN_API_KEY
        os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT
        return Client()
    return None
