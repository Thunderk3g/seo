from langchain_openai import OpenAIEmbeddings
from app.config import settings

def get_embeddings():
    return OpenAIEmbeddings(
        api_key=settings.OPENAI_API_KEY,
        model="text-embedding-3-small"
    )
