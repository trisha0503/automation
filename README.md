# OrangeHRM Automation 🤖

A production-grade automation system built with **FastAPI + 
Playwright + AWS SQS** that logs into the OrangeHRM HR portal,
searches employees by different logic, saves each profile as a PDF,
and stores metadata as JSON — all triggered asynchronously via
a REST API.

---

## 🏗️ Architecture
POST /orangehrm/download
↓
FastAPI Route
↓
AWS SQS Queue
↓
SQS Consumer (background polling)
↓
Playwright Automation
→ Login
→ Navigate to Employee List
→ Search by Department
→ Loop each Employee
→ Save Profile as PDF
→ Save Metadata as JSON
↓
Local Storage
downloads/orangehrm/{job_id}/
├── 1-John-Doe.pdf
├── 2-Jane-Smith.pdf
└── metadata.json
---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI |
| Automation | Playwright (Chromium) |
| Queue | AWS SQS |
| PDF generation | Playwright PDF + pypdf |
| Config | python-dotenv |
| HTTP client | httpx |
| Validation | Pydantic |

---

## 📁 Project Structure
orangehrm-automation/
├── api/
│   ├── init.py
│   ├── models.py          # Pydantic request models
│   └── routes.py          # FastAPI route definitions
├── core/
│   ├── init.py
│   ├── queue.py           # SQS producer, consumer, manager
│   └── pdf_handler.py     # PDF merge and cleanup utilities
├── scrapers/
│   ├── init.py
│   └── orangehrm/
│       ├── init.py
│       ├── automation.py  # Main Playwright automation
│       └── response.py    # Default response structure
├── downloads/             # Saved PDFs (gitignored)
├── screenshots/           # Screenshots (gitignored)
├── config.py              # Central environment config
├── main.py                # FastAPI entry point
├── requirements.txt
├── .env.example
└── .gitignore
---

## ⚙️ Setup

### Prerequisites
- Python 3.11+
- AWS account with SQS access
- pip

### 1. Clone the repo
```bash
git clone https://github.com/trisha0503/orangehrm-automation
cd orangehrm-automation
```

### 2. Create virtual environment
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Mac/Linux
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 4. Configure environment
```bash
cp .env.example .env
```

Edit `.env` with your values:
```env
ORANGEHRM_URL=https://opensource-demo.orangehrmlive.com
ORANGEHRM_USERNAME=Admin
ORANGEHRM_PASSWORD=admin123

AWS_SQS_REGION=ap-south-1
AWS_SQS_ACCESS_KEY_ID=your_key
AWS_SQS_SECRET_ACCESS_KEY=your_secret
SQS_QUEUE_ORANGEHRM=orangehrmScraperQueue
```

### 5. Run the server
```bash
python main.py

# or
uvicorn main:app --host 0.0.0.0 --port 3031 --reload
```

---

## 🚀 Usage

### Swagger UI
http://localhost:3031/docs

### Health check
```bash
curl http://localhost:3031/health
```

### Trigger automation
```bash
curl -X POST http://localhost:3031/orangehrm/download \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "001",
    "department": "IT",
    "max_employees": 5
  }'
```

### Response
```json
{
  "statusCode": 200,
  "message": "Job added to queue",
  "data": {
    "job_id": "001",
    "department": "IT",
    "max_employees": 5
  }
}
```

---

## 📂 Output

After automation completes, files are saved locally:
downloads/
└── orangehrm/
└── 001/
├── 1-John-Doe.pdf
├── 2-Jane-Smith.pdf
├── 3-Alice-Brown.pdf
└── metadata.json
screenshots/
└── orangehrm/
└── 001/
├── 1-login-success.pdf
├── 2-employee-list.pdf
├── 3-search-results.pdf
└── report-001.pdf      ← merged report

### metadata.json structure
```json
{
  "job_id": "001",
  "department": "IT",
  "total_employees": 5,
  "employees": [
    {
      "index": 1,
      "emp_id": "0001",
      "name": "John Doe",
      "job_title": "Software Engineer",
      "status": "Active",
      "department": "IT",
      "profile_url": "https://...",
      "job_id": "001"
    }
  ]
}
```

