"""Discover and import recipes from the household's configured source sites.

Walks each site's sitemap (standard on WordPress blogs), tries every
plausible post URL through the JSON-LD importer, and stops after `limit`
successful imports per site. Non-recipe pages are skipped automatically
(no structured recipe data). Fetches are politely paced; recipes are stored
for the household's own use only.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from ..config import UserConfig
from ..paths import parsed_cache_dir
from .library import slugify
from .webimport import extract_jsonld_recipe, fetch_html, import_from_url

SITEMAP_CANDIDATES = ("sitemap_index.xml", "wp-sitemap.xml", "sitemap.xml")
SKIP_PATTERNS = re.compile(
    r"/(category|tag|author|about|shop|privacy|contact|page)/|"
    r"\.(jpg|png|webp|pdf)$|#",
    re.IGNORECASE,
)


def source_domain(url: str) -> str:
    return urlparse(url).netloc.removeprefix("www.")


def _locs(xml: str) -> list[str]:
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)


def sitemap_urls(site: str, max_pages: int = 2000) -> list[str]:
    """Collect post URLs from a site's sitemap tree (best effort)."""
    root = site.rstrip("/")
    for name in SITEMAP_CANDIDATES:
        try:
            xml = fetch_html(f"{root}/{name}")
        except Exception:
            continue
        locs = _locs(xml)
        if not locs:
            continue
        pages: list[str] = []
        submaps = [l for l in locs if l.endswith(".xml")]
        if submaps:
            # Prefer post sitemaps; skip image/category/tag maps.
            for sub in submaps:
                if re.search(r"(post|posts)[^/]*\.xml", sub) or not re.search(
                    r"(category|tag|author|page|image|video)", sub
                ):
                    try:
                        pages.extend(_locs(fetch_html(sub)))
                    except Exception:
                        continue
                    if len(pages) >= max_pages:
                        break
        else:
            pages = locs
        urls = [
            u for u in pages
            if u.startswith(root) and not SKIP_PATTERNS.search(u) and u != root + "/"
        ]
        if urls:
            return urls[:max_pages]
    return []


def already_imported(user: str, base: Path | None = None) -> set[str]:
    """Slugs present in the parsed cache (any source)."""
    cache = parsed_cache_dir(user, base)
    return {p.stem for p in cache.glob("*.json")} if cache.exists() else set()


def discover_site(
    client,
    user: str,
    site: str,
    limit: int,
    model: str,
    base: Path | None = None,
    pace_s: float = 1.5,
) -> tuple[int, int]:
    """Import up to `limit` new recipes from one site; returns (imported, tried)."""
    urls = sitemap_urls(site)
    # Newest first is typical sitemap order; shuffle-free determinism is fine.
    have = already_imported(user, base)
    imported = tried = consecutive_failures = 0
    for url in urls:
        if imported >= limit:
            break
        tried += 1
        try:
            html = fetch_html(url)
        except Exception:
            continue
        data = extract_jsonld_recipe(html)
        if data is None or not data["steps"]:
            continue  # not a recipe post
        if slugify(data["title"]) in have:
            continue
        try:
            slug = import_from_url(client, user, url, model=model, base=base)
            have.add(slug)
            imported += 1
            consecutive_failures = 0
            print(f"  + {slug}", flush=True)
        except Exception as exc:
            consecutive_failures += 1
            print(f"  ! {url}: {str(exc)[:80]}", flush=True)
            if consecutive_failures >= 8:
                print(
                    f"  stopping {site}: {consecutive_failures} failures in a row "
                    f"(usage limit or site block) — re-run discover-recipes later "
                    f"to resume where this left off", flush=True,
                )
                break
        time.sleep(pace_s)
    return imported, tried


def discover_all(
    client, user: str, config: UserConfig, limit_per_site: int | None = None,
    base: Path | None = None, total_limit: int | None = None,
) -> int:
    """Import from every configured site. Give either a per-site limit or a
    total budget split evenly across sites (leftover capacity rolls forward)."""
    sites = config.recipe_sources
    total = 0
    remaining = total_limit
    for i, site in enumerate(sites):
        if remaining is not None:
            sites_left = len(sites) - i
            site_limit = max(1, -(-remaining // sites_left))  # ceil split
        else:
            site_limit = limit_per_site or 15
        if remaining is not None and remaining <= 0:
            break
        print(f"[{user}] discovering from {source_domain(site)}…", flush=True)
        imported, tried = discover_site(
            client, user, site, site_limit, config.model, base
        )
        print(f"[{user}] {source_domain(site)}: {imported} imported "
              f"({tried} pages checked)", flush=True)
        total += imported
        if remaining is not None:
            remaining -= imported
    return total
