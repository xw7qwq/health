# 来源与迁移记录

## 项目来源

fitflare 整理自 `lucius7` 服务器 `/home/lucius7/fitbaus` 的部署源码。原远端为 [theLucius7/fitbaus](https://github.com/theLucius7/fitbaus)，GitHub 显示它是 [markrai/fitbaus](https://github.com/markrai/fitbaus) 的 fork。原始 FitBaus 作者提交以 Mark Rai 署名，后续部署改动的作者信息也予以保留。

迁移时服务器分支为 `maintenance/api-docs-20260923`，提交 `f9146f8ab7c827d5f360f382402112c80e2d10dd`。运行容器与工作树的入口、配置及依赖文件已做 SHA-256 对照。此记录只描述取材版本，不保证今后的线上状态。

## 历史整理

迁移保留原来的 30 条提交及作者、提交说明。早期 8 条提交曾引用一个在源码中硬编码的 Fitbit 客户端密钥，当前部署源码已移除此值。上传前在本地净化该历史 blob，并检查全部可达 Git 对象中不再包含该值。没有将密钥写入此记录。

净化后的部署基线为 `74bbdb9de9021b992f329ee1079bc0ea366398d0`。清理改变了提交 ID，但基线源码树与原部署提交完全一致。服务器原仓库、运行配置、授权状态和健康数据未因整理而修改。历史清理不代表旧凭据已经撤销或轮换。

新维护分支为 `main`，只发布净化后的历史；服务器旧分支和标签不直接上传。不要从原历史直接合并或强制同步，否则可能重新引入已删除的值。需要带入旧仓库改动时，应在独立环境审查补丁后应用。

`docs/history/` 保存有日期的原始改造记录，旧提交、镜像标签、服务器路径和验证结论属于当时的上下文。当前安装与维护以根目录 README、DEPLOYMENT 和 API 文档为准。

## 2026-10-23 分支整合收尾

[PR #1](https://github.com/xw7qwq/health/pull/1) 将 Google Health API v4 的线上实现与私有单账户重构合并到 `main`，合并提交为 `948992d977c4c874813e4c857054210369a978da`。新仓库原有提交仍在历史中，没有强推。该提交的 Release checks 已通过。

收尾时核对远端只保留 `main`，没有待合并 PR 或远端标签。服务器本地残留的三个 2026-09-23 标签仍指向净化前历史；已在仓库外做权限受限的私有 bundle 备份并移除这些本地标签。新仓库的 `main` 不包含已知的旧凭据对象。发布门禁现包含历史审计，防止旧标签或分支误推后再次混入。

上述处理没有更改旧公开仓库 `theLucius7/fitbaus`，也不能证明旧 Fitbit 密钥已撤销。旧凭据仍需在提供方后台撤销或重置。

## 2026-10-23 公开只读整理

用户确认旧仓库 `theLucius7/fitbaus` 已删除，旧 Fitbit 认证也已在提供方删除。这是用户提供的处理结果；本仓库没有保存或重新启用旧密钥。

[PR #3](https://github.com/xw7qwq/health/pull/3) 修复静态资源缓存指纹，[PR #4](https://github.com/xw7qwq/health/pull/4) 修复趋势方向、比较窗口和 HTTPS 链接。公开只读整理保留这些改动，并按当前部署需求移除网页登录、会话、管理面板、原始文件下载和全部 HTTP 写入入口。Google Health 授权和手动同步通过服务器命令行完成，自动同步与历史数据保留。

当时网站和 API 直接展示配置账户的数据，从旧私有版本升级需要显式设置 `FITFLARE_DATA_ACCESS=public`。当前操作说明以 README、DEPLOYMENT 和 GOOGLE_HEALTH 为准，上面的私有模式记录仅描述先前版本。

## 2026-10-25 网站并入面板

仪表盘网站、公开 API 和 API 文档并入 lucius7.dev 面板（[panel](https://github.com/xw7qwq/panel)），面板从 Fitflare 推送的快照展示数据。本仓库删除了前端、模板、文档生成器、浏览器测试和 Node 工具链，HTTP 只保留健康检查：旧页面 301 跳到面板，旧接口返回 `410`。同步、授权、面板推送和历史数据不变，`FITFLARE_DATA_ACCESS` 不再读取。

## 许可与第三方组件

继承源码没有标准 `LICENSE`、`COPYING` 或 `NOTICE` 文件，原 README 仅说明：

> This project is for personal use.

本次整理不另行授权原项目，也不将整个仓库标记为 MIT。使用和再分发时应核对原作者说明及依赖自身的许可。

2026-10-25 之前的版本在 `vendor/chart.umd-4.4.1.min.js` 中附带 Chart.js 4.4.1（Chart.js Contributors，MIT）和 `@kurkle/color` 0.3.2（Jukka Kurkela，MIT），版权声明未被修改；网站并入面板后已不再包含该文件。其余依赖的版本见 `requirements.lock`。