---

## 🔄 How the Queue Works
1. POST request received by FastAPI
2. Job serialized → sent to AWS SQS
3. SQSConsumer polls queue every 2 seconds
4. Message received → Playwright automation starts
5. Runs in separate thread (Windows event loop fix)
6. Message deleted from queue after success
7. On failure → message reappears after VisibilityTimeout

Key design decisions:
- **One consumer per scraper** — no blocking between sites
- **MaxNumberOfMessages=1** — one job at a time per queue
- **VisibilityTimeout=3600** — 1 hour for long automations
- **run_in_executor** — Playwright runs in fresh thread
  with its own event loop (required on Windows)

---

## ➕ Adding a New Scraper

**1. Create scraper folder:**
scrapers/
└── newsite/
├── init.py
├── automation.py   ← copy orangehrm/automation.py
└── response.py     ← copy orangehrm/response.py

**2. Add queue config in `.env`:**
```env
SQS_QUEUE_NEWSITE=newsiteScraperQueue
```

**3. Add to `config.py`:**
```python
SQS_QUEUES = {
    "orangehrm": os.getenv("SQS_QUEUE_ORANGEHRM", "..."),
    "newsite":   os.getenv("SQS_QUEUE_NEWSITE", "..."),  # ← add
}
```

**4. Add handler in `core/queue.py`:**
```python
async def run_newsite_automation(dto: dict) -> None:
    from scrapers.newsite.automation import NewSiteService
    await NewSiteService().run(dto)

JOB_HANDLERS = {
    "orangehrm": run_orangehrm_automation,
    "newsite":   run_newsite_automation,  # ← add
}
```

**5. Add route in `api/routes.py`:**
```python
from api.routes import orangehrm_router, newsite_router
app.include_router(newsite_router)
```

That's it — the consumer starts automatically on next launch.

---

## 🔑 Design Patterns

This project follows the same patterns used in
production university automation systems:

| Pattern | Purpose |
|---------|---------|
| `ActionError` | Wraps every UI step — clear failure messages |
| `PageHelper` | `safe_click` / `safe_fill` — no raw Playwright calls |
| `StatusTracker` | Tracks each step independently |
| `SQSConsumer` | One per scraper — parallel processing |
| `ConsumerManager` | Starts/stops all consumers on app lifecycle |
| `run_in_executor` | Playwright in fresh thread — Windows fix |

---

## 📋 Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SERVER_PORT` | API port | `3031` |
| `ORANGEHRM_URL` | Portal URL | - |
| `ORANGEHRM_USERNAME` | Login username | - |
| `ORANGEHRM_PASSWORD` | Login password | - |
| `AWS_SQS_REGION` | SQS region | `ap-south-1` |
| `AWS_SQS_ACCESS_KEY_ID` | AWS access key | - |
| `AWS_SQS_SECRET_ACCESS_KEY` | AWS secret key | - |
| `SQS_QUEUE_ORANGEHRM` | Queue name | `orangehrmScraperQueue` |
| `DOWNLOADS_DIR` | PDF save path | `./downloads` |
| `SCREENSHOTS_DIR` | Screenshot path | `./screenshots` |

---

## 📦 Requirements
fastapi==0.110.0
uvicorn==0.29.0
playwright==1.44.0
boto3==1.34.0
httpx==0.27.0
python-dotenv==1.0.0
pydantic==2.6.0
pypdf==4.2.0
---

## 📝 Notes

- Demo site resets credentials periodically —
  default is always `Admin / admin123`
- Set `headless=True` in `automation.py` for
  production/server environments
- AWS SQS queues are **auto-created** on startup
  if they don't exist — no manual setup needed
- Extend easily by adding new scrapers following
  the same `ActionError / PageHelper / StatusTracker`
  pattern

---

## 👩‍💻 Author

**Trisha Patra**
Full Stack Developer & Automation Engineer
[LinkedIn](https://www.linkedin.com/in/trisha-patra-582477242)
[GitHub](https://github.com/trisha0503)