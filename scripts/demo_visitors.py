"""Who visited the public demo: one row per visitor address, with the organization that owns it.

Usage: uv run python scripts/demo_visitors.py [--days 14] [--include-me]

Reads page views (with the visitor's address and browser, logged by the request middleware in
api/main.py) from CloudWatch Logs Insights, drops bots and your own current address, and looks up
each address's registered owner through RDAP, the public registries' lookup (rdap.org sends it to
ARIN, RIPE, and so on). An organization name means a company or university network; a home ISP
(Comcast, Verizon) or a cloud provider means it can't be told. It never names a person.
"""

import argparse
import ipaddress
import json
import time
import urllib.request
from datetime import UTC, datetime, timedelta

import boto3

LOG_GROUP = "/ecs/ehr-rwe-eln"
BOTS = ("bot", "crawl", "spider", "slurp", "curl", "python", "go-http", "headless", "scan")
QUERY = """
fields @timestamp, client, user_agent, path
| filter ispresent(client)
| sort @timestamp asc
| limit 10000
"""


def my_address() -> str:
    with urllib.request.urlopen("https://checkip.amazonaws.com", timeout=10) as r:  # noqa: S310
        return r.read().decode().strip()


def owner(address: str) -> tuple[str, str]:
    """(organization, country) for an address from RDAP; empty strings when unknown. Only the
    registrant organization: RDAP also lists contacts, who are people, and those are skipped."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return "", ""
    request = urllib.request.Request(
        f"https://rdap.org/ip/{ip}", headers={"Accept": "application/rdap+json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as r:  # noqa: S310 (fixed https URL)
            data = json.load(r)
    except Exception:
        return "", ""
    for entity in data.get("entities", []):
        if "registrant" not in entity.get("roles", []):
            continue
        card = {f[0]: f[3] for f in entity.get("vcardArray", [None, []])[1]}
        if card.get("kind") == "org" and card.get("fn"):
            return card["fn"], data.get("country", "")
    return data.get("name", ""), data.get("country", "")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--include-me", action="store_true")
    args = parser.parse_args()

    logs = boto3.client("logs", region_name="us-east-1")
    end = datetime.now(UTC)
    query_id = logs.start_query(
        logGroupName=LOG_GROUP,
        startTime=int((end - timedelta(days=args.days)).timestamp()),
        endTime=int(end.timestamp()),
        queryString=QUERY,
    )["queryId"]
    while (result := logs.get_query_results(queryId=query_id))["status"] in (
        "Scheduled",
        "Running",
    ):
        time.sleep(1)
    rows = [{f["field"]: f["value"] for f in row} for row in result["results"]]

    me = None if args.include_me else my_address()
    visitors: dict[str, dict] = {}
    for row in rows:
        agent = row.get("user_agent", "")
        if row["client"] == me or any(b in agent.lower() for b in BOTS):
            continue
        v = visitors.setdefault(
            row["client"], {"first": row["@timestamp"][:16], "pages": [], "agent": agent}
        )
        v["pages"].append(row["path"])

    print(
        f"{len(rows)} page views logged in {args.days} days; {len(visitors)} visitors after"
        f" dropping bots{'' if args.include_me else ' and you'}\n"
    )
    for address, v in visitors.items():
        org, country = owner(address)
        pages = ", ".join(dict.fromkeys(v["pages"]))
        print(f"{v['first']}  {org or '(unknown)'} [{country}]  {len(v['pages'])} views: {pages}")
        print(f"    {v['agent'][:110]}")
        time.sleep(0.5)


if __name__ == "__main__":
    main()
