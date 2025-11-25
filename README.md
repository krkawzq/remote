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

## 📖 详细文档

### Sync 命令

#### 配置项说明

**连接配置**
```toml
host = "192.168.1.100"              # 远程主机地址
user = "root"                       # SSH 用户名
port = 22                           # SSH 端口（可选）
password = "password"               # 密码（可选）
key = "~/.ssh/id_ed25519"          # 私钥路径（可选）
add_authorized_key = true           # 自动添加公钥到远程
ssh_config = "my-server"            # 从 ~/.ssh/config 加载
timeout = 10                        # 连接超时（秒）
```

**文件同步**
```toml
[[file]]
src = "本地文件路径"
dist = ":远程文件路径"              # : 前缀表示远程路径
mode = "sync"                       # sync|update|init
```

模式说明：
- `sync`: 每次都同步（覆盖）
- `update`: 仅依赖src时间戳更新
- `init`: 仅第一次连接时同步

**脚本执行**
```toml
[[script]]
src = "脚本文件名"
mode = "always"                     # always|init
exec_mode = "exec"                  # exec|source
interpreter = "/bin/bash"           # 解释器
flags = ["-l"]                      # 解释器参数
args = ["arg1", "arg2"]            # 脚本参数
interactive = false                 # 是否交互式
allow_fail = false                  # 允许失败
```

**配置块**
```toml
[block]
dist = ":~/.bashrc"                 # 目标文件
group_mode = "incremental"          # incremental|override

[[block.blocks]]
src = "aliases.sh"                  # 配置块源文件
mode = "update"                     # update|init
```

配置块会在目标文件中插入标记：
```bash
# >>> remote:block:aliases.sh <<<
# 你的配置内容
# <<< remote:block:aliases.sh >>>
```

### Proxy 命令

#### 启动代理

```bash
remote proxy start <name> [OPTIONS]
```

选项：
- `--local-port, -l`: 本地代理端口（默认：7890）
- `--remote-port, -r`: 远程映射端口（默认：1081）
- `--mode, -m`: 代理模式 http|socks5（默认：http）
- `--local-host`: 本地代理地址（默认：localhost）
- `--foreground, -f`: 前台运行（默认后台）

示例：
```bash
# 使用默认端口
remote proxy start my-server

# 自定义端口
remote proxy start my-server -l 7897 -r 1082

# 前台运行（用于调试）
remote proxy start my-server --foreground
```

#### 查看状态

```bash
# 查看特定实例
remote proxy status my-server

# 查看所有实例
remote proxy status
```

#### 停止代理

```bash
# 停止特定实例
remote proxy stop my-server

# 停止所有实例
remote proxy stop
```

### Transfer 命令

#### 基本用法

```bash
remote transfer <src> <dst> [OPTIONS]
```

支持 SCP 兼容语法：
- `user@host:path` - 远程路径
- `./local/path` - 本地路径

#### 选项说明

**SCP 兼容选项：**
- `-P, --port`: SSH 端口（默认：22）
- `-p`: 保留文件权限和时间戳
- `-v`: 详细模式
- `-q`: 安静模式
- `-C`: 启用压缩
- `-l, --limit-rate`: 限制传输速率（如：1M, 100K）
- `-r`: 递归传输（暂不支持）

**传输增强选项：**
- `--resume/--no-resume`: 启用/禁用断点续传（默认：启用）
- `--force`: 强制重新传输（忽略清单文件）
- `--parallel`: 并行连接数（默认：4）
- `--aria2`: 启用 Aria2 模式（激进的并行传输）
- `--split`: Aria2 模式下的分块数（默认：32）
- `--chunk`: 分块大小（如：4M, 1MB）

#### 示例

```bash
# 基本传输
remote transfer ./file.txt user@host:/tmp/

# 并行传输大文件
remote transfer --parallel 16 big.iso host:big.iso

# Aria2 模式（最大速度）
remote transfer --aria2 --split 64 large_file.tar.gz host:large_file.tar.gz

# 限制传输速率
remote transfer -l 10M file.zip host:file.zip

# 强制重新传输
remote transfer --no-resume --force host:file.txt .
```

### Connect 命令

#### 启动交互式会话

```bash
remote connect <host> [OPTIONS]
```

支持多种主机格式：
- `hostname` - 使用 SSH 配置中的主机
- `user@host` - 指定用户名
- `user@host:port` - 指定用户名和端口

#### 选项说明

- `-u, --user`: SSH 用户名
- `-p, -P, --port`: SSH 端口
- `--password`: 提示输入密码
- `-i, --key`: SSH 密钥文件路径
- `--threshold`: 大文件阈值（如：100M）
- `--parallel`: 并行连接数
- `--chunk`: 分块大小（如：4M）
- `--timeout`: 连接超时（秒）

#### 内置命令

在交互式 shell 中可用的命令：

