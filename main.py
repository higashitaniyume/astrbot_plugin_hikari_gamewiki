"""
游戏 Wiki 查询插件（合集）。

支持：
- 泰拉瑞亚（/trwiki）
- 星露谷物语（/sdwiki）
- 我的世界（/mcwiki）
- 以撒的结合（/isaacwiki）
- 杀戮尖塔 2（/sts2wiki）

每个命令可在配置中单独开关，api 地址可覆盖。输出格式：链接 + 页面摘要（+ 主图）。

移植自 HIKARI BOT NEO 的 terraria_wiki / stardew_wiki / mc_wiki / isaac_wiki / sts2_wiki 插件。
"""

from __future__ import annotations

from typing import Any, AsyncGenerator

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.event.filter import GreedyStr
from astrbot.api.star import Context, Star, register

try:
    from .wikis import MediaWikiClient, Sts2Client, WikiError, WikiNotFound
except ImportError:
    from wikis import MediaWikiClient, Sts2Client, WikiError, WikiNotFound

# 每个 Wiki 的默认配置（可在插件配置中覆盖）
WIKI_DEFAULTS: dict[str, dict[str, Any]] = {
    "trwiki": {
        "name": "泰拉瑞亚",
        "api_url": "https://terraria.wiki.gg/api.php",
        "detail_max_chars": 1600,
        "image_size": 640,
    },
    "sdwiki": {
        "name": "星露谷物语",
        "api_url": "https://zh.stardewvalleywiki.com/mediawiki/api.php",
        "detail_max_chars": 1600,
        "image_size": 640,
    },
    "mcwiki": {
        "name": "我的世界",
        "api_url": "https://zh.minecraft.wiki/api.php",
        "detail_max_chars": 1600,
        "image_size": 640,
    },
    "isaacwiki": {
        "name": "以撒的结合",
        "api_url": "https://bindingofisaacrebirth.wiki.gg/api.php",
        "detail_max_chars": 1600,
        "image_size": 640,
    },
    "sts2wiki": {
        "name": "杀戮尖塔 2",
        "api_url": "https://spire-codex.com/api",
        "site_url": "https://spire-codex.com",
        "language": "zhs",
        "version": "",
        "detail_max_chars": 900,
        "search_categories": [],
    },
}

MEDIAWIKI_COMMON_KEYS = ("timeout", "search_limit", "summary_max_chars", "proxy", "user_agent")


