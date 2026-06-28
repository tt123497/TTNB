# Legacy 脚本归档

这些脚本已被 `run_update.py` 统一入口替代，保留在此目录供参考。

## 原功能对照

| 废弃脚本 | 功能 | 替代方案 |
|---------|------|---------|
| auto_data.py | 自动数据采集 | run_update.py |
| auto_update.py | 自动更新逻辑 | run_update.py |
| fetch_prices.py | 价格抓取 | run_update.py → fetch_live_prices() |
| expand_sectors.py | 赛道扩展(12→63) | sector_fixed_stocks.py |
| build_layout.py | 布局重建 | run_update.py → fill_layout_stocks() |
| upgrade_briefing.py | 简报升级 | .github/scripts/sentinel_ai.py |
| upgrade_site.py | 站点升级 | 不再需要 |
| check.py / check_repo.py | 检查脚本 | run_update.py 自带完整性校验 |
| deploy_github.py | GitHub 部署 | .github/workflows/market-update.yml |
| gitee_deploy.py | Gitee 部署 | sync_to_gitee.py (如需) |
| netlify_deploy.py | Netlify 部署 | 不再需要 |
| sync_to_gitee.py | 同步到 Gitee | 按需保留 |
| github_push.py | GitHub 推送 | workflow 自动推送 |
| github_setup.py | GitHub 初始化 | 一次性脚本, 不再需要 |
| enable_pages.py~4 | Pages 启用(4个版本) | 一次性脚本, 不再需要 |
| find_pages.py | Pages 查找 | 一次性脚本, 不再需要 |
| add_ssh.py | SSH 配置 | 一次性脚本, 不再需要 |
| final_push.py | 最终部署 | 一次性脚本, 不再需要 |

**注意**: 这些脚本不再维护，如需数据更新请使用 `run_update.py`。
