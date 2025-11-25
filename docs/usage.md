# Remote 工具使用指南

## 快速开始

### 安装

```bash
# 使用 uv（推荐）
uv pip install -e .

# 或使用 pip
pip install -e .
```

### 基本使用

#### Proxy 命令

启动代理：
```bash
remote proxy start my-server
remote proxy start my-server --local-port 7890 --remote-port 1081
```

查看状态：
```bash
remote proxy status
remote proxy status my-server
```

停止代理：
```bash
remote proxy stop my-server
remote proxy stop  # 停止所有实例
```

## 新架构特性

### 1. 增强的日志系统

使用 Rich 提供美观的结构化日志：

```bash
# 设置日志级别
remote --log-level DEBUG proxy start my-server

# 输出到文件
remote --log-file ~/.remote/logs/remote.log proxy start my-server
```

日志输出到 stderr，业务输出到 stdout，便于区分和重定向。

### 2. 丰富的配置选项

支持多种配置来源，优先级：环境变量 > CLI 参数 > TOML 配置 > 默认值

**环境变量：**
```bash
export REMOTE_PROXY_LOCAL_PORT=7890
export REMOTE_PROXY_REMOTE_PORT=1081
remote proxy start my-server
```

**CLI 参数：**
```bash
remote proxy start my-server \
  --local-port 7890 \
  --remote-port 1081 \
  --mode http \
  --local-host localhost
```

**配置文件：**
```toml
# config.toml
[proxy]
local_port = 7890
remote_port = 1081
mode = "http"
local_host = "localhost"
```

```bash
remote proxy start my-server --config config.toml
```

### 3. 友好的用户提示

所有提示信息使用 Rich 渲染，提供：
- 彩色输出
- 清晰的错误信息
- 交互式确认
- 表格化状态显示

### 4. 增强的命令参数

```bash
# 前台运行（用于调试）
remote proxy start my-server --foreground

# 自定义日志级别
remote --log-level DEBUG proxy start my-server

# 使用配置文件
remote proxy start my-server --config config.toml
```

## 架构说明

新架构采用三层设计：

1. **Core 层**：核心基础设施（连接、日志、配置）
2. **Domain 层**：业务逻辑（Proxy 服务、Sync 服务）
3. **Adapters 层**：外部接口（CLI、配置加载）

这种设计使得：
- 代码结构清晰，易于维护
- 业务逻辑可独立测试
- 易于扩展新功能
- 支持多种存储后端

## 迁移指南

### 从旧版本迁移

旧版本的命令基本兼容，但有以下改进：

1. **日志系统**：现在使用 Rich，输出更美观
2. **配置系统**：支持环境变量和配置文件合并
3. **错误提示**：更友好的错误信息和上下文

### 配置迁移

旧版本的配置仍然有效，但建议使用新的配置方式：

```bash
# 旧方式（仍然支持）
remote proxy start my-server -l 7890 -r 1081

# 新方式（推荐）
remote proxy start my-server --config config.toml
```

## 示例场景

### 场景1：多代理实例

```bash
# 启动多个代理实例
remote proxy start server1 --local-port 7890 --remote-port 1081
remote proxy start server2 --local-port 7891 --remote-port 1082

# 查看所有实例
remote proxy status

# 停止所有实例
remote proxy stop
```

### 场景2：使用配置文件

创建 `proxy.toml`：
```toml
[proxy]
local_port = 7890
remote_port = 1081
mode = "http"
local_host = "localhost"
```

```bash
remote proxy start my-server --config proxy.toml
```

### 场景3：调试模式

```bash
# 前台运行，查看详细日志
remote --log-level DEBUG proxy start my-server --foreground
```

## 故障排查

### 查看日志

日志文件位置：`~/.remote/proxy/<name>.out` 和 `~/.remote/proxy/<name>.err`

```bash
# 查看标准输出日志
cat ~/.remote/proxy/my-server.out

# 查看错误日志
cat ~/.remote/proxy/my-server.err
```

### 常见问题

**Q: 代理无法启动？**
- 检查 SSH 配置是否正确
- 确认本地代理服务是否运行
- 查看错误日志：`cat ~/.remote/proxy/<name>.err`

**Q: 如何查看详细日志？**
```bash
remote --log-level DEBUG proxy start my-server --foreground
```

**Q: 如何停止所有代理？**
```bash
remote proxy stop
```

## 高级用法

### 自定义日志文件

```bash
remote --log-file /path/to/logfile.log proxy start my-server
```

### 环境变量配置

```bash
export REMOTE_PROXY_LOCAL_PORT=7890
export REMOTE_PROXY_REMOTE_PORT=1081
export REMOTE_PROXY_MODE=http
remote proxy start my-server
```

### 配置文件合并

配置文件会与环境变量和 CLI 参数合并，优先级：
1. CLI 参数（最高）
2. 环境变量
3. TOML 配置
4. 默认值（最低）