@register("gamewiki", "higashitaniyume", "游戏 Wiki 搜索合集：泰拉瑞亚 / 星露谷 / 我的世界 / 以撒 / 杀戮尖塔 2", "1.0.0")
class GameWikiPlugin(Star):
    """游戏 Wiki 查询插件。"""

    def __init__(self, context: Context, config: Any = None):
        super().__init__(context, config)

    # ── 工具方法 ──

    def _enabled(self, key: str) -> bool:
        section = self._section(key)
        return bool(section.get("enabled", True))

    def _section(self, key: str) -> dict[str, Any]:
        section = self.config.get(key, {}) if self.config else {}
        if not isinstance(section, dict):
            section = {}
        merged = dict(WIKI_DEFAULTS.get(key, {}))
        merged.update(section)
        return merged

    def _build_mediawiki(self, key: str) -> MediaWikiClient:
        section = self._section(key)
        return MediaWikiClient(
            str(section.get("api_url") or ""),
            timeout=float(section.get("timeout", 12)),
            search_limit=int(section.get("search_limit", 3)),
            summary_max_chars=int(section.get("summary_max_chars", 220)),
            detail_max_chars=int(section.get("detail_max_chars", 1600)),
            image_size=int(section.get("image_size", 640)),
            proxy=str(section.get("proxy", "") or ""),
            user_agent=str(section.get("user_agent", "astrbot-gamewiki/1.0") or ""),
        )

    def _build_sts2(self) -> Sts2Client:
        section = self._section("sts2wiki")
        categories = section.get("search_categories")
        if not isinstance(categories, list):
            categories = []
        return Sts2Client(
            str(section.get("api_url") or ""),
            site_url=str(section.get("site_url", "") or ""),
            language=str(section.get("language", "zhs") or ""),
            version=str(section.get("version", "") or ""),
            timeout=float(section.get("timeout", 12)),
            search_limit=int(section.get("search_limit", 5)),
            summary_max_chars=int(section.get("summary_max_chars", 300)),
            search_categories=categories,
            proxy=str(section.get("proxy", "") or ""),
            user_agent=str(section.get("user_agent", "astrbot-gamewiki/1.0") or ""),
        )

    async def _handle(self, event: AstrMessageEvent, key: str, query: str) -> AsyncGenerator:
        """通用查询流程：搜索 → 发文本 → 发主图。"""
        section = self._section(key)
        display_name = str(section.get("name") or key)
        keyword = query.strip()
        if not keyword:
            yield event.plain_result(f"用法：/{key} <关键词>\n例如：/{key} 晶塔")
            return

        try:
            if key == "sts2wiki":
                result = await self._build_sts2().search(keyword)
            else:
                result = await self._build_mediawiki(key).search(keyword)
        except WikiNotFound as e:
            logger.info(f"[GameWiki] {key} 未找到: {e}")
            yield event.plain_result(f"{display_name} Wiki：{e}")
            return
        except WikiError as e:
            logger.warning(f"[GameWiki] {key} 查询失败: {e}")
            yield event.plain_result(f"{display_name} Wiki 查询失败：{e}")
            return
        except Exception as e:
            logger.exception(f"[GameWiki] {key} 查询异常: {e}")
            yield event.plain_result(f"{display_name} Wiki 查询出错：{type(e).__name__}")
            return

        link_text = f"{display_name} Wiki · {result.title}\n{result.url}"
        if result.summary:
            link_text += f"\n\n{result.summary}"
        yield event.plain_result(link_text)
        if result.image_url:
            yield event.image_result(result.image_url)

    # ── 命令 ──

    @filter.command("trwiki", alias={"泰拉瑞亚wiki", "泰拉瑞亚Wiki", "泰拉瑞亚维基", "terrariawiki", "tr维基", "TRWiki"})
    async def trwiki(self, event: AstrMessageEvent, query: GreedyStr = ""):
        """搜索中文泰拉瑞亚 Wiki"""
        if not self._enabled("trwiki"):
            return
        async for result in self._handle(event, "trwiki", query):
            yield result

    @filter.command("sdwiki", alias={"星露谷wiki", "星露谷Wiki", "星露谷维基", "stardewwiki", "星露谷"})
    async def sdwiki(self, event: AstrMessageEvent, query: GreedyStr = ""):
        """搜索中文星露谷物语 Wiki"""
        if not self._enabled("sdwiki"):
            return
        async for result in self._handle(event, "sdwiki", query):
            yield result

    @filter.command("mcwiki", alias={"我的世界wiki", "我的世界Wiki", "mc维基", "minecraftwiki", "MCWiki"})
    async def mcwiki(self, event: AstrMessageEvent, query: GreedyStr = ""):
        """搜索中文我的世界 Wiki"""
        if not self._enabled("mcwiki"):
            return
        async for result in self._handle(event, "mcwiki", query):
            yield result

    @filter.command("isaacwiki", alias={"以撒wiki", "以撒Wiki", "以撒维基", "isaac", "以撒的结合"})
    async def isaacwiki(self, event: AstrMessageEvent, query: GreedyStr = ""):
        """搜索以撒的结合 Wiki"""
        if not self._enabled("isaacwiki"):
            return
        async for result in self._handle(event, "isaacwiki", query):
            yield result

    @filter.command("sts2wiki", alias={"杀戮尖塔2wiki", "杀戮尖塔2Wiki", "尖塔2wiki", "sts2", "slaythespire2"})
    async def sts2wiki(self, event: AstrMessageEvent, query: GreedyStr = ""):
        """搜索杀戮尖塔 2 Wiki"""
        if not self._enabled("sts2wiki"):
            return
        async for result in self._handle(event, "sts2wiki", query):
            yield result
