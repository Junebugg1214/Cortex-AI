from __future__ import annotations

import re
from collections import defaultdict

IDENTITY_PATTERNS = [
    r"(?:my name is|i'?m|i am|call me)\s+([A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*(?:\s+[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*)*)",
    r"(?:this is)\s+(?:Dr\.?\s+)?([A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*(?:\s+[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*)*)",
    r"(?:i'?m|i am)\s+([A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*(?:\s+[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*)*),?\s*(?:MD|PhD|JD|MBA|DO|DDS|RN|PE|CPA)",
    r"(?:Dr\.?|Doctor)\s+([A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*)",
]

ROLE_PATTERNS = [
    r"i(?:'m| am) (?:a |an |the )?([a-z]+(?:\s+[a-z]+)?(?:ist|er|or|ant|ent|ian|ive|manager|director|officer|founder|engineer|developer|designer|analyst|scientist|physician|doctor|nurse|lawyer|consultant))",
    r"(?:work(?:ing)? as|my (?:job|role|position|title) is)(?: a| an| the)?\s+([^.,]+)",
    r"i (?:lead|manage|run|head|oversee)\s+([^.,]+)",
]

COMPANY_PATTERNS = [
    r"(?:my |our )(?:company|startup|business|firm|organization|org)(?: is)?\s+(?:called\s+)?([A-Z][A-Za-z0-9]+(?:[-\s][A-Z]?[A-Za-z0-9]+)*)",
    r"(?:i |we )(?:founded|started|co-?founded|built|created|launched)\s+([A-Z][A-Za-z0-9]+(?:[-\s][A-Z]?[A-Za-z0-9]+)*)",
    r"(?:co-?founder|founder|CEO|CTO|CMO|COO|CIO)\s+(?:of|at)\s+([A-Z][A-Za-z0-9]+(?:[-\s][A-Z]?[A-Za-z0-9]+)*)",
    r"(?:of|at)\s+([A-Z][A-Za-z0-9]+(?:[-\s][A-Z]?[A-Za-z0-9]+)*)\.\s+(?:We|I|Our)",
]

PROJECT_PATTERNS = [
    r"(?:working on|building|developing|creating)\s+(?:a |an |the )?([^.,]+?)(?:\s+(?:which|that|to|for)|\.|,|$)",
    r"(?:my |our )(?:project|product|platform|app|tool|system|solution)\s+(?:is\s+)?(?:called\s+)?([A-Z][A-Za-z0-9]+(?:[-\s][A-Z]?[A-Za-z0-9]+)*)?",
]

TECH_KEYWORDS = {
    "languages": [
        "python",
        "javascript",
        "typescript",
        "java",
        "c++",
        "c#",
        "ruby",
        "rust",
        "swift",
        "kotlin",
        "php",
        "scala",
        "matlab",
        "sql",
        "html",
        "css",
        "golang",
    ],
    "frameworks": [
        "react",
        "angular",
        "vue",
        "django",
        "flask",
        "fastapi",
        "express",
        "next.js",
        "nextjs",
        "nuxt",
        "rails",
        "spring",
        "laravel",
        ".net",
        "tensorflow",
        "pytorch",
        "keras",
        "langchain",
    ],
    "platforms": [
        "aws",
        "gcp",
        "azure",
        "vercel",
        "netlify",
        "heroku",
        "docker",
        "kubernetes",
        "linux",
        "ubuntu",
        "windows",
        "macos",
        "ec2",
        "lambda",
        "cloudflare",
    ],
    "databases": [
        "postgresql",
        "postgres",
        "mysql",
        "mongodb",
        "redis",
        "elasticsearch",
        "dynamodb",
        "firebase",
        "supabase",
        "convex",
        "planetscale",
        "pinecone",
    ],
    "tools": [
        "git",
        "github",
        "gitlab",
        "jira",
        "confluence",
        "slack",
        "notion",
        "figma",
        "vscode",
        "vim",
        "cursor",
        "copilot",
        "pytest",
        "ruff",
    ],
}

TECH_FALSE_POSITIVES = {"go", "r", "c", "rust", "swift", "ruby"}

