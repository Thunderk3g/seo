from typing import Generator
from app.config import settings

# This file will hold the FastAPI dependencies for injecting services,
# such as database sessions, authenticated users, or shared graph instances.

def get_settings():
    return settings

# Add more dependencies such as get_db, get_llm_service, etc.
