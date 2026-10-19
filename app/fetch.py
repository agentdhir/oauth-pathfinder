"""Safe page fetching + search. Direct fetch first; falls back to the r.jina.ai reader
for JS-rendered docs (only public URLs are ever sent there)."""
import hashlib, ipaddress, json, re, socket, time
from urllib.parse import urlparse, urljoin
import httpx
from bs4 import BeautifulSoup

from .storage import CACHE_DIR as CACHE

UA = "Mozilla/5.0 (compatible; OAuthPathfinder/0.1; +research)"
MAX_CHARS = 14000
NAT64 = ipaddress.ip_network("64:ff9b::/96")


def is_public_url(url: str) -> bool:
    """Reject non-http(s) and private/loopback targets (URLs come from search + LLM)."""
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return False
        if any(x in url.lower() for x in ("/login", "/signin", "/sign-in", "/signup", "login?", "auth0.com/u/")):
            return False
        for info in socket.getaddrinfo(p.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.version == 6 and ip in NAT64:  # NAT64 networks: judge the embedded IPv4
                ip = ipaddress.ip_address(int(ip) & 0xFFFFFFFF)
            elif ip.version == 6 and ip.ipv4_mapped:
                ip = ip.ipv4_mapped
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except Exception:
        return False


def _clean(html: str) -> tuple[str, str, list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.string or "").strip() if soup.title else ""
    links = [a["href"] for a in soup.find_all("a", href=True)]
    for t in soup(["script", "style", "nav", "footer", "header", "noscript", "svg", "form"]):
        t.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = main.get_text("\n", strip=True)
    return title, re.sub(r"\n{3,}", "\n\n", text), links


CACHE_TTL = 3 * 24 * 3600


def fetch_page(url: str) -> dict | None:
    """Cached wrapper: pages are kept for a few days so evidence can be re-checked without re-fetching."""
    if not is_public_url(url):
        return None
    f = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    if f.exists() and time.time() - f.stat().st_mtime < CACHE_TTL:
        return json.loads(f.read_text(encoding="utf-8"))
    p = _fetch(url)
    if p:
        try:
            CACHE.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(p), encoding="utf-8")
        except OSError:
            pass  # cache is an optimisation; never fail a fetch because of it
    return p


def _fetch(url: str) -> dict | None:
    """Returns {url,title,text,links,via} or None."""
    try:
        with httpx.Client(follow_redirects=True, timeout=20, headers={"User-Agent": UA}) as c:
            r = c.get(url)
            if r.status_code < 400 and "html" in r.headers.get("content-type", "html"):
                title, text, links = _clean(r.text)
                final = str(r.url)
                links = [urljoin(final, l) for l in links]
                if len(text) >= 600:
                    return {"url": final, "title": title, "text": text[:MAX_CHARS], "links": links, "via": "direct"}
            # JS-rendered or blocked: try the reader
            rr = c.get("https://r.jina.ai/" + url, headers={"User-Agent": UA, "Accept": "text/plain"}, timeout=40)
            if rr.status_code == 200 and len(rr.text) > 400:
                t = rr.text
                m = re.match(r"Title:\s*(.*)", t)
                return {"url": url, "title": m.group(1).strip() if m else url, "text": t[:MAX_CHARS], "links": [], "via": "reader"}
    except Exception:
        return None
    return None


def web_search(query: str, n: int = 6) -> list[dict]:
    try:
        from ddgs import DDGS
        return [{"url": r["href"], "title": r["title"]} for r in DDGS().text(query, max_results=n)]
    except Exception:
        return []
