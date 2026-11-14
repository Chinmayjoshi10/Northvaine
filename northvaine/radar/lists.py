"""Dealers other brands list: competitors' stockist and "where to buy" pages (D153, plan B S5).

A client's best channel buyers are often already listed in public: the brands it competes with
publish who stocks them. A shop listed by two or more brands is a multi-brand stockist, a buyer of
the client's kind of product that already sells several makers' ranges; a showroom carrying one
brand's name is likely exclusive and is left out.

Only names and web addresses are taken from a list page; nothing on it is a claim. Each dealer
then becomes a lead only through its own website (the target-account path, D138): a stated
sentence naming what the client sells, then the gate, the skeptic, fit, the floor and the review.
Pages are fetched by the run's fetcher, which honours robots.txt; a refused page is skipped.
Generic path words only, no industry words; hosts the founder adds to
`radar_list_hosts_denied` are never read.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from northvaine.core.settings import Settings
from northvaine.radar.country import country_from_host
from northvaine.radar.discover import PageFetcher
from northvaine.radar.models import TargetAccount

__all__ = ["Listed", "Mention", "dealer_accounts", "list_links", "listed_dealers", "mention_line"]

# Hosts that are never a dealer's own site, wherever they appear on a list page.
_NOT_DEALERS = (
    "facebook.", "instagram.", "linkedin.", "twitter.", "x.com", "youtube.", "pinterest.",
    "google.", "goo.gl", "apple.com", "whatsapp.", "wa.me", "t.me", "tiktok.", "bit.ly",
    "wikipedia.", "amazon.", "maps.", "cookiebot.", "onetrust.", "gstatic.", "w3.org",
    "matterport.", "powerappsportals.", "yulio.", "vimeo.", "issuu.", "hubspot.",
)  # fmt: skip


@dataclass(frozen=True)
class Mention:
    """A line of a peer brand's own stockist page that names the dealer (D154)."""

    peer: str
    url: str
    text: str  # the whole page text, the document the quote is checked against
    line: str  # the verbatim line naming the dealer


@dataclass(frozen=True)
class Listed:
    domain: str
    brands: tuple[str, ...]  # the peer domains whose list pages name it
    mentions: tuple[Mention, ...] = ()


# Words a dealer's web address often ends with that say nothing about who it is.
_GENERIC_TAILS = ("limited", "ltd", "group", "online", "direct", "store", "shop", "uk", "co")


def name_token(domain: str) -> str:
    """The distinctive word of a dealer's web address: 'beers' for 'beersltd.co.uk'."""
    first = domain.split(".")[0]
    parts = [x for x in re.split(r"[-_\d]+", first) if x]
    best = max(parts, key=len) if parts else ""
    changed = True
    while changed:
        changed = False
        for tail in _GENERIC_TAILS:
            if best.endswith(tail) and len(best) - len(tail) >= 4:
                best = best[: -len(tail)]
                changed = True
    return best


def mention_line(text: str, domain: str, limit: int = 120) -> str | None:
    """A verbatim piece of `text` that names the dealer: it starts where the distinctive word of
    the dealer's web address starts a word (letters only, so "E H Smith" matches "ehsmith") and
    runs to the end of that line, at most `limit` characters. None when the page does not name
    it, or when the word is too short to tell."""
    token = name_token(domain).casefold()
    if len(token) < 4:
        return None
    letters: list[str] = []
    where: list[int] = []  # letters[i] came from text[where[i]]
    for i, ch in enumerate(text):
        if ch.isalpha():
            letters.append(ch.casefold())
            where.append(i)
    joined = "".join(letters)
    at = joined.find(token)
    while at != -1:
        begin = where[at]
        if begin == 0 or not text[begin - 1].isalnum():  # the name starts a word
            stop = text.find("\n", begin)
            stop = len(text) if stop == -1 else stop
            piece = text[begin : min(stop, begin + limit)].strip()
            if piece:
                return piece
        at = joined.find(token, at + 1)
    return None


