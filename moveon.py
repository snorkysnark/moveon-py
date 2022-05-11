import copy
from dataclasses import dataclass
import json
import logging
from typing import AsyncIterable, Optional
import anyio
import httpx
import xmltodict


class StatusError(Exception):
    def __init__(self, status, message="Unexpected status") -> None:
        self.status = status
        self.message = message
        super().__init__(self.message)

    def __str__(self):
        return f"{self.message}: {self.status}"


@dataclass
class MoveonClient:
    url: str
    client: httpx.AsyncClient
    retry_time: float = 0.2

    async def queue_raw(self, data: dict) -> httpx.Response:
        """Queues a request, without checking for errors"""
        flat_data = copy.deepcopy(data)
        flat_data["method"] = "queue"

        # 'data' and 'data.filters' fields must be strings, not dictionaries
        if "data" in flat_data:
            if "filters" in flat_data["data"]:
                flat_data["data"]["filters"] = json.dumps(flat_data["data"]["filters"])
            flat_data["data"] = json.dumps(flat_data["data"])

        return await self.client.post(self.url, data=flat_data)

    async def queue(self, data: dict) -> int:
        """Queues a request, returning request id"""
        response = await self.queue_raw(data)
        response.raise_for_status()

        xml = xmltodict.parse(response.text)
        status = xml["rest"]["queue"]["status"]

        if status != "success":
            raise StatusError(status)

        response_data = xml["rest"]["queue"]["response"]
        return json.loads(response_data)["queueId"]

    async def get_raw(self, queue_id: int) -> httpx.Response:
        """Get status of a queued request (may not be ready)"""
        return await self.client.post(self.url, data={"method": "get", "id": queue_id})

    async def get(self, queue_id: int, retry_time: Optional[float] = None) -> dict:
        """Wait until request is ready, returning the response body"""

        async def next_request():
            response = await self.get_raw(queue_id)
            response.raise_for_status()

            xml = xmltodict.parse(response.text)
            status = xml["rest"]["get"]["status"]

            return xml, status

        xml, status = await next_request()

        retry_time = retry_time or self.retry_time
        while status != "success":
            if status != "processing" and status != "queued":
                raise StatusError(status)

            logging.info(f'Retrying get method with status "{status}"')
            await anyio.sleep(retry_time)
            xml, status = await next_request()

        response_data = xml["rest"]["get"]["response"]

        # response["data"]["rows"] should always be a list
        if "data" in response_data and "rows" in response_data["data"]:
            rows = response_data["data"]["rows"]
            if not isinstance(rows, list):
                response_data["data"]["rows"] = [rows]

        return response_data

    async def queue_and_get(
        self, data: dict, retry_time: Optional[float] = None
    ) -> dict:
        """Queue the request, wait until it is completed, return the response body"""
        request_id = await self.queue(data)
        return await self.get(request_id, retry_time)

    async def iter_pages(
        self, data: dict, page_limit: int = 0, retry_time: Optional[float] = None
    ) -> AsyncIterable[dict]:
        """
        Runs queue_and_get for all availiable pages,
        starting with data["data"]["page"]
        """
    
        # Don't overwrite 'page' field of the original request
        data = copy.deepcopy(data)
    
        logging.info("Requesting page {}/?".format(data["data"]["page"]))
        current_xml = await self.queue_and_get(data, retry_time)
    
        current_page = int(current_xml["data"]["page"])
        total_pages = int(current_xml["data"]["total"])
    
        yield current_xml
    
        if page_limit > 0:
            total_pages = min(page_limit, total_pages)
    
        for page in range(current_page + 1, total_pages + 1):
            logging.info(f"Requesting page {page}/{total_pages}")
    
            data["data"]["page"] = page
            current_xml = await self.queue_and_get(data, retry_time)
            yield current_xml
