# Remote

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

一个强大的 SSH 远程服务器管理工具，提供配置同步、反向代理、文件传输和交互式连接功能。

## ✨ 主要特性

### 📦 配置同步 (Sync)
- **文件同步**：自动同步本地文件到远程服务器
- **脚本执行**：批量执行初始化脚本
- **配置块管理**：增量更新配置文件的特定部分
- **SSH 配置**：自动生成和管理 SSH 配置
- **密钥管理**：自动添加公钥到远程服务器

### 🌐 反向代理 (Proxy)
- **反向隧道**：通过 SSH 建立反向代理隧道
- **后台运行**：支持后台守护进程模式
- **多实例**：支持同时管理多个代理实例
- **状态管理**：查看代理状态和日志
- **跨平台**：使用 Paramiko 实现，完全跨平台

### 📤 文件传输 (Transfer)
- **断点续传**：支持大文件断点续传，自动保存传输进度
- **并行传输**：多连接并行下载，提升传输速度
- **Aria2 模式**：激进的并行传输模式，适合大文件
- **SCP 兼容**：兼容 SCP 命令行参数和语法
- **进度显示**：实时显示传输进度和速度

### 🔌 交互式连接 (Connect)
- **统一接口**：统一的本地和远程文件管理接口
- **内置命令**：提供 cp、ls、cd、pwd、cat、mkdir、rm 等常用命令
- **路径前缀**：使用 `:` 前缀区分远程路径（如 `:~/file.txt`）
- **命令转发**：支持 `!command` 转发本地或远程命令
- **Tab 补全**：智能路径补全，支持本地和远程路径
- **上下文切换**：自动跟踪当前工作目录上下文

## 🚀 快速开始

### 安装

使用 uv（推荐）：
```bash
uv pip install -e .
```

或使用 pip：
```bash
pip install -e .
```

### 基本使用

#### 1. 同步远程服务器配置

创建配置文件 `config.toml`：

```toml
# SSH 连接配置
host = "192.168.1.100"
user = "root"
password = "your_password"  # 或使用 key
key = "~/.ssh/id_ed25519"
add_authorized_key = true

# 脚本和配置路径
block_home = "~/remote/blocks"
script_home = "~/remote/scripts"

# 文件同步
[[file]]
src = "~/.zshrc"
dist = ":~/.zshrc"
mode = "update"

[[file]]
src = "~/.tmux.conf"
dist = ":~/.tmux.conf"
mode = "init"

# 脚本执行
[[script]]
src = "install_zsh.sh"
mode = "init"

[[script]]
src = "apt_packages.sh"
mode = "always"

# 配置块（增量更新配置文件）
[block]
dist = ":~/.bashrc"
group_mode = "incremental"
blocks = [
    { src = "aliases.sh", mode = "update" },
    { src = "env_vars.sh", mode = "update" }
]
```

执行同步：
```bash
# 基本同步
remote sync config.toml

# 同步并保存 SSH 配置
remote sync config.toml --ssh-config my-server
```

#### 2. 使用反向代理

将本地代理（如 Clash）共享给远程服务器使用：

```bash
# 启动代理（后台运行）
remote proxy start my-server --local-port 7890 --remote-port 1081

# 查看状态
remote proxy status my-server

# 查看所有实例
remote proxy status

# 停止代理
remote proxy stop my-server

# 停止所有实例
remote proxy stop
```

在远程服务器上使用代理：
```bash
ssh my-server

# 设置代理环境变量
export http_proxy=http://localhost:1081
export https_proxy=http://localhost:1081
export all_proxy=socks5://localhost:1081

# 测试代理
curl https://www.google.com
```

#### 3. 文件传输

传输文件支持断点续传和并行下载：

```bash
# 上传文件到远程服务器
remote transfer ./file.txt user@host:/tmp/

# 从远程服务器下载文件
remote transfer user@host:~/data.zip .

# 使用并行传输加速大文件
remote transfer --parallel 8 big.iso host:big.iso

# Aria2 模式（激进的并行传输）
remote transfer --aria2 --split 32 large_file.tar.gz host:large_file.tar.gz

# 禁用断点续传，强制重新传输
remote transfer --no-resume --force host:file.txt .
```

#### 4. 交互式连接

启动交互式会话，统一管理本地和远程文件：

```bash
# 连接到远程服务器
remote connect my-server

# 使用用户名和端口
remote connect user@host:2222

# 使用密码认证
remote connect host --password

# 配置传输参数
remote connect host --threshold 50M --parallel 8 --chunk 4M
```

在交互式 shell 中：

```bash
[local] $ ls                    # 列出本地目录
[local] $ ls :~/data            # 列出远程目录
[local] $ cd :~/projects        # 切换到远程目录
[remote] $ cp :~/file.txt .    # 下载文件
[remote] $ cp ./local.txt :~/  # 上传文件
[remote] $ cat :~/config.txt   # 查看远程文件
[remote] $ !pwd                # 执行远程命令
[remote] $ !local ls           # 执行本地命令
[remote] $ help                # 查看帮助
```

## 📖 文档

- 详细使用说明和更多示例请参考 `docs/` 目录：
  - `docs/QUICKSTART.md`：快速开始与典型场景
  - `docs/usage.md`：进阶用法、配置系统与故障排查
  - `docs/README.md`：完整文档索引

## 🔧 高级用法

### 多环境配置

为不同服务器创建不同配置文件：

```bash
remote sync prod.toml --ssh-config prod-server
remote sync dev.toml --ssh-config dev-server
remote sync staging.toml --ssh-config staging-server
```

### 配置块的增量更新

适用于需要在远程服务器上保留其他配置，只更新特定部分的场景：

