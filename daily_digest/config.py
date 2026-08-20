"""Source definitions and tunable knobs for the daily digest."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "out"
DB_PATH = DATA_DIR / "digest.db"

ARTICLES_PER_DAY = 2

# Slots reserved for older, high-scoring backlog items. Guarantees a full
# digest on days when nothing good ships.
BACKLOG_SLOTS = 1

# Only items published within this window count as "fresh".
FRESH_WINDOW_DAYS = 21

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 DailyDigest/0.1"
)


@dataclass(frozen=True)
class Source:
    key: str
    name: str
    feed_url: str
    # Nudges sources that reliably publish deep engineering content.
    weight: float = 1.0


# Verified working 2026-08. Sources that fetch AND yield scoreable body text.
SOURCES: list[Source] = [
    Source("cloudflare", "Cloudflare", "https://blog.cloudflare.com/rss/", 1.3),
    Source("pinterest", "Pinterest", "https://medium.com/feed/pinterest-engineering", 1.2),
    Source("discord", "Discord", "https://discord.com/blog/rss.xml", 0.7),
    Source("slack", "Slack", "https://slack.engineering/feed/", 1.3),
    Source("vercel", "Vercel", "https://vercel.com/atom", 0.6),
    Source("instacart", "Instacart", "https://tech.instacart.com/feed", 1.1),
    Source("airbnb", "Airbnb", "https://medium.com/feed/airbnb-engineering", 1.2),
    Source("netflix", "Netflix", "https://netflixtechblog.com/feed", 1.3),
    Source("meta", "Meta", "https://engineering.fb.com/feed/", 1.3),
    Source("github", "GitHub", "https://github.blog/engineering/feed/", 1.1),
    Source("aws_arch", "AWS Architecture", "https://aws.amazon.com/blogs/architecture/feed/", 1.0),
]

# Sources from the original wishlist that v0 cannot serve, with the reason.
# `doctor` reports these so the gap stays visible instead of silently missing.
NEEDS_ADAPTER: dict[str, str] = {
    "OpenAI": "article pages return 403; RSS carries 25-word teasers only -> needs headless browser",
    "Stripe": "/blog/feed.rss is the marketing blog; engineering posts at /blog/engineering have no RSS -> needs HTML adapter",
    "Anthropic": "no RSS endpoint (404 on all common paths) -> needs HTML adapter",
    "Databricks": "connection reset by bot protection -> needs headless browser",
    "Shopify": "no RSS endpoint (404) -> needs HTML adapter",
    "Snowflake": "403 forbidden / connection reset -> needs headless browser",
    "Confluent": "no RSS endpoint (404) -> needs HTML adapter",
    "CockroachDB": "no RSS endpoint (404) -> needs HTML adapter",
    "ClickHouse": "no RSS endpoint (404) -> needs HTML adapter",
    "Figma": "no RSS endpoint (404) -> needs HTML adapter",
    "Uber": "406 not acceptable on RSS paths -> needs HTML adapter",
}

# Staff-level competency taxonomy. Selection fills the least-covered bucket
# rather than always taking the top-scoring item, which forces breadth.
COMPETENCIES: dict[str, list[str]] = {
    "distributed-systems": [
        "consensus", "raft", "paxos", "quorum", "replication", "leader election",
        "consistency", "linearizab", "partition", "split brain", "gossip", "clock skew",
    ],
    "storage-and-data": [
        "database", "index", "b-tree", "lsm", "shard", "postgres", "mysql",
        "cassandra", "schema", "query planner", "olap", "oltp", "data lake",
    ],
    "caching": ["cache", "cdn", "invalidation", "redis", "memcache", "hit rate", "edge network"],
    "queues-and-streaming": [
        "kafka", "queue", "stream", "pub/sub", "event-driven", "backpressure",
        "exactly-once", "flink", "ingestion pipeline",
    ],
    "scale-and-performance": [
        "latency", "throughput", "p99", "benchmark", "optimiz", "bottleneck",
        "profil", "load test", "capacity", "tail latency",
    ],
    "reliability-and-incidents": [
        "outage", "incident", "postmortem", "post-mortem", "resilien",
        "circuit breaker", "retry", "chaos", "sre", "availability", "degradation",
    ],
    "observability": [
        "observab", "tracing", "telemetry", "metrics", "logging", "monitor", "opentelemetry",
    ],
    "migrations": [
        "migrat", "rewrite", "legacy", "cutover", "backfill", "zero-downtime", "decommission",
    ],
    "architecture-and-apis": [
        "architect", "microservice", "monolith", "api design", "grpc", "graphql",
        "service mesh", "idempoten", "protocol",
    ],
    "security-and-multitenancy": [
        "security", "auth", "encryption", "tenant", "isolation", "rate limit", "abuse", "ddos",
    ],
    "infra-and-cost": [
        "kubernetes", "container", "provisioning", "cost", "efficiency",
        "compute", "utilization", "fleet", "ec2",
    ],
    "ml-systems": [
        "inference", "training", "model serving", "gpu", "embedding", "ranking",
        "recommendation", "feature store", "llm",
    ],
}


@dataclass
class LLMConfig:
    """OpenAI-compatible endpoint. Works with OpenAI, Azure, GitHub Models, Ollama."""

    api_key: str = field(default_factory=lambda: os.getenv("DIGEST_LLM_API_KEY", ""))
    base_url: str = field(
        default_factory=lambda: os.getenv("DIGEST_LLM_BASE_URL", "https://api.openai.com/v1")
    )
    model: str = field(default_factory=lambda: os.getenv("DIGEST_LLM_MODEL", "gpt-4o-mini"))

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)
