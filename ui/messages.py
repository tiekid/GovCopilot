"""Shared user-facing status text for the UI layer.

Centralized so the same wording is used everywhere a given condition
is reported, instead of being duplicated (and risking drift) across
ui/analysis_worker.py, ui/pipeline_worker.py, and ui/main_window.py.
"""

GEMINI_NOT_CONFIGURED_MESSAGE = (
    "Chưa cấu hình Google Gemini API.\n"
    "Vui lòng nhập API Key trong Cài đặt."
)

# Shown for any GeminiProviderError reaching the UI (request failure,
# quota, retired model with no replacement, ...) — never the raw
# SDK/API error text.
GEMINI_UNAVAILABLE_MESSAGE = (
    "Không thể kết nối tới Google Gemini. Vui lòng thử lại sau."
)