DOMAIN_KEYWORDS = {
    "healthcare": [
        "clinical",
        "medical",
        "health",
        "patient",
        "hospital",
        "physician",
        "doctor",
        "nurse",
        "diagnosis",
        "treatment",
        "fda",
        "hipaa",
        "ehr",
        "emr",
        "ctcae",
        "oncology",
        "cancer",
        "therapy",
        "pharmaceutical",
        "drug",
        "trial",
    ],
    "finance": [
        "financial",
        "banking",
        "investment",
        "trading",
        "portfolio",
        "stock",
        "bond",
        "crypto",
        "blockchain",
        "fintech",
        "payment",
        "lending",
        "insurance",
    ],
    "ai_ml": [
        "machine learning",
        "deep learning",
        "neural network",
        "nlp",
        "computer vision",
        "ai",
        "artificial intelligence",
        "model",
        "training",
        "inference",
        "llm",
        "gpt",
        "transformer",
        "rag",
        "embedding",
    ],
    "legal": [
        "legal",
        "law",
        "attorney",
        "lawyer",
        "contract",
        "compliance",
        "regulatory",
        "litigation",
        "intellectual property",
        "patent",
        "trademark",
    ],
    "education": [
        "education",
        "learning",
        "teaching",
        "student",
        "course",
        "curriculum",
        "school",
        "university",
        "academic",
        "research",
    ],
}

RELATIONSHIP_PATTERNS = [
    r"(?:partner(?:ship|ed|ing)?|collaborat(?:e|ion|ing)|work(?:ing)? with)\s+([A-Z][A-Za-z0-9\s-]+?)(?:\s+(?:on|to|for)|\.|,|$)",
    r"(?:advisor|mentor|investor|client|customer)\s+(?:from|at|is)\s+([A-Z][A-Za-z0-9\s-]+)",
    r"([A-Z][A-Za-z0-9\s-]+?)\s+(?:is our|are our)\s+(?:partner|client|investor|advisor)",
]

RELATIONSHIP_TYPE_PATTERNS = {
    "partner": [
        r"(?:partner(?:ship|ing)?|collaborat(?:e|ing|ion))\s+(?:with|and)\s+([A-Z][A-Za-z0-9\s-]+?)(?:\s+(?:on|to|for)|\.|,|$)",
        r"([A-Z][A-Za-z0-9\s-]+?)\s+(?:is our|are our)\s+(?:partner|collaborator)",
    ],
    "mentor": [
        r"(?:mentor(?:ed)?|mentoring)\s+(?:by|from|is)\s+([A-Z][A-Za-z0-9\s-]+)",
        r"([A-Z][A-Za-z0-9\s-]+?)\s+(?:is my|as my)\s+mentor",
    ],
    "advisor": [
        r"(?:advisor|advised)\s+(?:by|from|is)\s+([A-Z][A-Za-z0-9\s-]+)",
        r"([A-Z][A-Za-z0-9\s-]+?)\s+(?:is an?|as an?)\s+advisor",
    ],
    "investor": [
        r"(?:investor|invested|backed|funded)\s+(?:by|from|is)\s+([A-Z][A-Za-z0-9\s-]+)",
        r"([A-Z][A-Za-z0-9\s-]+?)\s+(?:invested|is an investor)",
    ],
    "client": [
        r"(?:client|customer)s?\s+(?:include|is|are)\s+([A-Z][A-Za-z0-9\s-]+)",
        r"([A-Z][A-Za-z0-9\s-]+?)\s+(?:is a|as a)\s+(?:client|customer)",
    ],
    "competitor": [
        r"(?:competitor|competing)\s+(?:with|is|like)\s+([A-Z][A-Za-z0-9\s-]+)",
        r"(?:vs|versus|compared to)\s+([A-Z][A-Za-z0-9\s-]+)",
    ],
}

VALUE_PATTERNS = [
    r"i (?:believe|think|value|prioritize|care about)\s+([^.,]+)",
    r"(?:important to me|matters to me|i always)\s+([^.,]+)",
    r"(?:my |our )(?:principle|value|philosophy|approach) is\s+([^.,]+)",
]

CURRENT_INDICATORS = [
    "currently",
    "now",
    "right now",
    "at the moment",
    "these days",
    "lately",
    "recently",
    "this week",
    "this month",
    "this year",
    "2024",
    "2025",
    "2026",
]
PAST_INDICATORS = ["used to", "previously", "formerly", "back when", "in the past", "years ago", "last year", "before"]
FUTURE_INDICATORS = ["planning to", "going to", "will", "want to", "hope to", "aiming to", "targeting", "goal is"]

