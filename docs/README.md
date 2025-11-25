## Remote 文档总览

本文档目录用于索引 `remote` 项目的所有文档与设计说明，建议从「快速入门」开始阅读，然后根据需要查看使用指南和架构文档。

### 📚 入门与使用

- **快速入门**：[`QUICKSTART.md`](./QUICKSTART.md)  
  用几个典型场景（同步配置、共享代理、批量初始化服务器）带你在 5 分钟内上手。

- **使用指南**：[`usage.md`](./usage.md)  
  介绍 Proxy 相关的日常用法、新架构下的配置方式、日志系统和 CLI 体验等。

### 🏗 架构与设计

- **产品与问题背景**：[`remote.md`](./remote.md)  
  描述 remote 这个 SSH 管理工具要解决的典型痛点，以及早期 MVP 设计思路（脚本执行、文件同步、文本块同步）。

- **总体架构 ADR**：[`adr/remote-architecture.md`](./adr/remote-architecture.md)  
  以 ADR 形式记录从旧实现迁移到 Core / Domain / Adapters / Infrastructure 四层架构的决策与约束。

- **传输设计（Transfer）**：[`transfer-design.md`](./transfer-design.md)  
  详细说明断点续传、分块下载、并行传输等传输子系统的设计与实现思路。

### 📁 示例与配置

- **示例配置**：查看仓库根目录下的 `examples/` 目录：  
  - [`examples/proxy-config.toml`](../examples/proxy-config.toml)：Proxy 功能的示例配置文件，可配合 `remote proxy start --config` 使用。

更多 Sync / Transfer / Connect 的示例可以按 README 中的示例命令自行组合，也可以在实际使用过程中补充新的示例配置文件。


