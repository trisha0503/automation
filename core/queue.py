"""
core/queue.py — AWS SQS queue management, producer, and consumer.
"""
import json
import asyncio
import logging
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from config import (
    AWS_SQS_REGION,
    AWS_SQS_ACCESS_KEY_ID,
    AWS_SQS_SECRET_KEY,
    SQS_QUEUES,
    SQS_VISIBILITY_TIMEOUT,
)

logger = logging.getLogger(__name__)


# ── SQS CLIENT ────────────────────────────────────────────────────────────────
def _get_sqs_client():
    return boto3.client(
        "sqs",
        region_name=AWS_SQS_REGION,
        aws_access_key_id=AWS_SQS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SQS_SECRET_KEY,
    )


_queue_url_cache: dict[str, str] = {}


def _get_or_create_queue_url(scraper: str) -> str:
    if scraper in _queue_url_cache:
        return _queue_url_cache[scraper]

    queue_name = SQS_QUEUES.get(scraper)
    if not queue_name:
        raise RuntimeError(
            f"No SQS queue configured for '{scraper}'. "
            f"Add SQS_QUEUE_{scraper.upper()}=<queue-name> to .env"
        )

    sqs = _get_sqs_client()

    try:
        resp = sqs.get_queue_url(QueueName=queue_name)
        url  = resp["QueueUrl"]
        logger.info("[SQS] ✓ Queue found [%s]: %s", scraper, url)
        _queue_url_cache[scraper] = url
        return url

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code in (
            "AWS.SimpleQueueService.NonExistentQueue",
            "QueueDoesNotExist",
        ):
            logger.warning(
                "[SQS] Queue '%s' not found — creating...", queue_name
            )
            create_resp = sqs.create_queue(
                QueueName=queue_name,
                Attributes={
                    "VisibilityTimeout":             str(SQS_VISIBILITY_TIMEOUT),
                    "MessageRetentionPeriod":        "86400",
                    "ReceiveMessageWaitTimeSeconds": "20",
                },
            )
            url = create_resp["QueueUrl"]
            logger.info("[SQS] ✓ Queue created [%s]: %s", scraper, url)
            _queue_url_cache[scraper] = url
            return url
        else:
            raise RuntimeError(
                f"Failed to get SQS queue for '{scraper}': {e}"
            )


# ── PRODUCER ──────────────────────────────────────────────────────────────────
async def enqueue_job(scraper: str, dto: dict) -> None:
    try:
        loop      = asyncio.get_event_loop()
        sqs       = _get_sqs_client()
        queue_url = _get_or_create_queue_url(scraper)
        job_id    = str(dto.get("job_id", "unknown"))

        message_body = json.dumps({
            "scraper": scraper,
            "dto":     dto,
        })

        await loop.run_in_executor(
            None,
            lambda: sqs.send_message(
                QueueUrl=queue_url,
                MessageBody=message_body,
                MessageAttributes={
                    "scraper": {
                        "StringValue": scraper,
                        "DataType":    "String",
                    }
                },
            ),
        )
        logger.info(
            "[SQS] ✓ Message sent → [%s] job_id: %s", scraper, job_id
        )

    except RuntimeError:
        raise
    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"SQS send failed for '{scraper}': {e}")


# ── JOB HANDLERS ──────────────────────────────────────────────────────────────
async def run_orangehrm_automation(dto: dict) -> None:
    from scrapers.orangehrm.automation import OrangeHRMService
    await OrangeHRMService().run(dto)


JOB_HANDLERS: dict[str, callable] = {
    "orangehrm": run_orangehrm_automation,
    # add new scrapers here:
    # "newsite": run_newsite_automation,
}


