## Examples 示例说明

`examples/` 目录包含 `remote` 工具的示例配置文件，便于快速对照使用。

### Proxy 示例

- **`proxy-config.toml`**  
  一个最小可用的 Proxy 配置示例，对应命令：

  ```bash
  remote proxy start my-server --config examples/proxy-config.toml
  ```

  文件内容说明：

  ```toml
  [proxy]
  local_port = 7890      # 本地代理端口（例如 Clash 的端口）
  remote_port = 1081     # 远程映射端口
  mode = "http"          # 代理模式：http 或 socks5
  local_host = "localhost"
  ```

  你可以在此基础上增加自己的标签或环境信息，例如：

  ```toml
  [proxy.tags]
  environment = "production"
  region = "us-east"
  ```

### 后续扩展示例

建议将 Sync / Transfer / Connect 相关的典型配置也放在本目录，例如：

- `sync-config.toml`：同步 dotfiles、初始化脚本和配置块的示例
- `transfer-large-file.sh`：大文件并行/断点续传的示例脚本
- `connect-config.md`：常用 connect 命令示例与说明

当你增加新的示例文件时，可以在本 `README.md` 中补充一行简要说明，便于浏览。


