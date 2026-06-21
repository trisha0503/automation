# import logging
# from contextlib import asynccontextmanager
# from dotenv import load_dotenv
# load_dotenv()

# from fastapi import FastAPI
# from config import SERVER_PORT
# from core.queue import consumer_manager
# from api.routes import orangehrm_router

# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
# )


# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     consumer_manager.start_all()
#     yield
#     await consumer_manager.stop_all()


# app = FastAPI(
#     title="OrangeHRM Automation API",
#     version="1.0.0",
#     lifespan=lifespan,
# )

# app.include_router(orangehrm_router)


# @app.get("/health")
# async def health():
#     return {"status": "ok"}


# if __name__ == "__main__":
#     import uvicorn
#     import multiprocessing
#     multiprocessing.freeze_support()
#     uvicorn.run(
#         "main:app",
#         host="0.0.0.0",
#         port=SERVER_PORT,
#         reload=False,
#     )

# ---------------Without SQS--------------

import logging
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from config import SERVER_PORT
from api.routes import orangehrm_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)

app = FastAPI(
    title="OrangeHRM Automation API",
    version="1.0.0",
)

app.include_router(orangehrm_router)

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    import multiprocessing
    multiprocessing.freeze_support()
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=SERVER_PORT,
        reload=False,
    )