NEGATION_PATTERNS = [
    r"(?:i|we)\s+(?:don'?t|do not|never|won'?t|will not|refuse to|stopped)\s+(?:use|like|want|prefer|work with|recommend|trust|support)\s+([^.,]+)",
    r"(?:i|we)\s+(?:avoid|stay away from|steer clear of|moved away from|dropped|ditched|abandoned)\s+([^.,]+)",
    r"(?:i|we)\s+(?:hate|dislike|can'?t stand|am not a fan of|am against)\s+([^.,]+)",
    r"(?:not|no longer)\s+(?:using|a fan of|interested in|working with)\s+([^.,]+)",
    r"(?:switched|migrated|moved)\s+(?:from|away from)\s+([A-Za-z0-9]+)\s+(?:to|over to)",
    r"(?:i|we)\s+(?:quit|stopped|gave up on|abandoned)\s+([^.,]+)",
]
NEGATION_KEYWORDS = {
    "never",
    "don't",
    "dont",
    "won't",
    "wont",
    "avoid",
    "hate",
    "dislike",
    "stopped",
    "quit",
    "abandoned",
    "dropped",
    "switched from",
    "no longer",
    "not anymore",
    "refuse",
    "against",
}

PREFERENCES_PATTERNS = [
    r"(?:i|we)\s+(?:prefer|like|love|enjoy|favor)\s+([^.,]+?)(?:\s+(?:over|to|rather than|instead of)|[.,]|$)",
    r"(?:my|our)\s+(?:preferred|favorite|go-to|default)\s+(?:tool|approach|method|style|way|stack)\s+(?:is|for)\s+([^.,]+)",
    r"(?:i|we)\s+(?:always|usually|typically|generally|tend to)\s+([^.,]+?)(?:\s+(?:when|for|because)|[.,]|$)",
    r"i(?:'m| am)\s+(?:a|an)\s+([A-Za-z-]+)\s+(?:person|type|kind of (?:person|developer|engineer))",
    r"(?:my|our)\s+(?:style|approach|way)\s+(?:is|involves?)\s+([^.,]+)",
]
PREFERENCE_INDICATORS = {
    "prefer",
    "like",
    "love",
    "favor",
    "enjoy",
    "always",
    "usually",
    "typically",
    "my style",
    "my approach",
    "go-to",
    "favorite",
}

CONSTRAINTS_PATTERNS = [
    r"(?:budget|funding|spend|cost)\s+(?:is|of|around|about|under|limit(?:ed to)?)\s*\$?([\d,]+(?:\.\d+)?(?:\s*(?:k|K|M|million|billion))?)",
    r"\$?([\d,]+(?:\.\d+)?(?:\s*(?:k|K|M|million|billion))?)\s+(?:budget|funding|to spend)",
    r"(?:can(?:'t| not)?|cannot)\s+(?:spend|afford)\s+(?:more than|over)\s*\$?([\d,]+)",
    r"(?:deadline|timeline|timeframe|due|launch|go-live)\s+(?:is|in|by|within)\s+([^.,]+)",
    r"(?:need|must|have to)\s+(?:finish|complete|deliver|launch|ship)\s+(?:by|in|within)\s+([^.,]+)",
    r"([0-9]+)\s*(?:weeks?|months?|days?|years?)\s+(?:timeline|deadline|to (?:launch|complete|finish))",
    r"(?:team|staff|engineers?|developers?)\s+(?:of|is|are)\s+([0-9]+(?:\s+(?:people|engineers?|developers?))?)",
    r"([0-9]+)\s+(?:person|people|engineer|developer)s?\s+(?:team|working on)",
    r"(?:only|just)\s+([0-9]+)\s+(?:of us|people|engineers?)",
    r"(?:must|have to|need to|required to)\s+(?:use|support|integrate with|be compatible with)\s+([^.,]+)",
    r"(?:limited|restricted|constrained)\s+(?:to|by)\s+([^.,]+)",
    r"(?:must|need to)\s+(?:comply with|meet|follow|adhere to)\s+([A-Z]{2,}(?:\s+[A-Za-z]+)*)",
    r"([A-Z]{2,})\s+(?:compliant|compliance|certified|requirements?)",
]
CONSTRAINT_TYPES = {
    "budget": ["budget", "funding", "cost", "spend", "afford", "$", "k", "million"],
    "timeline": ["deadline", "timeline", "weeks", "months", "days", "by", "due", "launch"],
    "team": ["team", "people", "engineers", "developers", "staff", "headcount"],
    "technical": ["must use", "limited to", "compatible", "integrate", "support"],
    "regulatory": ["comply", "hipaa", "gdpr", "pci", "sox", "fda", "regulation"],
}

