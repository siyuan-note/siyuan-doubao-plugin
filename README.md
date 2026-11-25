# 思源笔记 · 豆包插件

让豆包通过 MCP 直接读写你的思源笔记：搜索、阅读、编写、整理。

插件本体不保存笔记数据，也不打包任何凭据；所有读写都发生在你自己的思源内核上，token 由豆包保管，只发往你填写的思源地址。

> 状态：开发中，尚未提交上架审核。

## 插件包结构

```
siyuan/
├── plugin.json                  # 根清单：名称、版本、简介、图标、示例
├── skills/siyuan/
│   ├── SKILL.md                 # 技能：触发条件、标准流程、写入规则
│   └── references/tools.md      # 工具清单与常见坑
├── mcp.json                     # MCP 服务声明，URL 与鉴权用 ${VAR} 模板
├── com.doubao/
│   ├── assets/plugin-icon.png   # 插件图标
│   └── auth/siyuan.json         # 静态凭据表单：协议 / 主机 / 端口 / token
└── scripts/
    ├── build.py                 # 校验并打包到 dist/
    └── smoke_test.py            # 零依赖的 MCP 握手自检
```

传输是 MCP Streamable HTTP，端点为 `{scheme}://{host}:{port}/mcp`，请求头 `Authorization: Token <API token>`。

## 使用前提

- 思源 3.8.x 及以上，且内核正在运行
- 豆包客户端，插件运行在「本地电脑」
- 已在思源「设置 → 鉴权 → API token」取得 token
- 当前工作空间的 MCP 能力开关已开启

## 构建

只需要 Python 3.9+ 标准库。

```bash
python3 scripts/build.py --check   # 仅校验
python3 scripts/build.py           # 校验并生成 dist/siyuan-plugin-<version>.zip
```

压缩包是扁平结构，`plugin.json` 位于根目录；条目时间戳固定，同样的源码每次构建出的 sha256 一致。

## 自检

连接失败时先跑自检，它复现 `initialize` → `notifications/initialized` → `tools/list` 三步：

```bash
SIYUAN_API_TOKEN=xxxx python3 scripts/smoke_test.py
python3 scripts/smoke_test.py --url https://siyuan.example.com --token xxxx --insecure
```

返回 `401` 是 token 不对，`403` 是 token 不是管理员 token，`tools 0 available` 是工作空间 MCP 能力开关被关掉。

## 待平台校验的字段

`what-is-plugin` 说明了包结构的模块划分，但 `plugin.json`、`mcp.json`、`com.doubao/auth/*.json` 的字段细节以「包构成与清单文件」为准。本仓库这三处按语义先写好，上架前需要和平台文档逐字段核对；校验逻辑集中在 `scripts/build.py`，改清单不必动技能。

## 已知限制

- 云电脑模式下 `127.0.0.1` 指向云主机，连不到用户本机的思源
- 思源内核内置的 MCP 工具数量较多，模型存在选错工具的可能；技能里已做路由与坑位说明
- 加密笔记本、只读模式、MCP 能力开关依然生效，与在思源里操作一致

## 许可证

AGPL-3.0，与思源笔记一致。
