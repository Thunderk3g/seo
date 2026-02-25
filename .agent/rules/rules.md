---
trigger: always_on
---

---
trigger: always_on
glob: **
description: Enforce enterprise-grade coding standards for Django, React, Docker, and AI-crawler architecture. No emojis, no informal output, and strict best practices.
---

# Global Development Rules – Website Intelligence Platform

## 1. Communication & Output Rules
- Do NOT use emojis in code, comments, documentation, or outputs.
- Maintain professional, technical, and concise language.
- Avoid fluff, filler text, and unnecessary verbosity.
- Prefer clarity, determinism, and structured responses.
- All generated code must be production-grade, not tutorial-level.

---

## 2. General Engineering Principles (MANDATORY)
- Follow SOLID principles.
- Follow DRY (Don’t Repeat Yourself).
- Follow Clean Architecture and separation of concerns.
- Avoid monolithic file structures.
- Prefer modular, scalable, and maintainable code.
- Write self-documenting code with meaningful naming.
- Avoid hardcoded values; use configuration and environment variables.
- Ensure scalability for large datasets (millions of URLs, links, crawl sessions).

---

## 3. Django Backend Best Practices (STRICT)

### 3.1 Project Architecture
- Use domain-driven app structure (not a single monolithic app).
- Separate apps by responsibility:
  - crawler
  - crawl_sessions
  - ai_agents
  - gsc_integration
  - dashboard
  - common (shared utilities)
- Keep business logic inside `services/` layers.
- Do NOT place business logic inside views or models.

### 3.2 Models
- Keep models lean and focused on data representation.
- Avoid fat models with excessive logic.
- Use indexed fields for frequently queried columns.
- Use UUIDs for critical entities (e.g., crawl sessions).
- Optimize for PostgreSQL performance (JSONB where appropriate).

### 3.3 Views & APIs
- Use Django REST Framework for APIs.
- Views must remain thin.
- Delegate logic to service layer.
- Use serializers for validation and transformation.
- Ensure pagination for large datasets.

### 3.4 Services Layer (Critical)
- All core logic must be inside services modules.
- Examples:
  - crawler_engine.py
  - session_manager.py
  - analysis_pipeline.py
- Services must be reusable and testable.
- Avoid duplicated logic across apps.

### 3.5 Settings & Configuration
- Use 12-factor configuration.
- Split settings into:
  - base.py
  - dev.py
  - prod.py
- Use environment variables for secrets and credentials.
- Never hardcode API keys or secrets.

---

## 4. React Frontend Best Practices (Future-Ready)

### 4.1 Structure
- Use modular component architecture.
- Separate:
  - components/
  - pages/
  - services/
  - hooks/
  - utils/
- Avoid large, monolithic components.

### 4.2 Coding Standards
- Use functional components and hooks.
- Avoid unnecessary re-renders (memoization where needed).
- Keep components pure and reusable.
- Maintain strict separation between UI and business logic.

### 4.3 State Management
- Prefer centralized state management when scaling.
- Avoid deeply nested prop drilling.
- Use service/API layer for backend communication.

---

## 5. Docker & Hybrid Containerization Rules (MANDATORY)

### 5.1 Containerization Philosophy
- Use hybrid containerization:
  - Django backend container
  - PostgreSQL container
  - Optional Redis/Celery containers (future)
- Keep containers lightweight and production-ready.

### 5.2 Docker Best Practices
- Use multi-stage builds where applicable.
- Do not run applications as root inside containers.
- Keep Dockerfiles optimized and minimal.
- Use docker-compose for local orchestration.
- Separate dev and production container configurations.

### 5.3 Environment Management
- Use `.env` files for configuration.
- Provide `.env.example` template.
- Do not commit real environment secrets.

---

## 6. Crawler System Development Rules
- Ensure asynchronous and non-blocking crawl design.
- Implement BFS-based crawling with priority frontier.
- Prevent infinite loops and duplicate crawling.
- Respect robots.txt and crawl politeness.
- Log crawl metrics (status codes, depth, latency).
- Design for high-scale link graphs and large crawl sessions.

---

## 7. AI Agent Architecture Rules
- AI agents must NOT perform raw crawling.
- AI layer must consume structured crawl data only.
- Use orchestrator pattern for multi-agent coordination.
- Keep agents modular and domain-specific.
- Avoid hallucinated outputs; ground insights in actual crawl signals.

---

## 8. Database & PostgreSQL Best Practices
- Use session-based snapshot architecture.
- Index frequently queried fields (URL, session_id, status).
- Optimize for large-scale data storage.
- Avoid N+1 queries (use select_related/prefetch_related).
- Use migrations properly; never modify DB schema manually in production.

---

## 9. Logging, Monitoring, and Observability
- Implement centralized structured logging.
- Log crawl events, errors, and retries.
- Avoid excessive console noise.
- Use meaningful log levels (INFO, WARNING, ERROR).
- Ensure debuggability for large crawl operations.

---

## 10. Testing & Code Quality
- Write unit tests for services and core logic.
- Maintain test separation per app.
- Avoid untested critical logic (crawler, AI pipeline, DB services).
- Use linting and formatting standards (PEP8 for Python).
- Ensure type-safe and maintainable code.

---

## 11. Security Best Practices
- Never expose API keys or secrets in code.
- Validate all external inputs.
- Sanitize URLs before crawling.
- Implement rate limiting for APIs.
- Use secure authentication mechanisms for external integrations (e.g., GSC API).

---

## 12. Documentation Rules
- Maintain clear technical documentation in `/docs`.
- Keep architecture docs updated with system changes.
- Write professional README files.
- Avoid emojis and informal language in documentation.

---

## 13. Prohibited Practices (STRICTLY DISALLOWED)
- No emojis in code, comments, logs, or documentation.
- No monolithic Django apps.
- No business logic inside views.
- No hardcoded credentials.
- No duplicated service logic.
- No unstructured project architecture.
- No experimental or hacky code in core modules.

---

## 14. Final Development Philosophy
This workspace must produce:
- Scalable
- Maintainable
- Production-grade
- Enterprise-level code

All implementations must prioritize performance, modularity, and long-term extensibility suitable for a large-scale AI-driven crawler and website intelligence platform.