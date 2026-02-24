import os
import shutil
from pathlib import Path

BASE_DIR = Path('.')

# List of all directories
dirs = [
    "backend/config",
    "backend/config/settings",
    "backend/apps/crawler/services",
    "backend/apps/crawler/selectors",
    "backend/apps/crawler/tests",
    "backend/apps/crawl_sessions/services",
    "backend/apps/crawl_sessions/tests",
    "backend/apps/ai_agents/orchestrator",
    "backend/apps/ai_agents/agents",
    "backend/apps/ai_agents/narrator",
    "backend/apps/ai_agents/rag",
    "backend/apps/ai_agents/services",
    "backend/apps/gsc_integration/clients",
    "backend/apps/gsc_integration/services",
    "backend/apps/dashboard/services",
    "backend/apps/common",
    "backend/api/middleware",
    "backend/core/scheduler",
    "backend/core/signals",
    "backend/core/permissions",
    "backend/requirements",
    "frontend/src",
    "docs",
    ".agent/rules"
]

files = {
    # Backend Config
    "backend/config/__init__.py": '"""Root configuration module."""\n',
    "backend/config/settings/__init__.py": '"""Settings module."""\n',
    "backend/config/settings/base.py": '"""Base settings for Django 12-factor project."""\n\nimport os\nfrom pathlib import Path\n\nBASE_DIR = Path(__file__).resolve().parent.parent.parent\nSECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")\nDEBUG = os.environ.get("DEBUG", "False") == "True"\nALLOWED_HOSTS = []\n\nINSTALLED_APPS = [\n    "django.contrib.admin",\n    "django.contrib.auth",\n    "django.contrib.contenttypes",\n    "django.contrib.sessions",\n    "django.contrib.messages",\n    "django.contrib.staticfiles",\n    "rest_framework",\n    "apps.crawler",\n    "apps.crawl_sessions",\n    "apps.ai_agents",\n    "apps.gsc_integration",\n    "apps.dashboard",\n    "apps.common",\n]\n\nDATABASES = {\n    "default": {\n        "ENGINE": "django.db.backends.postgresql",\n        "NAME": "seo_db",\n    }\n}\nROOT_URLCONF = "config.urls"\nWSGI_APPLICATION = "config.wsgi.application"\n',
    "backend/config/settings/dev.py": '"""Development settings."""\n\nfrom .base import *\n\nDEBUG = True\n',
    "backend/config/settings/prod.py": '"""Production settings."""\n\nfrom .base import *\n\nDEBUG = False\nALLOWED_HOSTS = ["*"] # Configure this in production\n',
    "backend/config/urls.py": '"""Root URL Configuration."""\n\nfrom django.contrib import admin\nfrom django.urls import path, include\n\nurlpatterns = [\n    path("admin/", admin.site.urls),\n    path("api/v1/", include("api.urls")),\n]\n',
    "backend/config/asgi.py": '"""ASGI config."""\n\nimport os\nfrom django.core.asgi import get_asgi_application\n\nos.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")\napplication = get_asgi_application()\n',
    "backend/config/wsgi.py": '"""WSGI config."""\n\nimport os\nfrom django.core.wsgi import get_wsgi_application\n\nos.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")\napplication = get_wsgi_application()\n',
    
    # Crawler App
    "backend/apps/__init__.py": "",
    "backend/apps/crawler/__init__.py": "",
    "backend/apps/crawler/admin.py": '"""Admin interface for crawler models."""\n\nfrom django.contrib import admin\n',
    "backend/apps/crawler/apps.py": '"""Crawler App Configuration."""\n\nfrom django.apps import AppConfig\n\nclass CrawlerConfig(AppConfig):\n    default_auto_field = "django.db.models.BigAutoField"\n    name = "apps.crawler"\n',
    "backend/apps/crawler/models.py": '"""Crawler models (metadata, etc.)."""\n\nfrom django.db import models\n',
    "backend/apps/crawler/services/__init__.py": "",
    "backend/apps/crawler/services/crawler_engine.py": '"""Core Crawler Engine Service."""\n',
    "backend/apps/crawler/services/frontier_manager.py": '"""URL Frontier Manager."""\n',
    "backend/apps/crawler/services/fetcher.py": '"""HTTP Fetcher Logic."""\n',
    "backend/apps/crawler/services/parser.py": '"""HTML Parsing Logic."""\n',
    "backend/apps/crawler/services/renderer.py": '"""JS Rendering logic using Playwright (Placeholder)."""\n',
    "backend/apps/crawler/services/normalization.py": '"""URL/Content Normalization."""\n',
    "backend/apps/crawler/selectors/__init__.py": "",
    "backend/apps/crawler/selectors/link_extractor.py": '"""Link extraction strategies."""\n',
    "backend/apps/crawler/selectors/metadata_extractor.py": '"""Metadata (title, tags) extractor."""\n',
    "backend/apps/crawler/selectors/schema_extractor.py": '"""Structured data (JSON-LD) extraction."""\n',
    "backend/apps/crawler/tasks.py": '"""Scheduled and on-demand crawl tasks (Celery)."""\n',
    "backend/apps/crawler/utils.py": '"""Crawler specific utilities."""\n',
    "backend/apps/crawler/tests/__init__.py": "",

    # Crawl Sessions App
    "backend/apps/crawl_sessions/__init__.py": "",
    "backend/apps/crawl_sessions/models.py": '"""\nCrawl Session snapshot architecture.\nConceptual placeholders: CrawlSession, Page, Link, URLClassification, SitemapURL\n"""\n\nfrom django.db import models\n\nclass CrawlSession(models.Model):\n    pass\n\nclass Page(models.Model):\n    pass\n\nclass Link(models.Model):\n    pass\n\nclass URLClassification(models.Model):\n    pass\n\nclass SitemapURL(models.Model):\n    pass\n',
    "backend/apps/crawl_sessions/services/__init__.py": "",
    "backend/apps/crawl_sessions/services/session_manager.py": '"""Session creation and management service."""\n',
    "backend/apps/crawl_sessions/services/change_detector.py": '"""Change detection between crawl snapshots."""\n',
    "backend/apps/crawl_sessions/services/snapshot_service.py": '"""Snapshot construction and retrieval logic."""\n',
    "backend/apps/crawl_sessions/tests/__init__.py": "",

    # AI Agents App
    "backend/apps/ai_agents/__init__.py": "",
    "backend/apps/ai_agents/orchestrator/__init__.py": "",
    "backend/apps/ai_agents/orchestrator/orchestrator.py": '"""Central AI brain to orchestrate multiple agents."""\n',
    "backend/apps/ai_agents/orchestrator/routing.py": '"""Dynamic routing of structured crawl data to agents."""\n',
    "backend/apps/ai_agents/agents/__init__.py": "",
    "backend/apps/ai_agents/agents/indexing_agent.py": '"""Agent for indexing potential assessment."""\n',
    "backend/apps/ai_agents/agents/classification_agent.py": '"""Agent for page categorization."""\n',
    "backend/apps/ai_agents/agents/link_intelligence_agent.py": '"""Agent to analyze internal linking and PR flow."""\n',
    "backend/apps/ai_agents/agents/structured_data_agent.py": '"""Agent for schema architecture review."""\n',
    "backend/apps/ai_agents/agents/performance_agent.py": '"""Agent evaluating rendering and speed KPIs."""\n',
    "backend/apps/ai_agents/agents/sitemap_agent.py": '"""Agent for sitemap compliance logic."""\n',
    "backend/apps/ai_agents/narrator/__init__.py": "",
    "backend/apps/ai_agents/narrator/insight_narrator.py": '"""Executive insight generator / summarization."""\n',
    "backend/apps/ai_agents/rag/__init__.py": "",
    "backend/apps/ai_agents/rag/retriever.py": '"""RAG document retrieval from completed crawls."""\n',
    "backend/apps/ai_agents/rag/embeddings.py": '"""Vector embeddings connection logic."""\n',
    "backend/apps/ai_agents/rag/chat_engine.py": '"""Conversational chat layer connection."""\n',
    "backend/apps/ai_agents/services/__init__.py": "",
    "backend/apps/ai_agents/services/analysis_pipeline.py": '"""Pipeline managing analysis states."""\n',

    # GSC Integration App
    "backend/apps/gsc_integration/__init__.py": "",
    "backend/apps/gsc_integration/clients/__init__.py": "",
    "backend/apps/gsc_integration/clients/gsc_client.py": '"""Low level client to Google Search Console API."""\n',
    "backend/apps/gsc_integration/services/__init__.py": "",
    "backend/apps/gsc_integration/services/search_analytics_service.py": '"""Service pulling queries, clicks, impressions."""\n',
    "backend/apps/gsc_integration/services/url_inspection_service.py": '"""Service for checking indexed status via Inspection API."""\n',
    "backend/apps/gsc_integration/services/sitemap_service.py": '"""Service to fetch or submit sitemaps to GSC."""\n',
    "backend/apps/gsc_integration/models.py": '"""GSC synced data tables."""\n\nfrom django.db import models\n',
    "backend/apps/gsc_integration/sync_tasks.py": '"""Daily GSC sync jobs (Celery)."""\n',

    # Dashboard App
    "backend/apps/dashboard/__init__.py": "",
    "backend/apps/dashboard/services/__init__.py": "",
    "backend/apps/dashboard/services/coverage_service.py": '"""Aggregation logic for index coverage data."""\n',
    "backend/apps/dashboard/services/link_stats_service.py": '"""Aggregation logic for link stats."""\n',
    "backend/apps/dashboard/services/enhancement_service.py": '"""Aggregation logic for rich schemas and vital parameters."""\n',
    "backend/apps/dashboard/services/overview_service.py": '"""High level dashboard overview summary."""\n',
    "backend/apps/dashboard/serializers.py": '"""API response serializers for React frontend."""\n',
    "backend/apps/dashboard/views.py": '"""REST API endpoints for the dashboard."""\n',

    # Common App
    "backend/apps/common/__init__.py": "",
    "backend/apps/common/constants.py": '"""Shared system constants."""\n',
    "backend/apps/common/exceptions.py": '"""Custom exceptions definitions."""\n',
    "backend/apps/common/logging.py": '"""Centralized logging config/helpers."""\n',
    "backend/apps/common/mixins.py": '"""Reusable mixins."""\n',
    "backend/apps/common/helpers.py": '"""Shared helper functions."""\n',

    # API
    "backend/api/__init__.py": "",
    "backend/api/routers.py": '"""API Routers."""\n\nfrom rest_framework.routers import DefaultRouter\n\nrouter = DefaultRouter()\n',
    "backend/api/urls.py": '"""Central API layer URL routing."""\n\nfrom django.urls import path, include\nfrom .routers import router\n\nurlpatterns = [\n    path("", include(router.urls)),\n]\n',
    "backend/api/middleware/__init__.py": "",
    "backend/api/middleware/request_logging.py": '"""Request logging middleware."""\n',

    # Core
    "backend/core/__init__.py": "",
    "backend/core/scheduler/__init__.py": "",
    "backend/core/scheduler/scheduler.py": '"""Cron / Celery scheduling (daily crawl)."""\n',
    "backend/core/signals/__init__.py": "",
    "backend/core/permissions/__init__.py": "",

    # Requirements
    "backend/requirements/base.txt": "Django>=4.2\ndjangorestframework\npsycopg2-binary\ncelery\nredis\npython-dotenv\n",
    "backend/requirements/dev.txt": "-r base.txt\npytest\npytest-django\n",
    "backend/requirements/prod.txt": "-r base.txt\ngunicorn\n",

    # Root Level Base Configs
    "backend/manage.py": '"""Django manage.py file."""\n\nimport os\nimport sys\n\ndef main():\n    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")\n    try:\n        from django.core.management import execute_from_command_line\n    except ImportError as exc:\n        raise ImportError(\n            "Couldn\'t import Django. Are you sure it\'s installed and "\n            "available on your PYTHONPATH environment variable? Did you "\n            "forget to activate a virtual environment?"\n        ) from exc\n    execute_from_command_line(sys.argv)\n\nif __name__ == "__main__":\n    main()\n',
    "backend/Dockerfile": "# Dockerfile for Django Backend\nFROM python:3.11-slim\n\nWORKDIR /app\n\nCOPY requirements/base.txt /app/\nRUN pip install -r base.txt\n\nCOPY . /app/\n\nCMD [\"gunicorn\", \"config.wsgi\", \"-b\", \"0.0.0.0:8000\"]\n",

    # Frontend
    "frontend/README.md": "# Future React Dashboard Structure\n\nThis is a placeholder directory for the future frontend application.\n",

    # Root
    ".env.example": "DATABASE_URL=postgres://user:password@localhost:5432/seo_db\nGSC_API_KEY=\nSECRET_KEY=replace-me-in-production\nDEBUG=True\n",
    "docker-compose.yml": 'version: "3.8"\n\nservices:\n  db:\n    image: postgres:15\n    environment:\n      POSTGRES_USER: user\n      POSTGRES_PASSWORD: password\n      POSTGRES_DB: seo_db\n    ports:\n      - "5432:5432"\n\n  backend:\n    build:\n      context: ./backend\n    command: python manage.py runserver 0.0.0.0:8000\n    ports:\n      - "8000:8000"\n    env_file:\n      - .env\n    depends_on:\n      - db\n',
    "README.md": "# tanish-24-git-seo\n\nProduction-ready scalable Website Intelligence Platform consisting of a Web Crawler Engine, Multi-Agent AI System, GSC Integration, and a Session-Based Database.\n",
    "pyproject.toml": "[tool.pytest.ini_options]\nDJANGO_SETTINGS_MODULE = \"config.settings.dev\"\npython_files = [\"tests.py\", \"test_*.py\", \"*_tests.py\"]\n",
    "requirements.txt": "-r backend/requirements/base.txt\n"
}

for d in dirs:
    os.makedirs(BASE_DIR / d, exist_ok=True)

for file_path, content in files.items():
    p = BASE_DIR / file_path
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)

# Copy existing files to structure
files_to_copy = {
    "AI Agent Structure.md": "docs/AI Agent Structure.md",
    "Crawling Strategies.md": "docs/Crawling Strategies.md",
    "Database Design – Crawl Session.md": "docs/Database Design – Crawl Session.md",
    "Web Crawler Engine.md": "docs/Web Crawler Engine.md",
    ".agent/rules/rules.md": ".agent/rules/rules.md"
}

for src, dst in files_to_copy.items():
    if os.path.exists(src):
        dest_path = BASE_DIR / dst
        if os.path.abspath(src) != os.path.abspath(dest_path):
            os.makedirs(dest_path.parent, exist_ok=True)
            shutil.copy(src, dest_path)

print("Scaffolding complete.")
