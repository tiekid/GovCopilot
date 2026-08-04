from dotenv import load_dotenv
import os

# Đọc file .env
load_dotenv()

# Cấu hình hệ thống VBĐH
VB_URL = os.getenv("VB_URL", "")
USERNAME = os.getenv("USERNAME", "")
PASSWORD = os.getenv("PASSWORD", "")

# OpenAI API Key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")