# ── SQS CONSUMER ──────────────────────────────────────────────────────────────
class SQSConsumer:
    def __init__(self, scraper: str):
        if scraper not in JOB_HANDLERS:
            raise ValueError(f"Unknown scraper: '{scraper}'")

        self._scraper         = scraper
        self._sqs             = _get_sqs_client()
        self._queue_url       = _get_or_create_queue_url(scraper)
        self._handler         = JOB_HANDLERS[scraper]
        self._is_processing   = False
        self._should_continue = True
        self._polling_task    = None

    def start(self):
        logger.info(
            "[Consumer] ✓ Polling started — [%s] queue: %s",
            self._scraper,
            SQS_QUEUES.get(self._scraper)
        )
        self._polling_task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        logger.info("[Consumer] Stopping — [%s]", self._scraper)
        self._should_continue = False

        wait_count, max_wait = 0, 30
        while self._is_processing and wait_count < max_wait:
            logger.info(
                "[Consumer][%s] Waiting... (%d/%ds)",
                self._scraper, wait_count, max_wait
            )
            await asyncio.sleep(1)
            wait_count += 1

        if self._is_processing:
            logger.warning(
                "[Consumer][%s] ⚠ Forced shutdown", self._scraper
            )
        else:
            logger.info(
                "[Consumer][%s] ✓ Graceful shutdown", self._scraper
            )

        if self._polling_task:
            self._polling_task.cancel()

    async def _poll_loop(self):
        while self._should_continue:
            try:
                if not self._is_processing:
                    await self._poll_and_process()
            except Exception as e:
                logger.error(
                    "[Consumer][%s] Poll loop error: %s", self._scraper, e
                )
            await asyncio.sleep(2)
        logger.info("[Consumer][%s] Polling loop stopped", self._scraper)

    async def _poll_and_process(self):
        loop = asyncio.get_event_loop()
        try:
            response = await loop.run_in_executor(
                None,
                lambda: self._sqs.receive_message(
                    QueueUrl=self._queue_url,
                    MaxNumberOfMessages=1,
                    WaitTimeSeconds=20,
                    VisibilityTimeout=SQS_VISIBILITY_TIMEOUT,
                    MessageAttributeNames=["All"],
                    AttributeNames=["All"],
                ),
            )

            messages = response.get("Messages", [])
            if not messages:
                logger.debug(
                    "[Consumer][%s] No messages (polling...)", self._scraper
                )
                return

            message = messages[0]
            logger.info(
                "[Consumer][%s] 📨 Received: %s",
                self._scraper, message.get("MessageId")
            )

            self._is_processing = True
            try:
                await self._process_message(message)
                await self._delete_message(message.get("ReceiptHandle"))
                logger.info("[Consumer][%s] ✓ Done", self._scraper)
            except Exception as e:
                logger.error(
                    "[Consumer][%s] ✗ Failed: %s", self._scraper, e
                )
            finally:
                self._is_processing = False

        except Exception as e:
            logger.error(
                "[Consumer][%s] Poll error: %s", self._scraper, e
            )
            self._is_processing = False

    async def _process_message(self, message: dict):
        body   = json.loads(message.get("Body", "{}"))
        dto    = body.get("dto", {})
        job_id = dto.get("job_id", "unknown")

        logger.info(
            "[Consumer][%s] 🚀 Starting — job_id: %s",
            self._scraper, job_id
        )

        handler = self._handler
        start   = asyncio.get_event_loop().time()

        def run_in_thread():
            import asyncio as _asyncio
            loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(handler(dto))
            finally:
                loop.close()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, run_in_thread)

        duration = asyncio.get_event_loop().time() - start
        logger.info(
            "[Consumer][%s] ✓ Completed — job_id: %s in %.1fs",
            self._scraper, job_id, duration
        )

    async def _delete_message(self, receipt_handle: str):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._sqs.delete_message(
                QueueUrl=self._queue_url,
                ReceiptHandle=receipt_handle,
            ),
        )


# ── CONSUMER MANAGER ──────────────────────────────────────────────────────────
class ConsumerManager:
    def __init__(self):
        self._consumers: list[SQSConsumer] = []

    def start_all(self):
        for scraper in JOB_HANDLERS:
            try:
                consumer = SQSConsumer(scraper)
                consumer.start()
                self._consumers.append(consumer)
                logger.info(
                    "[ConsumerManager] ✓ Started — [%s]", scraper
                )
            except Exception as e:
                logger.error(
                    "[ConsumerManager] ✗ Failed [%s]: %s", scraper, e
                )

    async def stop_all(self):
        for consumer in self._consumers:
            await consumer.stop()
        logger.info("[ConsumerManager] All consumers stopped")


consumer_manager = ConsumerManager()