CORRECTIONS_PATTERNS = [
    r"(?:i meant|actually)\s+([A-Za-z0-9]+)\s+not\s+([A-Za-z0-9]+)",
    r"(?:actually|sorry|correction|to clarify|let me correct|i misspoke),?\s+(?:i meant|it(?:'s| is)|that(?:'s| is)|it should be|i mean)\s+([^.,]+)",
    r"(?:not|no,?)\s+([A-Za-z0-9\s]+),?\s+(?:but|rather|i meant?|it(?:'s| is))\s+([A-Za-z0-9\s]+)",
    r"(?:i said|when i said)\s+([^,]+),?\s+(?:i meant|but i meant|i actually meant)\s+([^.,]+)",
    r"(?:that(?:'s| is)|i was)\s+wrong,?\s+(?:it(?:'s| is)|it should be|the correct (?:answer|thing) is)\s+([^.,]+)",
    r"(?:typo|error|mistake),?\s+(?:i meant|should be|it(?:'s| is))\s+([^.,]+)",
    r"(?:wait|hold on|no wait),?\s+(?:i meant?|it(?:'s| is)|that(?:'s| is))\s+([^.,]+)",
    r"(?:let me (?:rephrase|restate|clarify)|to be (?:clear|more precise)),?\s+([^.,]+)",
]
CORRECTION_KEYWORDS = {
    "actually",
    "correction",
    "sorry",
    "i meant",
    "typo",
    "mistake",
    "wrong",
    "error",
    "let me correct",
    "to clarify",
    "i misspoke",
    "wait",
    "hold on",
}

STRIP_PREFIXES = ["in ", "that ", "the ", "a ", "an ", "to ", "for ", "with ", "about "]
NOISE_WORDS = {
    "strategies",
    "doing",
    "things",
    "stuff",
    "something",
    "anything",
    "working",
    "building",
    "creating",
    "developing",
    "using",
    "good",
    "great",
    "best",
    "better",
    "important",
    "new",
    "old",
    "first",
    "last",
    "next",
    "other",
}
SKIP_WORDS = {
    "the",
    "this",
    "that",
    "what",
    "when",
    "where",
    "which",
    "who",
    "how",
    "why",
    "our",
    "my",
    "your",
    "their",
    "his",
    "her",
    "its",
    "we",
    "they",
    "he",
    "she",
    "it",
    "you",
    "i",
    "also",
    "just",
    "now",
    "then",
    "here",
    "there",
    "please",
    "thanks",
    "thank",
    "hello",
    "hi",
    "hey",
    "currently",
    "recently",
    "basically",
    "actually",
}

ROLE_HINT_WORDS = {
    "advisor",
    "analyst",
    "architect",
    "consultant",
    "cto",
    "ceo",
    "cfo",
    "cio",
    "ciso",
    "coo",
    "cmo",
    "designer",
    "developer",
    "director",
    "doctor",
    "engineer",
    "founder",
    "head",
    "lead",
    "lawyer",
    "manager",
    "mentor",
    "nurse",
    "officer",
    "physician",
    "principal",
    "product",
    "professor",
    "researcher",
    "scientist",
    "senior",
    "staff",
    "student",
    "teacher",
    "vp",
}
ROLE_GUARD_WORDS = {"busy", "fan", "kind", "person", "thing", "stuff", "type"}
PROJECT_HINT_WORDS = {
    "agent",
    "api",
    "app",
    "assistant",
    "automation",
    "backend",
    "dashboard",
    "feature",
    "frontend",
    "integration",
    "library",
    "migration",
    "mobile",
    "pipeline",
    "platform",
    "plugin",
    "product",
    "prototype",
    "repo",
    "sdk",
    "service",
    "site",
    "stack",
    "system",
    "tool",
    "workflow",
}
PRIORITY_ACTION_HINT_WORDS = {
    "build",
    "creating",
    "deploy",
    "design",
    "document",
    "explore",
    "fix",
    "improve",
    "integrate",
    "launch",
    "migrate",
    "prototype",
    "refactor",
    "research",
    "rewrite",
    "ship",
    "support",
    "test",
}

