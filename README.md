# 思源笔记 · 豆包插件

让豆包直接读写你本机的思源笔记：搜索、阅读、编写、整理。

插件本体不保存笔记数据，也不打包任何凭据。所有读写都由思源内核自带的 `siyuan` CLI 在本地完成，直接操作工作空间里的 `.sy` 文件——不启动 HTTP 服务、不需要 API token、不经过任何云端中转。

> 状态：v1.1.0 已提交豆包公开插件审核（2026-11-25），当前为「审核中」，等待平台审核结果。

## 插件包结构

```
siyuan/
├── plugin.json                  # 根清单：名称、版本、简介、图标
├── skills/siyuan/
│   ├── SKILL.md                 # 技能：连接确认、标准流程、写入规则
│   └── references/tools.md      # CLI 命令清单与输出陷阱
├── com.doubao/
│   ├── assets/plugin-icon.png   # 插件图标
│   └── cli.json                 # CLI 连接器：install / status / statusMatchRegex
└── scripts/
    ├── build.py                 # 校验并打包到 dist/
    └── smoke_test.py            # 零依赖的 CLI 自检
```

`cli.json` 声明一个连接器 `siyuan`，安装命令为 `npm install -g @siyuan-note/cli`，状态命令为 `siyuan --version`，匹配正则 `siyuan version \d+\.\d+\.\d+`。连接器不声明 `auth`：思源内核 CLI 不需要任何凭据。

## 使用前提

- 思源客户端 3.8+；`@siyuan-note/cli` 会自动定位内核，也可通过 `SIYUAN_CLI_BIN` 指定
- Windows 安装器默认已把内核目录加入 PATH；macOS / Linux 必要时按思源文档建立软链
- 豆包电脑版（CLI 连接器当前只在 PC 本地环境可用）
- 工作空间已通过思源客户端创建过（`workspace list` 能列出）

## 构建

只需要 Python 3.9+ 标准库。

```bash
python3 scripts/build.py --check   # 仅校验
python3 scripts/build.py           # 校验并生成 dist/siyuan-plugin-<version>.zip
```

压缩包是扁平结构，`plugin.json` 位于根目录；条目时间戳固定，同样的源码每次构建出的 sha256 一致。

## 自检

连接失败时先跑自检，它复现豆包加载连接器时的三步检查：

```bash
python3 scripts/smoke_test.py
python3 scripts/smoke_test.py --workspace "F:/SiYuan"
python3 scripts/smoke_test.py --command "/path/to/SiYuan-Kernel"
```

输出依次是 CLI 版本、注册的工作空间列表、实际选中的工作空间、笔记本数量。常见失败：

- 找不到 `siyuan` 命令 → 内核目录未加入 PATH
- `appearance files not found` → CLI 二进制与资源目录分离，改用客户端安装目录下的命令
- `not a valid workspace` → 传错工作空间路径；用 `workspace list` 取真实路径
- `0 notebooks` → 工作空间不对或尚未创建笔记本

注意：默认工作空间是 `~/SiYuan`，但单次 CLI 命令不会读取注册列表。多工作空间时必须显式传 `-w`，不要依赖默认值。

## 已知限制

- CLI 连接器只在豆包电脑版可用，手机端和网页端无法使用本插件
- 写操作没有交互确认，命令执行即落盘；Skill 要求先读后写、危险操作先征得用户确认，并用 `--dry-run` 预览
- CLI 主动拒绝加密笔记本上的操作；SQL 强制只读
- 写命令的输出格式不统一（`ok` / 纯 ID / `{"id": ...}`），Skill 已标注，避免误判为失败

## 许可证

AGPL-3.0，与思源笔记一致。