def _domain(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.")


def _brand_word(domain: str) -> str:
    """The distinctive part of a brand's web address: 'acme' for 'acme-group.co.uk'."""
    first = domain.split(".")[0]
    return re.split(r"[-_]", first)[0]


def list_links(links: list[str], peer: str, words: tuple[str, ...], limit: int) -> list[str]:
    """Links on the peer's own pages that lead to its stockist / dealer list pages."""
    out: list[str] = []
    for link in links:
        if _domain(link) != peer and not _domain(link).endswith("." + peer):
            continue
        path = (urlsplit(link).path or "").casefold()
        if any(w in path for w in words) and link not in out:
            out.append(link)
        if len(out) >= limit:
            break
    return out


def listed_dealers(
    pages_by_peer: dict[str, list[list[str]]],
    denied: tuple[str, ...],
    texts_by_peer: dict[str, list[tuple[str, str]]] | None = None,
) -> list[Listed]:
    """Dealers named on the peers' list pages: external sites, counted by how many brands list
    them; a site whose address carries a listing brand's name (its own branded showroom) is left
    out. Multi-brand first."""
    brands_of: dict[str, set[str]] = defaultdict(set)
    for peer, pages in pages_by_peer.items():
        for links in pages:
            for link in links:
                domain = _domain(link)
                if (
                    not domain
                    or "." not in domain
                    or domain == peer
                    or domain.endswith("." + peer)
                    or any(bad in domain for bad in _NOT_DEALERS)
                    or any(domain == d or domain.endswith("." + d) for d in denied)
                ):
                    continue
                brands_of[domain].add(peer)
    peers = set(pages_by_peer)
    out = []
    for domain, brands in brands_of.items():
        if domain in peers:
            continue  # another brand of the same list is a peer, not a dealer
        if any(_brand_word(b) in domain for b in brands if len(_brand_word(b)) >= 4):
            continue  # "<brand>world.com": a showroom of one brand
        mentions = []
        for peer in sorted(brands):
            for url, text in (texts_by_peer or {}).get(peer, []):
                line = mention_line(text, domain)
                if line is not None:
                    mentions.append(Mention(peer, url, text, line))
                    break
        out.append(Listed(domain, tuple(sorted(brands)), tuple(mentions)))
    out.sort(key=lambda d: (-len(d.brands), d.domain))
    return out


async def dealer_accounts(
    spec: Any, fetcher: PageFetcher, settings: Settings
) -> tuple[list[TargetAccount], dict[str, Listed], list[str]]:
    """(dealers to read as target accounts, what listed each, notes) from the client's peer
    sites. A dealer needs a country: its web address's ending, else the client's only market."""
    peers = [_domain(p if "//" in p else f"https://{p}") for p in getattr(spec, "peer_sites", [])]
    peers = [p for p in peers if p][: settings.radar_list_max_peers]
    if not peers:
        return [], {}, []
    words = tuple(w.casefold() for w in settings.radar_list_path_words)
    pages_by_peer: dict[str, list[list[str]]] = {}
    texts_by_peer: dict[str, list[tuple[str, str]]] = {}
    notes: list[str] = []
    for peer in peers:
        home = await fetcher.fetch(f"https://{peer}/")
        if home.refused is not None or not home.links:
            notes.append(f"dealer lists: {peer} could not be read ({home.refused or 'no links'})")
            continue
        targets = list_links(home.links, peer, words, settings.radar_list_pages_per_peer)
        pages: list[list[str]] = []
        texts: list[tuple[str, str]] = []
        for url in targets:
            page = await fetcher.fetch(url)
            if page.refused is None and page.links:
                pages.append(page.links)
                texts.append((page.final_url or url, page.text or ""))
        pages_by_peer[peer] = pages
        texts_by_peer[peer] = texts
        if not pages:
            notes.append(f"dealer lists: {peer} shows no readable dealer page")
    denied = tuple(settings.radar_list_hosts_denied)
    listed = listed_dealers(pages_by_peer, denied, texts_by_peer)
    markets = list(getattr(spec, "markets", []) or [])
    accounts: list[TargetAccount] = []
    by_domain: dict[str, Listed] = {}
    for item in listed:
        country = country_from_host(item.domain) or (markets[0] if len(markets) == 1 else None)
        if country is None or (markets and country not in markets):
            continue
        accounts.append(
            TargetAccount(name=item.domain, country=country, website=f"https://{item.domain}/")
        )
        by_domain[item.domain] = item
        if len(accounts) >= settings.radar_list_max_dealers:
            break
    multi = sum(1 for a in accounts if len(by_domain[_domain(a.website)].brands) >= 2)
    notes.append(
        f"dealer lists: {len(pages_by_peer)} brand site(s) read, {len(accounts)} dealer(s) to "
        f"check, {multi} listed by more than one brand"
    )
    return accounts, by_domain, notes