ALL_TECH_KEYWORDS = {keyword for keywords in TECH_KEYWORDS.values() for keyword in keywords}
ALL_DOMAIN_KEYWORDS = {keyword for keywords in DOMAIN_KEYWORDS.values() for keyword in keywords}

PII_PATTERNS = [
    ("EMAIL", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    ("SSN", r"\b\d{3}-\d{2}-\d{4}\b"),
    (
        "CREDIT_CARD",
        r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3(?:0[0-5]|[68][0-9])[0-9]{11}|6(?:011|5[0-9]{2})[0-9]{12})\b",
    ),
    ("PRIVATE_KEY", r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    ("AWS_KEY", r"\bAKIA[0-9A-Z]{16}\b"),
    ("GITHUB_TOKEN", r"\bgh[ps]_[A-Za-z0-9_]{36,}\b"),
    ("API_KEY", r"(?:sk_live_[A-Za-z0-9]{24,}|sk-(?:ant-)?[A-Za-z0-9]{32,}|api[_-]?key[=:\s]+[A-Za-z0-9_\-]{20,})"),
    ("BEARER_TOKEN", r"\bBearer\s+[A-Za-z0-9._\-]{20,}\b"),
    ("DATABASE_URL", r"(?:postgres|mysql|mongodb|redis)://[^\s]+@[^\s]+"),
    ("IP_ADDRESS", r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"),
    ("STREET_ADDRESS", r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s+){1,3}(?:St|Ave|Blvd|Dr|Rd|Ln|Ct|Way|Pl|Cir|Ter|Pkwy)\.?\b"),
    ("PHONE", r"(?:\+?1[-.\s]?)?(?:\(?[0-9]{3}\)?[-.\s]?)[0-9]{3}[-.\s]?[0-9]{4}\b"),
]


class PIIRedactor:
    """Replaces PII in text with typed placeholders like [EMAIL], [PHONE], etc."""

    def __init__(self, custom_patterns: dict[str, str] | None = None):
        self._patterns: list[tuple[str, re.Pattern]] = []
        for label, pattern in PII_PATTERNS:
            self._patterns.append((label, re.compile(pattern)))
        if custom_patterns:
            for label, pattern in custom_patterns.items():
                self._patterns.append((label, re.compile(pattern)))
        self._counts: dict[str, int] = defaultdict(int)
        self._total: int = 0

    def redact(self, text: str) -> str:
        """Replace all PII matches with [TYPE] placeholders."""
        for label, compiled in self._patterns:

            def _replacer(match, _label=label):
                self._counts[_label] += 1
                self._total += 1
                return f"[{_label}]"

            text = compiled.sub(_replacer, text)
        return text

    def get_summary(self) -> dict:
        """Return redaction statistics. Never includes original PII values."""
        return {
            "redaction_applied": True,
            "total_redactions": self._total,
            "by_type": dict(self._counts),
        }


__all__ = [
    "ALL_DOMAIN_KEYWORDS",
    "ALL_TECH_KEYWORDS",
    "COMPANY_PATTERNS",
    "CONSTRAINTS_PATTERNS",
    "CONSTRAINT_TYPES",
    "CORRECTIONS_PATTERNS",
    "CORRECTION_KEYWORDS",
    "CURRENT_INDICATORS",
    "DOMAIN_KEYWORDS",
    "FUTURE_INDICATORS",
    "IDENTITY_PATTERNS",
    "NEGATION_PATTERNS",
    "NEGATION_KEYWORDS",
    "NOISE_WORDS",
    "PAST_INDICATORS",
    "PIIRedactor",
    "PII_PATTERNS",
    "PREFERENCES_PATTERNS",
    "PREFERENCE_INDICATORS",
    "PRIORITY_ACTION_HINT_WORDS",
    "PROJECT_HINT_WORDS",
    "PROJECT_PATTERNS",
    "RELATIONSHIP_PATTERNS",
    "RELATIONSHIP_TYPE_PATTERNS",
    "ROLE_GUARD_WORDS",
    "ROLE_HINT_WORDS",
    "ROLE_PATTERNS",
    "SKIP_WORDS",
    "STRIP_PREFIXES",
    "TECH_FALSE_POSITIVES",
    "TECH_KEYWORDS",
    "VALUE_PATTERNS",
]