```toml
[block]
dist = ":~/.bashrc"
group_mode = "incremental"
blocks = [
    { src = "custom_aliases.sh", mode = "update" },
    { src = "project_env.sh", mode = "update" }
]
```

每次同步只更新标记块，其他内容保持不变。

### 密钥认证

自动生成并配置 SSH 密钥：

```toml
# 使用现有密钥
key = "~/.ssh/id_ed25519"
add_authorized_key = true

# 首次连接使用密码
password = "initial_password"
add_authorized_key = true
```

首次连接后，工具会自动将公钥添加到远程服务器，后续连接使用密钥认证。

### 代理性能测试

在远程服务器上测试代理速度：

```bash
ssh my-server '
export http_proxy=http://localhost:1081
export https_proxy=http://localhost:1081

# 测试延迟
curl -o /dev/null -s -w "总时间: %{time_total}s\n" https://www.google.com

# 测试下载速度
curl -o /dev/null -w "速度: %{speed_download} bytes/s\n" \
  https://proof.ovh.net/files/10Mb.dat
'
```

## 📁 项目结构

```
remote/
├── remote/
│   ├── core/                    # 核心基础设施层
│   │   ├── client.py            # SSH 客户端封装
│   │   ├── constants.py         # 常量定义
│   │   ├── exceptions.py        # 异常定义
│   │   ├── interfaces.py        # 接口定义
│   │   ├── logging.py           # 日志系统
│   │   ├── telemetry.py         # 可观测性
│   │   ├── utils.py             # 工具函数
│   │   └── system/              # 系统操作
│   │       └── machine.py       # 机器状态管理
│   ├── domain/                  # 业务逻辑层
│   │   ├── proxy/               # 代理域
│   │   │   ├── models.py        # 代理模型
│   │   │   ├── service.py       # 代理服务
│   │   │   └── tunnel.py        # SSH 隧道实现
│   │   ├── sync/                # 同步域
│   │   │   ├── models.py        # 同步模型
│   │   │   ├── service.py       # 同步服务
│   │   │   ├── file_sync.py    # 文件同步
│   │   │   ├── block_sync.py    # 配置块管理
│   │   │   └── script_exec.py   # 脚本执行
│   │   └── transfer/            # 传输域
│   │       ├── models.py        # 传输模型和配置
│   │       ├── service.py       # 传输服务（断点续传、并行传输）
│   │       ├── downloader.py    # 下载器实现
│   │       ├── uploader.py      # 上传器实现
│   │       ├── chunk.py         # 分块管理
│   │       ├── manifest.py     # 传输清单管理
│   │       ├── parser.py        # 路径解析
│   │       └── connect/         # 连接会话域
│   │           ├── models.py    # 会话模型
│   │           ├── session.py   # 会话管理
│   │           ├── transfer.py  # 会话内传输处理
│   │           ├── command_parser.py # 命令解析
│   │           ├── path_resolver.py # 路径解析
│   │           └── exec_helpers.py  # 执行辅助函数
│   ├── adapters/                # 适配器层
│   │   ├── cli/                 # CLI 适配器
│   │   │   ├── app.py           # CLI 入口
│   │   │   ├── proxy.py         # 代理命令
│   │   │   ├── sync.py          # 同步命令
│   │   │   ├── transfer/        # 传输命令
│   │   │   │   ├── main.py      # 传输命令注册
│   │   │   │   └── transfer.py  # 传输命令实现
│   │   │   ├── connect/         # 连接命令
│   │   │   │   ├── main.py      # 连接命令入口
│   │   │   │   ├── shell.py     # 交互式 shell
│   │   │   │   ├── builtin_commands.py # 内置命令
│   │   │   │   ├── command_executor.py # 命令执行器
│   │   │   │   ├── config_manager.py   # 配置管理
│   │   │   │   ├── host_parser.py      # 主机解析
│   │   │   │   └── utils.py            # 工具函数
│   │   │   ├── connection.py    # 连接工厂
│   │   │   └── prompts.py       # 用户提示
│   │   └── config/              # 配置适配器
│   │       ├── loader.py        # 配置加载器
│   │       └── sync_parser.py   # 同步配置解析
│   └── infrastructure/          # 基础设施实现
│       └── state/               # 状态存储
│           └── file_store.py    # 文件状态存储
├── docs/                        # 文档目录
├── examples/                    # 示例配置
├── pyproject.toml               # 项目配置
└── README.md                    # 本文档
```

## 🛠️ 技术栈

- **Python 3.10+**: 现代 Python 特性
- **Paramiko**: SSH 协议实现
- **Typer**: CLI 框架
- **Rich**: 美观的终端输出和日志
- **Cryptography**: 加密支持

## 🎨 新特性

### 增强的日志系统
- 使用 Rich 提供结构化、彩色日志输出
- 日志输出到 stderr，业务输出到 stdout
- 支持日志级别和文件输出

### 丰富的配置选项
- 支持环境变量、CLI 参数、TOML 配置文件
- 配置优先级：CLI > 环境变量 > TOML > 默认值
- 配置文件合并支持

### 友好的用户体验
- Rich 渲染的提示信息
- 清晰的错误上下文
- 表格化状态显示
- 交互式确认

### 可扩展架构
- 三层架构设计（Core/Domain/Adapters）
- 接口抽象，易于扩展
- 业务逻辑与 IO 分离

## 🤝 贡献

欢迎贡献代码、报告问题或提出建议！

## 📄 许可证

MIT License

## 🔗 相关链接

- [Paramiko 文档](https://docs.paramiko.org/)
- [Typer 文档](https://typer.tiangolo.com/)
- [SSH 配置指南](https://www.ssh.com/academy/ssh/config)

**Enjoy! 🎉**
