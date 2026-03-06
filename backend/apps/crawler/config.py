from dataclasses import dataclass, field
from typing import List, Optional, Set

@dataclass
class CrawlConfig:
    """
    Crawl configuration as defined in spec §3, §6, §15, §20, §22.
    """
    user_agent: str = "DeepCrawler/1.0 (Search Engine Bot; +https://example.com/bot)"
    max_depth: int = 5
    max_urls: int = 1000
    crawl_delay: float = 1.0  # Default delay between requests if not specified by robots.txt
    allowed_domains: Set[str] = field(default_factory=set)
    include_subdomains: bool = False
    
    # Fetcher/Renderer configuration
    request_timeout: int = 30
    max_retries: int = 3
    concurrency: int = 5 # Max concurrent fetches per domain
    
    # Ethics/Compliance
    respect_robots: bool = True
    
    # JS Rendering
    render_js: bool = False # Whether to use Playwright (spec §9)
    wait_until: str = "networkidle" # networkidle, load, domcontentloaded
    
    # Persistence/Engine
    continuous_loop: bool = True
    recrawl_interval: int = 86400 # 24 hours
    
    def __post_init__(self):
        # Normalize domains to lowercase
        self.allowed_domains = {d.lower() for d in self.allowed_domains}
