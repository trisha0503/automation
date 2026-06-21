import os
from dotenv import load_dotenv
load_dotenv()

# ── Server ────────────────────────────────────────────────────
SERVER_PORT      = int(os.getenv("SERVER_PORT", 3031))
SERVER_IP        = os.getenv("SERVER_IP", "localhost")

# ── Timeouts ──────────────────────────────────────────────────
TIMEOUT_MS       = int(os.getenv("TIMEOUT_MS_VALUE", 5000))
TIMEOUT_SHORT_MS = int(os.getenv("TIMEOUT_SHORT_MS_VALUE", 3000))

# ── OrangeHRM ─────────────────────────────────────────────────
ORANGEHRM_URL      = os.getenv("ORANGEHRM_URL", "")
ORANGEHRM_USERNAME = os.getenv("ORANGEHRM_USERNAME", "")
ORANGEHRM_PASSWORD = os.getenv("ORANGEHRM_PASSWORD", "")

# ── AWS SQS ───────────────────────────────────────────────────
AWS_SQS_REGION         = os.getenv("AWS_SQS_REGION", "ap-south-1")
AWS_SQS_ACCESS_KEY_ID  = os.getenv("AWS_SQS_ACCESS_KEY_ID", "")
AWS_SQS_SECRET_KEY     = os.getenv("AWS_SQS_SECRET_ACCESS_KEY", "")
SQS_VISIBILITY_TIMEOUT = int(os.getenv("SQS_VISIBILITY_TIMEOUT", 3600))

SQS_QUEUES = {
    "orangehrm": os.getenv("SQS_QUEUE_ORANGEHRM", "orangehrmScraperQueue"),
    # add more scrapers here
}

# ── Local Storage ─────────────────────────────────────────────
DOWNLOADS_DIR   = os.getenv("DOWNLOADS_DIR", "./downloads")
SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "./screenshots")