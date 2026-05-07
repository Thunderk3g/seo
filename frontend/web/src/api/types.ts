// Types matching the actual DRF serializers in
// backend/apps/crawler/serializers.py. Hand-written until openapi-typescript
// is wired (DRF schema endpoint not yet exposed — see Day 5+).
//
// All primary keys are UUID strings (UUIDPrimaryKeyMixin). Day 1+ code MUST
// treat session/website/page IDs as strings, never numbers.

export type SessionType =
  | 'scheduled'
  | 'on_demand'
  | 'url_inspection';

export type SessionStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled';

// Matches CrawlConfigSerializer.
export interface CrawlConfig {
  max_depth: number;
  max_urls_per_session: number;
  concurrency: number;
  request_delay: number;
  request_timeout: number;
  max_retries: number;
  enable_js_rendering: boolean;
  respect_robots_txt: boolean;
  custom_user_agent: string;
}

// Matches WebsiteSerializer (read).
export interface Website {
  id: string;
  domain: string;
  name: string;
  is_active: boolean;
  include_subdomains: boolean;
  crawl_config: CrawlConfig | null;
  created_at: string;
  updated_at: string;
}

// Matches WebsiteCreateSerializer request body. The serializer normalises
// `domain` server-side; clients can send bare or scheme-prefixed domains.
export interface WebsiteCreate {
  domain: string;
  name?: string;
  is_active?: boolean;
  include_subdomains?: boolean;
  max_depth?: number;
  max_urls_per_session?: number;
  concurrency?: number;
}

// Matches CrawlSessionListSerializer.
export interface CrawlSessionListItem {
  id: string;
  website: string;
  website_domain: string;
  session_type: SessionType;
  status: SessionStatus;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  total_urls_discovered: number;
  total_urls_crawled: number;
  total_urls_failed: number;
  max_depth_reached: number;
  avg_response_time_ms: number;
}

// Matches CrawlSessionDetailSerializer (extends list with extra fields).
export interface CrawlSessionDetail extends CrawlSessionListItem {
  total_urls_skipped: number;
  error_summary: Record<string, number>;
  target_url: string;
  target_path_prefix: string;
  created_at: string;
  updated_at: string;
}

// Matches PageListSerializer.
export interface PageListItem {
  id: string;
  url: string;
  http_status_code: number;
  title: string | null;
  crawl_depth: number;
  load_time_ms: number;
  word_count: number;
  source: string;
  is_https: boolean;
}

// Response shape from POST /websites/:id/crawl/.
export interface CrawlTriggeredResponse {
  message: string;
  task_id: string;
  website_id: string;
}

// DRF validation error shape: { field_name: ["error msg"] } or { detail: "msg" }.
export type DrfFieldErrors = Record<string, string[]>;
