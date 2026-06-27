# TTNB 项目规则

## 铁律（违者必错）

1. **动手前先读完** — 改任何功能之前，先把所有相关文件从头到尾读一遍。特别是旧脚本、旧 workflow、旧 HTML，搞清楚原来是怎么跑的、输出了什么字段、前端读了什么字段。不要假设。

2. **替换=列清单** — 写新代码替代旧代码时，先把旧代码每个函数、每个输出字段、每个数据源列成清单，新代码逐项对齐。确认所有旧字段都有对应的产出，再提交。绝不允许"新代码写好了但丢了旧功能"。

3. **做完自己验证** — 改完不靠用户说"不行"。自己跑：语法检查、data.json 字段完整性对比、本地 HTTP server 打开页面看渲染。发现不对立刻修，不等用户指出。

4. **提交后自检发布** — commit+push 之后自己等 Pages build 完成，curl 拉线上 data.json 验证字段完整，打开网站确认渲染正常。不等用户说"怎么没有"。

5. **对照内存标准** — 改任何有标准的东西（事件、简报、赛道、字段名）之前，先查 `memory/MEMORY.md` 和相关 memory 文件，确认标准是什么，按标准来。

## 核心原则

- **这是增强项目，不是重写项目。** 加新功能不能丢旧功能。
- **真数据优先。** 所有事件/描述/日期必须是可验证的真实信息，绝不自编。
- **数据源优先级：通达信 TCP > 腾讯 HTTP > 同花顺 HTTP > 东财 HTTP。** 东财只用于它独有、别处拿不到的数据。
- **硬编码是兜底，云端是增强。** data.json 加载时 merge，不覆盖。
- **改完 field name 要全局搜索。** 一个字段改名，前后端、所有脚本都要跟着改。

## data.json 字段名铁律

- 简报页读**短字段名**：`r/t/b/s`（top3）、`r/c/n/why/sec`（picks）
- **双路径写入**：根层 `d.top3/d.picks` + briefing 层 `d.briefing.top3/d.briefing.picks` 都要有
- 禁止用 `title/body/name/code/reason` — 网站读不到

## 事件+布局铁律

- **每条事件必须有**：真实日期、真实标题、icon、赛道、可选URL链接
- **禁止宏噪音**：FOMC/LPR/MLF/非农/CPI/PMI/社融/进出口/固投 — 没人会为等PMI而提前买股票
- **事件必须绑定赛道**：无具体赛道的事件不放日历
- **布局=事件+标的**：事件和布局一一对应，改事件必须同步改布局
- **布局按日期排序**：未来近→远，历史远→近（`sort by realDays`）
- **布局标的**：科创/创业板最多3只，其余主板
- 事件上限50条，多了反而稀释注意力

## 通用UI规则

- 所有事件必须带链接（有URL的补URL，真没有的留空不用编）
- 布局卡按日期排列（最近的排最前）
- 标的Tab需要实时价格（盘中用腾讯API，盘后显示收盘价）
- 搜索股票后可显示K线、财务、研报、概念、新闻等详情

## 验证流程

```
1. python -c "import py_compile; py_compile.compile('file.py', doraise=True)"
2. 对照旧脚本字段列表，确认 data.json 每个字段都有产出
3. curl 拉 live data.json，grep 关键字段确认非空
4. python -m http.server 本地起页面，浏览器打开看渲染
```

## 项目结构速查

```
index.html          — 前端单页应用 (9 Tab)
data.json           — 云端产出的数据文件 (被 Git 忽略)
run_update.py       — 统一数据更新入口 (替代旧5个脚本)
a_stock_data.py     — a-stock-data 28端点函数库
sector_fixed_stocks.py — 55+赛道固定标的池
.github/scripts/    — 旧独立脚本 (已被 run_update.py 替代)
  fetch_data.py     — 原行情采集
  fetch_news.py     — 原多源新闻 (新浪+东财公告+华尔街见闻)
  fetch_enrich.py   — 原增强层 (北向/龙虎榜/解禁/两融/热点)
  fetch_tierA.py    — 原 Tier A (全球资讯/行业排名/腾讯估值/公告/研报)
  fetch_tierB.py    — 原 Tier B (概念/个股信息/资金流/新闻)
  sentinel_ai.py    — AI 哨兵 (读 data.json → DeepSeek → 写简报)
  fetch_events.py   — 事件日历+布局生成
  score_sectors.py  — 赛道信号评分
  discover_sectors.py — 热门赛道发现
  build_briefing.py — 简报构建
  backtest.py       — 回测统计
.github/workflows/  — GitHub Actions
  market-update.yml — 每5分钟行情更新
  sentinel-ai.yml   — 每小时AI哨兵
  daily-briefing.yml — 每日简报
```
