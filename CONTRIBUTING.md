# 开发与维护

环境使用 Python 3.11，安装步骤见 [README](README.md#开发)。运行依赖固定在 `requirements.lock`；完整检查还需要 Docker。

## 提交变更

1. 从最新的 `main` 创建短期工作分支（`feat/`、`fix/`、`chore/` 或 `docs/`），说明改动的触发条件、预期行为和验证方法。
2. 先运行相关测试，提交前运行 `bash scripts/check.sh`，它与 GitHub Actions 使用同一入口。
3. 检查 `git diff --check`、`python3 scripts/audit.py`、`python3 scripts/audit_history.py` 和 `git status`，只提交源码、文档和配置样例。历史审计需要完整克隆，浅克隆请先执行 `git fetch --unshallow`。
4. 发起面向 `main` 的 PR。主分支要求与最新基线同步、`check` 成功并解决评审讨论；管理员也遵守此规则，不直接推送或强推 `main`。单人维护不要求额外的批准人。
5. 一般使用 squash 合并；需要保留多个有意义的提交时使用 merge commit。远端工作分支合并后自动删除，本地确认改动已进入 `main` 后清理，并执行 `git fetch --prune`。
6. CI 通过不表示已部署。只从干净且与 `origin/main` 一致的 `main` 发布，升级见 [DEPLOYMENT.md](DEPLOYMENT.md#更新与回滚)。

`python3 -m unittest discover -s tests -p 'test_*.py' -v` 运行单元测试。完整的 `bash scripts/check.sh` 还会构建镜像、在镜像里运行这些测试，并检查合成数据容器的健康接口、跳转和写入边界，需要 Docker。

所有检查使用生成的 Demo/Hidden 合成档案。不要将生产 `profiles/` 挂载到测试容器；冒烟检查只连接合成数据容器，不使用生产地址。

仓库启用密钥扫描和推送保护。不要绕过凭据告警；先撤销或轮换泄露值，再处理提交。历史审计额外阻止已知的旧 Fitbit 凭据对象经分支或标签重新进入仓库，但不替代通用密钥扫描。不要执行未经审查的 `git push --all`、`git push --tags` 或镜像推送。

## HTTP 与面板

HTTP 只保留 `/api/health`。展示和公开接口在 [面板](https://github.com/xw7qwq/panel)，不要在这里加回页面或数据接口。推送的快照由 `common/panel_push.py` 生成，改动格式时同时更新面板的接收端和 `tests/test_panel_push.py`。

## 兼容性与数据

- 单账户是产品边界：命令行维护、定时任务和面板推送只处理 `FITFLARE_PROFILE_ID`。测试中额外放置 Hidden 目录是为了证明隔离，不是多用户能力。
- 保持 `FITFLARE_*` 变量名与 Compose 服务名 `fitflare`、容器名 `fitflare-app` 稳定。
- 修改数据结构前准备迁移与恢复方式，不能只依赖旧镜像回滚。
- 不提交 `.env`、授权信息、健康记录、备份、日志或带真实数据的截图；文件审计不能替代人工确认。
- 更新依赖时同步维护锁文件，并完成整套发布检查。
- 继承源码和第三方组件说明见 [来源记录](docs/provenance.md)。
