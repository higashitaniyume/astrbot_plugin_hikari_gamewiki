# astrbot_plugin_gamewiki

游戏 Wiki 搜索合集插件，一条命令搜一个游戏的 Wiki：

| 命令 | Wiki | 别名 |
|------|------|------|
| `/trwiki <关键词>` | 泰拉瑞亚（中文） | 泰拉瑞亚wiki / tr维基 / terrariawiki |
| `/sdwiki <关键词>` | 星露谷物语（中文） | 星露谷wiki / 星露谷维基 / stardewwiki |
| `/mcwiki <关键词>` | 我的世界（中文） | 我的世界wiki / mc维基 / minecraftwiki |
| `/isaacwiki <关键词>` | 以撒的结合 | 以撒wiki / isaac / 以撒的结合 |
| `/sts2wiki <关键词>` | 杀戮尖塔 2 | 杀戮尖塔2wiki / sts2 / slaythespire2 |

## 功能

- 搜索并返回最佳匹配页面：标题 + 链接 + 页面摘要 + 主图
- 泰拉瑞亚 / 星露谷 / 我的世界 / 以撒使用标准 MediaWiki API（自动降级 extracts → intro HTML）
- 杀戮尖塔 2 使用 Spire Codex API（中文数据源，支持卡牌/角色/遗物/药水/关键词等分类）

## 配置

每个 Wiki 可在插件配置中单独开关、覆盖 API 地址、调整摘要长度等。默认开箱即用，无需配置。

## 依赖

- `httpx>=0.27.0`（在 requirements.txt 中声明）

## 协议

AGPL-3.0-or-later
