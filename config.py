from dotenv import load_dotenv
import os

# Đọc file .env
load_dotenv()

# Cấu hình hệ thống VBĐH
VB_URL = os.getenv("VB_URL", "")
USERNAME = os.getenv("USERNAME", "")
PASSWORD = os.getenv("PASSWORD", "")

# Multi-provider AI configuration. AIInvitationExtractor never reads any
# of this directly — only providers/provider_factory.py does, selecting
# one concrete AIProvider by AI_PROVIDER. Everything above AIProvider
# stays provider-independent.
#
# Default is "ollama" — local-first, no key required. Gemini is an
# optional acceleration: set AI_PROVIDER=gemini to use it exclusively,
# or AI_PROVIDER=auto to prefer it with automatic fallback to Ollama
# (see providers/provider_factory.py::_create_auto_provider).
AI_PROVIDER = os.getenv("AI_PROVIDER", "ollama")

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0"))
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "5m")

# No hardcoded model name: empty means "not yet selected". GeminiProvider
# discovers the first Gemini model that supports text generation on
# first use (or via Settings > Test connection) and persists it here
# via config_store.set_config_value — see providers/gemini_provider.py.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "")

# Backs the OpenAIProvider stub (providers/openai_provider.py), which
# raises NotImplementedError — kept configurable so selecting it is a
# one-line config change once implemented.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

# Backs the ClaudeProvider stub (providers/claude_provider.py), which
# raises NotImplementedError.
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4")