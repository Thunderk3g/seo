"""Robots.txt Parser and Compliance Checker.

Implements Section 6 (Robots.txt Handling) of the Web Crawler Engine spec:
- Parse disallowed paths and directories
- Respect crawl-delay directives
- Extract sitemap locations declared in the robots file
- Apply user-agent specific rules
"""

import re
from typing import Optional
from urllib.parse import urlparse

from apps.common.logging import robots_logger


class RobotsParser:
    """Parse and query robots.txt rules for crawl compliance.

    Fetches and parses robots.txt before any page requests to
    ensure ethical, rule-compliant crawling.
    """

    def __init__(self, user_agent: str = "*"):
        self.user_agent = user_agent
        self._disallowed: list[str] = []
        self._allowed: list[str] = []
        self._crawl_delay: Optional[float] = None
        self._sitemap_urls: list[str] = []
        self._parsed = False

    @property
    def disallowed_paths(self) -> list[str]:
        return list(self._disallowed)

    @property
    def allowed_paths(self) -> list[str]:
        return list(self._allowed)

    @property
    def crawl_delay(self) -> Optional[float]:
        return self._crawl_delay

    @property
    def sitemap_urls(self) -> list[str]:
        return list(self._sitemap_urls)

    def parse(self, robots_content: str) -> None:
        """Parse robots.txt content and extract rules.

        Handles multiple user-agent blocks, applying rules from
        both the specific user-agent and the wildcard (*) blocks.
        """
        if not robots_content:
            self._parsed = True
            return

        lines = robots_content.strip().split("\n")
        current_agents: list[str] = []
        agent_rules: dict[str, dict] = {}
        global_sitemaps: list[str] = []

        for raw_line in lines:
            # Strip comments
            line = raw_line.split("#")[0].strip()
            if not line:
                continue

            # Parse directive
            if ":" not in line:
                continue

            directive, _, value = line.partition(":")
            directive = directive.strip().lower()
            value = value.strip()

            if directive == "user-agent":
                current_agents = [value.lower()]
                for agent in current_agents:
                    if agent not in agent_rules:
                        agent_rules[agent] = {
                            "disallow": [],
                            "allow": [],
                            "crawl-delay": None,
                        }

            elif directive == "disallow" and current_agents:
                if value:
                    for agent in current_agents:
                        agent_rules.setdefault(
                            agent, {"disallow": [], "allow": [], "crawl-delay": None}
                        )["disallow"].append(value)

            elif directive == "allow" and current_agents:
                if value:
                    for agent in current_agents:
                        agent_rules.setdefault(
                            agent, {"disallow": [], "allow": [], "crawl-delay": None}
                        )["allow"].append(value)

            elif directive == "crawl-delay" and current_agents:
                try:
                    delay = float(value)
                    for agent in current_agents:
                        agent_rules.setdefault(
                            agent, {"disallow": [], "allow": [], "crawl-delay": None}
                        )["crawl-delay"] = delay
                except ValueError:
                    pass

            elif directive == "sitemap":
                global_sitemaps.append(value)

        # ── Apply rules for our user-agent ─────────────────────
        ua_lower = self.user_agent.lower().split("/")[0].strip()
        specific = agent_rules.get(ua_lower, {})
        wildcard = agent_rules.get("*", {})

        # Specific agent rules take precedence over wildcard
        if specific:
            rules = specific
        else:
            rules = wildcard

        self._disallowed = rules.get("disallow", [])
        self._allowed = rules.get("allow", [])
        self._crawl_delay = rules.get("crawl-delay")
        self._sitemap_urls = global_sitemaps

        self._parsed = True

        robots_logger.info(
            "Parsed robots.txt: %d disallowed, %d allowed, %d sitemaps, delay=%s",
            len(self._disallowed), len(self._allowed),
            len(self._sitemap_urls), self._crawl_delay,
        )

    def is_allowed(self, url: str) -> bool:
        """Check if a URL is allowed by robots.txt rules.

        Uses longest-match semantics: the most specific matching
        rule wins. Allowed rules take precedence over disallowed
        for the same specificity.
        """
        if not self._parsed:
            return True

        path = urlparse(url).path

        # Check explicit allows first (longer match = higher priority)
        best_allow_len = 0
        best_disallow_len = 0

        for pattern in self._allowed:
            if self._path_matches(path, pattern):
                best_allow_len = max(best_allow_len, len(pattern))

        for pattern in self._disallowed:
            if self._path_matches(path, pattern):
                best_disallow_len = max(best_disallow_len, len(pattern))

        if best_allow_len > 0 or best_disallow_len > 0:
            # Longer match wins; allow wins on ties
            return best_allow_len >= best_disallow_len

        return True

    @staticmethod
    def _path_matches(path: str, pattern: str) -> bool:
        """Check if a URL path matches a robots.txt pattern.

        Supports:
        - Simple prefix matching (/admin → /admin/*)
        - Wildcard (*) matching
        - End anchor ($) matching
        """
        if not pattern:
            return False

        # Handle end anchor ($)
        if pattern.endswith("$"):
            regex_pattern = re.escape(pattern[:-1]) + "$"
        else:
            regex_pattern = re.escape(pattern)

        # Handle wildcards (*)
        regex_pattern = regex_pattern.replace(r"\*", ".*")

        # Pattern should match from start of path
        regex_pattern = "^" + regex_pattern

        try:
            return bool(re.match(regex_pattern, path))
        except re.error:
            return False
