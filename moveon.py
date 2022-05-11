import copy
from dataclasses import dataclass
import json
import logging
from typing import AsyncIterable, Optional, Tuple
import anyio
import httpx
from parsel import Selector


class XmlResponseError(Exception):
    def __init__(self, response, message="Unexpected response") -> None:
        self.response = response
        self.message = message
        super().__init__(self.message)

    def __str__(self):
        return f"{self.message}: {self.response}"


def _xpath_nonempty(selector, xpath: str, error_context: Optional[str] = None):
    result = selector.xpath(xpath).get()
    if not result:
        error_context = f" ({error_context})" if error_context else ""
        raise XmlResponseError(
            selector.extract(),
            message=f"Xpath failed{error_context}: {xpath}",
        )
    return result


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

        xml = Selector(response.text, type="xml")

        status = xml.xpath("/rest/queue/status/text()").get()
        if status != "success":
            raise XmlResponseError(response, message="Unsuccessful status")

        response_data = _xpath_nonempty(xml, "/rest/queue/response/text()")
        return json.loads(response_data)["queueId"]

    async def get_raw(self, queue_id: int) -> httpx.Response:
        """Get status of a queued request (may not be ready)"""
        return await self.client.post(self.url, data={"method": "get", "id": queue_id})

    async def get(self, queue_id: int, retry_time: Optional[float] = None) -> Selector:
        """Wait until request is ready, returning the response body"""

        async def next_request():
            response = await self.get_raw(queue_id)
            response.raise_for_status()

            xml = Selector(response.text, type="xml")
            status = xml.xpath("/rest/get/status/text()").get()

            return response, xml, status

        response, xml, status = await next_request()

        retry_time = retry_time or self.retry_time
        while status != "success":
            if status != "processing" and status != "queued":
                raise XmlResponseError(response, message="Unexpected get status")

            logging.info(f'Retrying get method with status "{status}"')
            await anyio.sleep(retry_time)
            response, xml, status = await next_request()

        response_data = xml.xpath("/rest/get/response")
        if len(response_data) != 1:
            raise XmlResponseError(response, message="Must have one response body")

        return response_data[0]

    async def queue_and_get(
        self, data: dict, retry_time: Optional[float] = None
    ) -> Selector:
        """Queue the request, wait until it is completed, return the response body"""
        request_id = await self.queue(data)
        return await self.get(request_id, retry_time)

    async def iter_pages(
        self, data: dict, page_limit: int = 0, retry_time: Optional[float] = None
    ) -> AsyncIterable[Tuple[int, Selector]]:
        """
        Runs queue_and_get for all availiable pages,
        starting with data["data"]["page"]
        """

        # Don't overwrite 'page' field of the original request
        data = copy.deepcopy(data)

        logging.info("Requesting page {}/?".format(data["data"]["page"]))
        current_xml = await self.queue_and_get(data, retry_time)

        current_page = int(_xpath_nonempty(current_xml, "data/page/text()"))
        total_pages = int(_xpath_nonempty(current_xml, "data/total/text()"))

        yield current_page, current_xml

        if page_limit > 0:
            total_pages = min(page_limit, total_pages)

        for page in range(current_page + 1, total_pages + 1):
            logging.info(f"Requesting page {page}/{total_pages}")

            data["data"]["page"] = page
            current_xml = await self.queue_and_get(data, retry_time)
            yield page, current_xml
