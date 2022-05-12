from argparse import ArgumentParser
from csv import DictReader, QUOTE_NONE
import logging
import httpx
import anyio

from moveon import MoveonClient


def id_map_from_csv(reader: DictReader) -> dict:
    id_map = {}
    for row in reader:
        id_from = row["Institution: ID"]
        id_to = row["Institution: ID target"]
        if id_from != id_to:
            id_map[id_from] = id_to

    return id_map


def find_contacts_for_institution(
    client: MoveonClient,
    institution_id,
    visible_columns="contact.id;contact.name;contact.institution_id;contact.institution",
    retry_time: float = 0.2,
):
    return client.iter_rows_in_all_pages(
        {
            "entity": "contact",
            "action": "list",
            "data": {
                "filters": {
                    "groupOp": "AND",
                    "rules": [
                        {
                            "field": "contact.institution_id",
                            "op": "eq",
                            "data": institution_id,
                        }
                    ],
                },
                "visibleColumns": visible_columns,
                "locale": "eng",
                "sidx": "contact.id",
                "sord": "asc",
                "_search": "true",
                "page": 1,
                "rows": 100,
            },
        },
        retry_time=retry_time,
    )


def update_contact(
    client: MoveonClient, contact_id, new_institution_id, retry_time: float = 0.2
):
    return client.queue_and_get(
        {
            "entity": "contact",
            "action": "save",
            "data": {
                "entity": "contact",
                "contact.id": contact_id,
                "contact.institution_id": new_institution_id,
            },
        },
        retry_time=retry_time,
    )


async def apply_map(
    id_map: dict, url: str, cert: httpx._types.CertTypes, retry_time: float
):
    async with MoveonClient(url, httpx.AsyncClient(cert=cert)) as client:
        for id_from, id_to in id_map.items():
            logging.info("Searching contacts for institution_id " + id_from)
            async for row in find_contacts_for_institution(
                client, id_from, retry_time=retry_time
            ):
                logging.info(f"Found {row}")
                contact_id = row["contact.id"]
                logging.info(
                    f"Remapping institution_id {id_from} -> {id_to} for contact {contact_id}"
                )
                logging.info(
                    await update_contact(
                        client, contact_id, id_to, retry_time=retry_time
                    )
                )


if __name__ == "__main__":
    argp = ArgumentParser(description="Remap institution_id of contacts")
    argp.add_argument(
        "map_tsv",
        help="Tab-delimited csv with fields 'Institution: ID' and 'Institution: ID target'",
    )
    argp.add_argument(
        "-c", "--cert", default="moveon.cert", help="Path to ssl certificate"
    )
    argp.add_argument(
        "-k", "--key", default="moveon.key", help="Path to certificate key"
    )
    argp.add_argument(
        "--url",
        default="https://urfu02-api.moveonru.com/restService/index.php?version=3.0",
        help="MoveOn API url",
    )
    argp.add_argument(
        "--retry-time", type=float, default=0.2, help="Delay between retrying requests"
    )
    argp.add_argument("-l", "--log", default=None, help="Log file path")
    argp.add_argument("-v", "--loglevel", default=logging.INFO, help="Log level")

    args = argp.parse_args()
    logging.basicConfig(level=args.loglevel, filename=args.log)

    with open(args.map_tsv) as tsv_file:
        id_map = id_map_from_csv(
            DictReader(tsv_file, delimiter="\t", quoting=QUOTE_NONE)
        )

        """
        Benefits of async are not currently utilised,
        but it wraps more nicely around MoveOn's API
        """
        anyio.run(apply_map, id_map, args.url, (args.cert, args.key), args.retry_time)
