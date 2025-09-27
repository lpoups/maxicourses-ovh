#!/usr/bin/env python3
"""Wrapper fetcher for Leclerc Drive relying on the manual CDP helper.

This fetcher delegates the whole navigation to ``manual_leclerc_cdp.run_manual_leclerc``
so that only the human-like method is maintained. It keeps the same CLI contract as
other fetch scripts (prints a JSON dict with status/price/etc.).

Mandate reminder: the canonical instructions live in
``collection_mandate.METHODS['leclerc_drive']`` and must not be bypassed.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from collection_mandate import get_method
from manual_leclerc_cdp import run_manual_leclerc

MANDATE = get_method("leclerc_drive")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


async def run() -> dict:
    if os.environ.get("USE_CDP") != "1":
        return {"status": "ERROR", "error": "Leclerc Drive nécessite USE_CDP=1"}
    result = await run_manual_leclerc(
        query=env("QUERY"),
        ean=env("EAN"),
        store_url=env("STORE_URL", "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-bruges.aspx"),
        cdp_url=env("CDP_URL", "http://127.0.0.1:9222"),
        human_delay_ms=int(os.environ.get("LECLERC_HUMAN_DELAY_MS", "5000")),
        result_delay_ms=int(os.environ.get("LECLERC_RESULT_DELAY_MS", "12000")),
        pdp_delay_ms=int(os.environ.get("LECLERC_PDP_DELAY_MS", "7000")),
        type_min_delay=int(os.environ.get("LECLERC_TYPE_MIN_MS", "80")),
        type_max_delay=int(os.environ.get("LECLERC_TYPE_MAX_MS", "180")),
    )
    # Drop debug info when invoked through the fetcher
    result.pop("debug", None)
    return result


if __name__ == "__main__":
    try:
        payload = asyncio.run(run())
        print(json.dumps(payload, ensure_ascii=False))
    except KeyboardInterrupt:
        sys.exit(1)
