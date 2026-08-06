"""
游戏 Wiki 查询客户端集合。

包含：
- MediaWikiClient：标准 MediaWiki API 客户端（泰拉瑞亚 / 星露谷 / 我的世界 / 以撒 共用）
- Sts2Client：Spire Codex API 客户端（杀戮尖塔 2 专用）

移植自 HIKARI BOT NEO 的 terraria_wiki / stardew_wiki / mc_wiki / isaac_wiki / sts2_wiki 插件。
代码独立，不依赖任何宿主机器人模块。
"""

from __future__ import annotations

import asyncio
import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import httpx


# =========================
# 通用数据结构
# =========================


class WikiError(RuntimeError):
    """Wiki 查询通用错误。"""


class WikiNotFound(WikiError):
    """没有找到匹配结果。"""


@dataclass(slots=True)
class WikiResult:
    """Wiki 查询结果。"""

    title: str
    summary: str
    detail: str
    url: str
    image_url: str = ""


# =========================
# 文本工具
# =========================


def _normalize_text(value: str) -> str:
    """清理文本：还原 HTML 实体、去掉引用标记、压缩空白。"""
    text = html.unescape(value)
    text = re.sub(r"\[\s*\d+\s*\]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _first_paragraph(value: str) -> str:
    """取第一段。"""
    return value.strip().split("\n", 1)[0].strip()


def _image_source(value: Any) -> str:
    """从 pageimages 响应项中提取图片 URL。"""
    if not isinstance(value, dict):
        return ""
    source = value.get("source")
    return source.strip() if isinstance(source, str) else ""


def _truncate(value: str, max_chars: int) -> str:
    """按字符数截断，超长加省略号。"""
    text = value.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


# =========================
# MediaWiki 客户端（4 个 Wiki 共用）
# =========================


class _IntroTextParser(HTMLParser):
    """从页面 HTML 中提取正文段落（跳过脚本/样式/表格）。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._paragraph_depth = 0
        self._current: list[str] = []
        self.paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "table"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "p":
            self._paragraph_depth += 1
            self._current = []

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth:
            if tag in {"script", "style", "table"}:
                self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "p" and self._paragraph_depth:
            text = _normalize_text("".join(self._current))
            if text:
                self.paragraphs.append(text)
            self._paragraph_depth -= 1
            self._current = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not self._paragraph_depth:
            return
        self._current.append(data)


class MediaWikiClient:
    """标准 MediaWiki API 客户端（action=query + extracts / parse / pageimages）。"""

    def __init__(self, api_url: str, *, timeout: float = 12.0,
                 search_limit: int = 3, summary_max_chars: int = 220,
                 detail_max_chars: int = 1600, image_size: int = 640,
                 proxy: str = "", user_agent: str = "astrbot-gamewiki/1.0") -> None:
        self.api_url = str(api_url or "").strip()
        self.timeout = timeout
        self.search_limit = max(1, min(search_limit, 10))
        self.summary_max_chars = max(60, summary_max_chars)
        self.detail_max_chars = max(self.summary_max_chars, detail_max_chars)
        self.image_size = max(120, min(image_size, 1600))
        self.proxy = str(proxy or "").strip() or None
        self.user_agent = str(user_agent or "").strip() or "astrbot-gamewiki/1.0"
        if not self.api_url:
            raise WikiError("Wiki API 地址未配置")

    def _client_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(self.timeout, connect=min(self.timeout, 10.0)),
            "follow_redirects": True,
            "headers": {
                "Accept": "application/json",
                "User-Agent": self.user_agent,
            },
        }
        if self.proxy:
            kwargs["proxy"] = self.proxy
        return kwargs

    async def search(self, query: str) -> WikiResult:
        """搜索并返回最佳匹配页面的摘要、详情和主图。"""
        keyword = query.strip()
        if not keyword:
            raise WikiError("缺少搜索关键词")

        page = await self._search_page(keyword)
        detail_result, image_result = await asyncio.gather(
            self._fetch_detail(page["title"]),
            self._fetch_main_image(page["title"]),
            return_exceptions=True,
        )
        if isinstance(detail_result, Exception):
            raise detail_result
        detail = detail_result or "这个页面暂时没有可提取的详细描述。"
        detail = _truncate(detail, self.detail_max_chars)
        summary = _truncate(_first_paragraph(detail), self.summary_max_chars)
        image_url = "" if isinstance(image_result, Exception) else image_result
        return WikiResult(
            title=str(page["title"]),
            summary=summary,
            detail=detail,
            url=str(page["fullurl"]),
            image_url=image_url,
        )

    async def _request(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(**self._client_kwargs()) as client:
                response = await client.get(self.api_url, params=params)
            response.raise_for_status()
            data = response.json()
        except httpx.RequestError as e:
            raise WikiError(f"Wiki 连接失败: {type(e).__name__}") from e
        except httpx.HTTPStatusError as e:
            raise WikiError(f"Wiki 请求失败: HTTP {e.response.status_code}") from e
        except ValueError as e:
            raise WikiError("Wiki 返回内容不是有效 JSON") from e
        if not isinstance(data, dict):
            raise WikiError("Wiki 返回格式异常")
        return data

    async def _search_page(self, keyword: str) -> dict[str, Any]:
        """搜索关键词，返回第一个匹配页面（含 fullurl）。"""
        data = await self._request(
            {
                "action": "query",
                "generator": "search",
                "gsrsearch": keyword,
                "gsrlimit": self.search_limit,
                "prop": "info",
                "inprop": "url",
                "format": "json",
                "formatversion": 2,
            }
        )
        pages = data.get("query", {}).get("pages", [])
        if not isinstance(pages, list) or not pages:
            raise WikiNotFound(f"没有找到「{keyword}」")
        pages.sort(key=lambda item: int(item.get("index") or 9999))
        page = pages[0]
        if not isinstance(page, dict) or not page.get("title") or not page.get("fullurl"):
            raise WikiError("Wiki 搜索结果格式异常")
        return page

    async def _fetch_detail(self, title: str) -> str:
        """先试 extracts 纯文本，失败再解析 intro HTML。"""
        extract = await self._fetch_extract(title)
        if extract:
            return extract
        return await self._fetch_intro_html(title)

    async def _fetch_extract(self, title: str) -> str:
        data = await self._request(
            {
                "action": "query",
                "prop": "extracts",
                "exintro": 1,
                "explaintext": 1,
                "redirects": 1,
                "titles": title,
                "format": "json",
                "formatversion": 2,
            }
        )
        pages = data.get("query", {}).get("pages", [])
        if not isinstance(pages, list) or not pages:
            return ""
        page = pages[0]
        if not isinstance(page, dict):
            return ""
        extract = page.get("extract")
        if not isinstance(extract, str):
            return ""
        return _normalize_text(extract)

    async def _fetch_intro_html(self, title: str) -> str:
        """MediaWiki 的 extracts 扩展可能未安装，降级解析 intro HTML。"""
        data = await self._request(
            {
                "action": "parse",
                "page": title,
                "prop": "text",
                "section": 0,
                "format": "json",
                "formatversion": 2,
            }
        )
        raw_html = data.get("parse", {}).get("text")
        if not isinstance(raw_html, str):
            return ""
        parser = _IntroTextParser()
        parser.feed(raw_html)
        return "\n\n".join(parser.paragraphs).strip()

    async def _fetch_main_image(self, title: str) -> str:
        data = await self._request(
            {
                "action": "query",
                "prop": "pageimages",
                "piprop": "thumbnail|original",
                "pithumbsize": self.image_size,
                "redirects": 1,
                "titles": title,
                "format": "json",
                "formatversion": 2,
            }
        )
        pages = data.get("query", {}).get("pages", [])
        if not isinstance(pages, list) or not pages:
            return ""
        page = pages[0]
        if not isinstance(page, dict):
            return ""
        return _image_source(page.get("original")) or _image_source(page.get("thumbnail"))


# =========================
# Spire Codex 客户端（杀戮尖塔 2）
# =========================

_DEFAULT_SEARCH_CATEGORIES = (
    "cards",
    "characters",
    "relics",
    "potions",
    "powers",
    "keywords",
    "monsters",
    "events",
)

_ENDPOINT_LABELS = {
    "cards": "卡牌",
    "characters": "角色",
    "relics": "遗物",
    "potions": "药水",
    "powers": "能力效果",
    "keywords": "关键词",
    "monsters": "怪物",
    "events": "事件",
    "encounters": "遭遇",
    "acts": "章节",
    "ascensions": "进阶",
    "orbs": "充能球",
    "afflictions": "苦痛",
    "modifiers": "修正",
    "achievements": "成就",
}

_CHARACTER_LABELS = {
    "ironclad": "铁甲战士",
    "silent": "静默猎手",
    "defect": "故障机器人",
    "regent": "储君",
    "necrobinder": "亡灵契约师",
    "shared": "通用",
    "colorless": "无色",
    "token": "衍生",
}


@dataclass(slots=True)
class _SpireCandidate:
    endpoint: str
    item_id: str
    name: str
    summary: str
    extract: str
    exact_name: bool
    score: int


class Sts2Client:
    """杀戮尖塔 2 中文数据源（Spire Codex API）客户端。"""

    def __init__(self, api_url: str, *, site_url: str = "", language: str = "zhs",
                 version: str = "", timeout: float = 12.0, search_limit: int = 5,
                 summary_max_chars: int = 300,
                 search_categories: list[str] | None = None,
                 proxy: str = "", user_agent: str = "astrbot-gamewiki/1.0") -> None:
        self.api_url = str(api_url or "").strip().rstrip("/")
        self.site_url = str(site_url or "").strip().rstrip("/")
        self.language = str(language or "zhs")
        self.version = str(version or "").strip()
        self.timeout = timeout
        self.search_limit = max(1, min(search_limit, 10))
        self.summary_max_chars = max(80, summary_max_chars)
        self.search_categories = _search_categories(search_categories)
        self.proxy = str(proxy or "").strip() or None
        self.user_agent = str(user_agent or "").strip() or "astrbot-gamewiki/1.0"
        if not self.api_url:
            raise WikiError("杀戮尖塔 2 数据源地址未配置")

    def _client_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(self.timeout, connect=min(self.timeout, 10.0)),
            "follow_redirects": True,
            "headers": {
                "Accept": "application/json",
                "User-Agent": self.user_agent,
            },
        }
        if self.proxy:
            kwargs["proxy"] = self.proxy
        return kwargs

    async def search(self, query: str) -> WikiResult:
        """跨分类搜索，返回最佳匹配。"""
        keyword = query.strip()
        if not keyword:
            raise WikiError("缺少搜索关键词")

        candidates: list[_SpireCandidate] = []
        exact_candidate: _SpireCandidate | None = None
        for endpoint in self.search_categories:
            endpoint_candidates = await self._fetch_candidates(endpoint, keyword)
            candidates.extend(endpoint_candidates)
            exact_candidate = next((c for c in endpoint_candidates if c.exact_name), None)
            if exact_candidate is not None:
                break

        if not candidates:
            raise WikiNotFound(f"没有找到「{keyword}」")

        best = exact_candidate or sorted(candidates, key=lambda item: item.score, reverse=True)[0]
        extract = _truncate(best.extract, max(self.summary_max_chars * 3, 900))
        summary = _truncate(_first_paragraph(extract), self.summary_max_chars)
        return WikiResult(
            title=f"{best.name}（{_endpoint_label(best.endpoint)}）",
            summary=summary,
            detail=extract,
            url=self._page_url(best.endpoint, best.item_id),
        )

    async def _fetch_candidates(self, endpoint: str, keyword: str) -> list[_SpireCandidate]:
        params: dict[str, Any] = {"lang": self.language, "search": keyword}
        if self.version:
            params["version"] = self.version

        data = await self._request(endpoint, params)
        if not isinstance(data, list):
            return []

        query_key = _compact_key(keyword)
        candidates: list[_SpireCandidate] = []
        for index, item in enumerate(data):
            if not isinstance(item, dict):
                continue
            candidate = _spire_candidate(endpoint, item, query_key, index)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    async def _request(self, endpoint: str, params: dict[str, Any]) -> Any:
        url = f"{self.api_url}/{endpoint.strip('/')}"
        try:
            async with httpx.AsyncClient(**self._client_kwargs()) as client:
                response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            raise WikiError(f"杀戮尖塔 2 数据源连接失败: {type(e).__name__}") from e
        except httpx.HTTPStatusError as e:
            raise WikiError(f"杀戮尖塔 2 数据源请求失败: HTTP {e.response.status_code}") from e
        except ValueError as e:
            raise WikiError("杀戮尖塔 2 数据源返回内容不是有效 JSON") from e

    def _page_url(self, endpoint: str, item_id: str) -> str:
        base = self.site_url
        if not base:
            parsed = urlparse(self.api_url)
            base = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
        if not base:
            return ""
        language_prefix = f"/{self.language}" if self.language and self.language != "eng" else ""
        url = f"{base}{language_prefix}/{endpoint}/{quote(item_id, safe='')}"
        if self.version:
            url = f"{url}?{urlencode({'version': self.version})}"
        return url


# ── Spire Codex 条目评分/摘要提取 ──


def _search_categories(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return _DEFAULT_SEARCH_CATEGORIES
    categories = [str(item).strip() for item in value if str(item).strip()]
    return tuple(categories) or _DEFAULT_SEARCH_CATEGORIES


def _endpoint_label(endpoint: str) -> str:
    return _ENDPOINT_LABELS.get(endpoint, endpoint)


def _character_label(value: Any) -> str:
    key = str(value or "").strip().casefold()
    return _CHARACTER_LABELS.get(key, str(value).strip() if value else "")


def _safe_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _spire_candidate(endpoint: str, item: dict[str, Any], query_key: str, index: int) -> _SpireCandidate | None:
    item_id = str(item.get("id") or "").strip()
    name = str(item.get("name") or "").strip()
    if not item_id or not name:
        return None

    fields = _spire_text_fields(item)
    haystack = _compact_key(" ".join([name, *fields]))
    name_key = _compact_key(name)
    exact_name = bool(query_key and name_key == query_key)
    if query_key and query_key not in haystack:
        return None

    summary = _spire_summary(endpoint, item)
    extract = _spire_extract(endpoint, item)
    score = _spire_score(endpoint, name_key, haystack, query_key, index)
    return _SpireCandidate(
        endpoint=endpoint,
        item_id=item_id,
        name=name,
        summary=summary,
        extract=extract,
        exact_name=exact_name,
        score=score,
    )


def _spire_text_fields(item: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    for key in ("description", "flavor", "type", "rarity", "pool", "color"):
        value = item.get(key)
        if isinstance(value, str):
            fields.append(value)
    tags = item.get("tags")
    if isinstance(tags, list):
        fields.extend(str(tag) for tag in tags)
    return fields


def _spire_score(endpoint: str, name_key: str, haystack: str, query_key: str, index: int) -> int:
    endpoint_rank = list(_DEFAULT_SEARCH_CATEGORIES).index(endpoint) if endpoint in _DEFAULT_SEARCH_CATEGORIES else 99
    score = 1000 - endpoint_rank * 20 - index
    if query_key and name_key == query_key:
        score += 10000
    elif query_key and name_key.startswith(query_key):
        score += 3000
    elif query_key and query_key in name_key:
        score += 1500
    elif query_key and query_key in haystack:
        score += 100
    return score


def _spire_summary(endpoint: str, item: dict[str, Any]) -> str:
    parts = [_endpoint_label(endpoint)]
    if endpoint == "cards":
        parts.extend(
            part
            for part in (
                _character_label(item.get("color")),
                _safe_text(item.get("type")),
                _safe_text(item.get("rarity")),
                _cost_label(item),
            )
            if part
        )
    elif endpoint in {"relics", "potions"}:
        parts.extend(part for part in (_character_label(item.get("pool")), _safe_text(item.get("rarity"))) if part)
    elif endpoint == "characters":
        parts.extend(
            part
            for part in (
                f"生命 {item.get('starting_hp')}" if item.get('starting_hp') is not None else "",
                f"初始金币 {item.get('starting_gold')}" if item.get('starting_gold') is not None else "",
                f"能量 {item.get('max_energy')}" if item.get('max_energy') is not None else "",
            )
            if part
        )
    elif endpoint == "monsters":
        parts.append(_safe_text(item.get("type")))
    return " · ".join(part for part in parts if part)


def _spire_extract(endpoint: str, item: dict[str, Any]) -> str:
    lines = [_spire_summary(endpoint, item)]
    description = _strip_spire_markup(_safe_text(item.get("description")))
    if description:
        lines.append(description)

    if endpoint == "cards":
        upgrade = _strip_spire_markup(_safe_text(item.get("upgrade_description")))
        if upgrade and upgrade != description:
            lines.append(f"升级：{upgrade}")
    flavor = _strip_spire_markup(_safe_text(item.get("flavor")))
    if flavor:
        lines.append(f"描述：{flavor}")
    return "\n".join(line for line in lines if line)


def _cost_label(item: dict[str, Any]) -> str:
    if item.get("is_x_cost"):
        return "费用 X"
    if item.get("is_x_star_cost"):
        return "星能 X"
    star_cost = item.get("star_cost")
    if star_cost is not None:
        return f"星能 {star_cost}"
    cost = item.get("cost")
    if cost is None:
        return ""
    return f"费用 {cost}"


def _strip_spire_markup(value: str) -> str:
    text = value
    text = re.sub(r"\[energy:(\d+)\]", r"\1费", text)
    text = re.sub(r"\[star:(\d+)\]", r"\1星", text)
    text = re.sub(r"\[/?[a-z]+(?:[:=][^\]]+)?\]", "", text, flags=re.IGNORECASE)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _compact_key(value: str) -> str:
    return re.sub(r"\s+", "", value.strip().casefold())
