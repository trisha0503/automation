# ---------------With SQS--------------

# from fastapi import APIRouter, HTTPException
# from api.models import ScrapeRequest
# from core.queue import enqueue_job

# orangehrm_router = APIRouter(
#     prefix="/orangehrm",
#     tags=["OrangeHRM"]
# )

# @orangehrm_router.post("/download")
# async def download_employees(request: ScrapeRequest):
#     try:
#         await enqueue_job("orangehrm", request.dict())
#         return {
#             "statusCode": 200,
#             "message":    "Job added to queue",
#             "data":       request.dict(),
#         }
#     except Exception as e:
#         raise HTTPException(status_code=400, detail=str(e))


# @orangehrm_router.get("/health")
# async def health():
#     return {"status": "ok"}



# ---------------Without SQS--------------

from fastapi import APIRouter, HTTPException
from api.models import ScrapeRequest
from scrapers.orangehrm.automation import OrangeHRMService

orangehrm_router = APIRouter(
    prefix="/orangehrm",
    tags=["OrangeHRM"]
)

@orangehrm_router.post("/download")
async def download_employees(request: ScrapeRequest):
    try:
        # run directly — no SQS needed
        service = OrangeHRMService()
        result  = await service.run(request.dict())
        return {
            "statusCode": 200,
            "message":    "Automation completed",
            "data":       result,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@orangehrm_router.get("/health")
async def health():
    return {"status": "ok"}