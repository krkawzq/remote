# 快速入门指南

本指南将帮助你在 5 分钟内开始使用 Remote 工具。

## 📦 安装

```bash
# 克隆仓库
git clone <repository-url>
cd remote

# 使用 uv 安装（推荐）
uv pip install -e .

# 验证安装
remote --help
```

## 🎯 场景 1：同步配置到新服务器

### 步骤 1: 创建配置文件

创建 `server.toml`：

```toml
# 基本连接信息
host = "your-server-ip"
user = "root"
password = "your-password"
add_authorized_key = true

# 同步 shell 配置
[[file]]
src = "~/.bashrc"
dist = ":~/.bashrc"
mode = "update"

[[file]]
src = "~/.vimrc"
dist = ":~/.vimrc"
mode = "update"
```

### 步骤 2: 执行同步

```bash
# 同步并保存 SSH 配置
remote sync server.toml --ssh-config my-server

# 之后可以直接使用 SSH 别名
ssh my-server
```

## 🌐 场景 2：共享本地代理给远程服务器

### 前提条件

- 本地有运行的代理（如 Clash、V2Ray）
- 已有 SSH 配置（通过场景 1 创建或手动配置）

### 步骤 1: 启动反向代理

```bash
# 假设本地 Clash 运行在 7890 端口
remote proxy start my-server --local-port 7890 --remote-port 1081
```

输出：
```
[proxy] Started 'my-server' in background
[proxy] SSH host: my-server
[proxy] PID: 12345
[proxy] Remote port: 1081 -> Local: localhost:7890
[proxy] Use 'remote proxy status my-server' to check status
```

### 步骤 2: 在远程使用代理

SSH 到远程服务器：
```bash
ssh my-server
```

设置代理环境变量：
```bash
export http_proxy=http://localhost:1081
export https_proxy=http://localhost:1081

# 测试
curl https://www.google.com
```

### 步骤 3: 管理代理

```bash
# 查看状态
remote proxy status my-server

# 查看所有代理
remote proxy status

# 停止代理
remote proxy stop my-server
```

## 🚀 场景 3：批量初始化新服务器

### 准备脚本

创建目录结构：
```
my-setup/
├── config.toml
├── scripts/
│   ├── install_packages.sh
│   ├── config_git.sh
│   └── setup_zsh.sh
└── blocks/
    ├── aliases.sh
    └── env_vars.sh
```

### config.toml

```toml
host = "your-server-ip"
user = "root"
password = "your-password"
add_authorized_key = true

script_home = "./scripts"
block_home = "./blocks"

# 安装软件包
[[script]]
src = "install_packages.sh"
mode = "init"

# 配置 Git
[[script]]
src = "config_git.sh"
mode = "always"

# 安装 zsh
[[script]]
src = "setup_zsh.sh"
mode = "init"
flags = ["-l"]

# 配置块
[block]
dist = ":~/.bashrc"
group_mode = "incremental"

[[block.blocks]]
src = "aliases.sh"
mode = "update"

[[block.blocks]]
src = "env_vars.sh"
mode = "update"
```

### scripts/install_packages.sh

```bash
#!/bin/bash
apt update
apt install -y git vim tmux curl wget
```

### scripts/config_git.sh

```bash
#!/bin/bash
git config --global user.name "Your Name"
git config --global user.email "your@email.com"
```

### blocks/aliases.sh

```bash
# 常用别名
alias ll='ls -lah'
alias ..='cd ..'
alias gs='git status'
alias gp='git pull'
```

### 执行同步

```bash
cd my-setup
remote sync config.toml --ssh-config prod-server
```

## 💡 实用技巧

### 技巧 1: 使用 SSH Config

手动编辑 `~/.ssh/config`：

```
Host my-server
    HostName 192.168.1.100
    User root
    Port 22
    IdentityFile ~/.ssh/id_ed25519
    ServerAliveInterval 60
```

然后配置文件中只需：
```toml
ssh_config = "my-server"
```

### 技巧 2: 持久化代理设置

在远程服务器的 `~/.bashrc` 或 `~/.zshrc` 中添加：

```bash
# 使用 Remote 代理
export http_proxy=http://localhost:1081
export https_proxy=http://localhost:1081
export all_proxy=socks5://localhost:1081

# Git 代理
git config --global http.proxy http://localhost:1081
git config --global https.proxy http://localhost:1081
```

### 技巧 3: 自动启动代理

创建启动脚本 `start_proxy.sh`：

```bash
#!/bin/bash
remote proxy start server1 --local-port 7890 --remote-port 1081
remote proxy start server2 --local-port 7890 --remote-port 1082
remote proxy start server3 --local-port 7890 --remote-port 1083

echo "All proxies started"
remote proxy status
```

### 技巧 4: 测试代理性能

```bash
ssh my-server '
export http_proxy=http://localhost:1081
export https_proxy=http://localhost:1081

# 测试延迟
echo "=== 测试延迟 ==="
for i in {1..5}; do
  echo -n "第$i次: "
  curl -o /dev/null -s -w "%{time_total}s\n" https://www.google.com
done

# 测试下载速度
echo -e "\n=== 测试下载速度 ==="
curl -o /dev/null -w "速度: %{speed_download} bytes/s\n时间: %{time_total}s\n" \
  https://proof.ovh.net/files/10Mb.dat
'
```

## 🔧 常见问题

### Q: 首次连接需要输入密码？

A: 是的，如果还没有配置密钥认证。设置 `add_authorized_key = true` 后，工具会自动添加公钥，之后就可以免密登录。

### Q: 代理突然断开？

A: 检查网络连接和 SSH 会话。使用 `remote proxy status` 查看状态，如果停止了，重新启动即可。

### Q: 如何同时管理多个服务器？

A: 为每个服务器创建配置文件和 SSH 配置：
```bash
remote sync server1.toml --ssh-config server1
remote sync server2.toml --ssh-config server2
remote proxy start server1
remote proxy start server2
```

### Q: 配置块和文件同步的区别？

A: 
- **文件同步**：覆盖整个文件
- **配置块**：只更新文件中的特定标记块，保留其他内容

### Q: 如何查看错误日志？

A: 代理日志在 `~/.remote/proxy/`：
```bash
# 查看错误日志
cat ~/.remote/proxy/my-server.err

# 查看输出日志
cat ~/.remote/proxy/my-server.out
```

## 📚 进阶阅读

- [完整配置参考](../README.md#-详细文档)
- [配置块详解](../docs/remote.md)
- [Proxy 性能优化](../README.md#代理性能测试)

## 🎉 开始使用吧！

现在你已经掌握了基本用法，开始管理你的远程服务器吧！

如有问题，欢迎查阅 [README.md](../README.md) 或提交 Issue。