- `cp <src> <dst>` - 复制文件（支持 `:` 前缀表示远程路径）
- `ls [path]` - 列出目录内容
- `cd <path>` - 切换目录
- `pwd` - 显示当前工作目录（本地和远程）
- `cat <path>` - 显示文件内容
- `mkdir <path>` - 创建目录
- `rm <path>` - 删除文件或目录
- `du [path]` - 显示磁盘使用情况
- `stat <path>` - 显示文件状态
- `config [show|set]` - 显示或设置配置
- `status` - 显示会话状态
- `clear` - 清屏
- `help [command]` - 显示帮助
- `exit` - 退出会话

#### 路径格式

- `:path` 或 `:~/path` - 远程路径
- `path` 或 `~/path` - 本地路径

#### 命令转发

- `!command` - 在当前上下文执行命令
- `!local command` - 在本地执行命令
- `!remote command` - 在远程执行命令

#### 示例

```bash
# 基本连接
remote connect my-server

# 使用密码认证
remote connect host --password

# 配置传输参数
remote connect host --threshold 50M --parallel 8

# 在交互式 shell 中
[local] $ ls :~/data              # 列出远程目录
[local] $ cd :~/projects           # 切换到远程目录
[remote] $ cp :~/file.txt .       # 下载文件
[remote] $ cp ./local.txt :~/     # 上传文件
[remote] $ cat :~/config.txt      # 查看远程文件
[remote] $ !pwd                   # 执行远程命令
[remote] $ !local ls -la         # 执行本地命令
```

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

## 📝 配置示例

完整的配置文件示例：

```toml
# 基本连接信息
host = "192.168.1.100"
user = "root"
key = "~/.ssh/id_ed25519"
add_authorized_key = true

# 解释器配置
interpreter = "/bin/bash"
interpreter_flags = ["-l"]

# 路径配置
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
mode = "update"

[[file]]
src = "~/.ssh/authorized_keys"
dist = ":~/.ssh/authorized_keys"
mode = "init"

# 初始化脚本
[[script]]
src = "install_zsh.sh"
mode = "init"
flags = ["-l"]

[[script]]
src = "install_packages.sh"
mode = "init"
allow_fail = true

[[script]]
src = "config_git.sh"
mode = "always"

# 配置块
[block]
dist = ":~/.zshrc"
group_mode = "incremental"

[[block.blocks]]
src = "aliases.sh"
mode = "update"

[[block.blocks]]
src = "env_vars.sh"
mode = "update"

[[block.blocks]]
src = "functions.sh"
mode = "update"
```

## 🤝 贡献

欢迎贡献代码、报告问题或提出建议！

## 📄 许可证

MIT License

## 🔗 相关链接

- [Paramiko 文档](https://docs.paramiko.org/)
- [Typer 文档](https://typer.tiangolo.com/)
- [SSH 配置指南](https://www.ssh.com/academy/ssh/config)

## ❓ 常见问题

### Q: 如何处理密码认证？

A: 在配置文件中设置 `password` 字段，或在命令行交互式输入。建议使用密钥认证更安全。

### Q: 代理无法连接？

A: 检查以下几点：
1. 本地代理是否正常运行（如 Clash）
2. SSH 配置是否正确（`~/.ssh/config`）
3. 远程服务器是否支持反向端口转发
4. 查看日志：`cat ~/.remote/proxy/<name>.err`

### Q: 如何更新已同步的文件？

A: 使用 `mode = "update"` 或 `mode = "sync"`，再次运行 sync 命令。

### Q: 配置块如何工作？

A: 工具会在目标文件中查找或创建标记块：
```bash
# >>> remote:block:aliases.sh <<<
内容
# <<< remote:block:aliases.sh >>>
```

只更新标记块内的内容，其他内容保持不变。

### Q: 如何同时管理多个远程服务器？

A: 为每个服务器创建独立的配置文件和 SSH 配置名：
```bash
remote sync server1.toml --ssh-config server1
remote sync server2.toml --ssh-config server2
remote proxy start server1 -l 7890 -r 1081
remote proxy start server2 -l 7890 -r 1082
```

### Q: Transfer 命令支持断点续传吗？

A: 是的，默认启用断点续传。传输进度保存在 `~/.remote/transfer/` 目录下。使用 `--no-resume` 可以禁用，`--force` 可以强制重新传输。

### Q: Connect 交互式 shell 中的路径如何区分本地和远程？

A: 使用 `:` 前缀表示远程路径：
- `:~/file.txt` 或 `:/path/to/file` - 远程路径
- `~/file.txt` 或 `./file.txt` - 本地路径

### Q: 如何提高大文件传输速度？

A: 可以使用以下方法：
1. 增加并行连接数：`--parallel 16`
2. 使用 Aria2 模式：`--aria2 --split 64`
3. 调整分块大小：`--chunk 8M`

---

**Enjoy! 🎉**

