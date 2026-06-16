"""Harvester registry."""

from __future__ import annotations

from typing import Any, Protocol

from .sources import acl_anthology, cvf, dblp, neurips, openreview, papercopilot, pmlr, rss, siggraph


class Harvester(Protocol):
    def supports(self, venue_key: str, year: int) -> bool: ...

    def harvest(self, venue_key: str, year: int) -> dict[str, Any]: ...


HARVESTERS: dict[str, Harvester] = {
    "openreview": openreview,
    "cvf": cvf,
    "neurips": neurips,
    "acl_anthology": acl_anthology,
    "dblp": dblp,
    "pmlr": pmlr,
    "rss": rss,
    "siggraph": siggraph,
    "siggraph_asia": siggraph,
    "papercopilot": papercopilot,
}


def available_sources(venue_key: str, year: int, preferred: list[str]) -> list[str]:
    return [
        source
        for source in preferred
        if source in HARVESTERS and HARVESTERS[source].supports(venue_key, year)
    ]


def harvest_with_source(source: str, venue_key: str, year: int) -> dict[str, Any]:
    if source not in HARVESTERS:
        raise ValueError(f"Unknown harvester source: {source}")
    harvester = HARVESTERS[source]
    if not harvester.supports(venue_key, year):
        raise ValueError(f"{source} does not support {venue_key}{year}")
    return harvester.harvest(venue_key, year)
