# Fitflare

[![Release checks](https://github.com/xw7qwq/health/actions/workflows/check.yml/badge.svg)](https://github.com/xw7qwq/health/actions/workflows/check.yml)

给自己用的健康数据同步服务：通过 Google Health API 同步自己的睡眠、活动、HRV 和静息心率，保留 Fitbit 历史记录，再把快照推送到 [lucius7.dev 面板](https://lucius7.dev/health/)展示。服务本身没有网页；授权和同步通过服务器命令行维护。

## 一个账户，一份记录

- 定时自动同步；连接、重新授权和手动同步通过服务器命令行完成。
- 同步后把指标、按日和按周的趋势以及最近的睡眠推送到面板，见 [DEPLOYMENT.md](DEPLOYMENT.md#推送到面板)。面板是查看记录的唯一入口。
- HTTP 只保留 `/api/health` 健康检查。旧网站的页面和文件路径 301 跳到 `https://lucius7.dev/health/`，旧的 `/api/*` 接口返回 `410 Gone` 并指向面板的接口说明，写入请求一律返回 `405`。

2026-10-25 起，原来的仪表盘网站、公开 API 和 API 文档并入面板（[panel](https://github.com/xw7qwq/panel)），这个仓库只负责同步和推送。

没有档案切换、家庭比较或创建多个档案的功能。后端、定时任务和面板推送只处理配置的唯一账户。已有 `profiles/<id>` 目录可以继续使用，不需要重命名或重新导入历史记录。

## 开始使用

当前可运行的部署方案是 **Linux + Docker Compose**，使用 Python 3.11、Flask 和 Gunicorn，无需数据库。

```bash
git clone https://github.com/xw7qwq/health.git fitflare
cd fitflare
cp deploy/.env.production.example .env
chmod 600 .env
```

编辑 `.env`：新安装的 `FITFLARE_PROFILE_ID=me` 表示唯一数据目录，从旧部署迁移时改成原目录名；要在面板上看到记录，填写 `FITFLARE_PANEL_INGEST_TOKEN`。随后：

```bash
sudo install -d -o 10001 -g 10001 -m 700 profiles
docker compose up -d --build
curl -fsS http://127.0.0.1:9000/api/health
```

在服务器命令行连接 Google Health 并首次同步：

```bash
docker exec -it fitflare-app python auth/authorize_google_health.py --configure --no-browser
docker exec fitflare-app python fetch/fetch_all.py
```

生产样例仅监听 `127.0.0.1:9000`。服务不需要公开域名；保留旧域名的反向代理只是为了让旧链接跳到面板。日常维护见 [DEPLOYMENT.md](DEPLOYMENT.md#运维命令)。

完整步骤、已有数据迁移、备份和回滚见 [DEPLOYMENT.md](DEPLOYMENT.md)；Google Cloud 配置与权限范围见 [GOOGLE_HEALTH.md](GOOGLE_HEALTH.md)。

## 数据来源

同步使用 Google Health API v4 和六项只读权限（活动、健康指标、睡眠、营养、个人资料、设置）。从 Fitbit 迁移的账户需要用关联原 Fitbit 账户的 Google 账号重新授权；迁移不会删除历史 CSV。Google Health 不再提供的数据（终身统计、徽章、闹钟等）保留为历史缓存。

## 开发

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock
python -m unittest discover -s tests -p 'test_*.py' -v
bash scripts/check.sh
```

`bash scripts/check.sh` 是完整的发布门禁，与 GitHub Actions 使用同一入口，需要 Docker：审计源码和 Git 历史，构建镜像并在镜像里运行单元测试，再启动一个合成数据容器，确认健康检查、跳转、`410` 和 `405` 都符合预期。所有测试只用合成数据。协作约定见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 仓库导航

| 路径 | 内容 |
| --- | --- |
| `server.py`、`backend/` | 健康检查、旧地址跳转、只读边界与同步调度 |
| `common/` | 数据路径、缓存、Google Health 客户端、指标和面板快照 |
| `auth/`、`fetch/` | 授权与数据同步；默认只处理配置账户 |
| `deploy/`、`scripts/` | 配置样例、检查、部署和面板推送工具 |
| `tests/` | 合成数据、访问隔离和跳转契约 |
| `docs/` | 来源、历史记录和 [Workers 可行性研究](docs/cloudflare-workers.md)（2026-09 的评估，展示部分现由面板承担） |
| `profiles/` | 本地私有运行数据，不进入 Git 或镜像 |

## 来源与数据

项目基于 [markrai/fitbaus](https://github.com/markrai/fitbaus)，继承自原 `theLucius7/fitbaus` 的服务器部署版本（旧仓库已删除）。作者和提交历史已保留；来源说明见 [docs/provenance.md](docs/provenance.md)。本项目与 Fitbit 或 Google 无隶属关系。

继承源码未提供标准许可证，原说明为 “This project is for personal use.”；本次整理不另行授予整个项目的开源许可证。

健康记录只通过面板展示；真实 `.env`、OAuth 凭据、原始健康数据文件、日志和备份均不进入仓库。安全与私密报告说明见 [SECURITY.md](SECURITY.md)。
