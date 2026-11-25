# 更新记录

## 1.1.0 — 2026-11-25

- 方案从 MCP 切换为 CLI 连接器：豆包只接受公网 HTTPS 的 MCP，与思源本地使用场景冲突
- 移除 `mcp.json` 与 `com.doubao/auth/siyuan.json`，新增 `com.doubao/cli.json`（安装、状态检查、无鉴权）
- 技能改为思源 3.8 内核 CLI 命令用法，附真实命令清单与输出陷阱（写命令返回 `ok` / 纯 ID）
- 状态匹配正则按实测输出修正为 `siyuan version \d+\.\d+\.\d+`
- 构建校验改为检查 CLI 清单、禁止 MCP 与静态凭据残留；自检改为复现 CLI 三步检查
- README 写明 `@siyuan-note/cli` npm 包装包是公开上架的前置条件

## 1.0.0 — 2026-11-25

- 首个版本骨架：`plugin.json`、`mcp.json`、`skills/siyuan/SKILL.md`、`com.doubao/`
- 技能覆盖搜索、读取、写入、整理四类操作，附完整工具清单 `references/tools.md`
- 静态凭据：协议 / 主机 / 端口 / API token 四个字段
- 构建脚本 `scripts/build.py` 按豆包插件包结构校验并打包
- 自检脚本 `scripts/smoke_test.py` 复现 MCP 握手流程
