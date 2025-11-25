# Transfer 模块设计文档 v2.0

## 1. 设计目标

### 1.1 核心功能
- ✅ 支持 SCP 兼容的路径格式 (`user@host:path`)
- ✅ 断点续传（默认开启，可关闭）
- ✅ 并发传输（多连接）
- ✅ Aria2 模式（超高速分块传输）
- ✅ 进度显示（Rich 进度条）
- ✅ 完整性校验（SHA256）
- ✅ 错误重试机制
- ✅ 速度限制
- ⚠️ 文件权限保留（待实现）
- ⚠️ 压缩传输（待实现）

### 1.2 设计原则
1. **简单优先**：小文件用单连接，大文件自动切换多连接
2. **安全可靠**：所有操作都有错误处理和回滚机制
3. **用户友好**：清晰的进度显示，有意义的错误信息
4. **性能优化**：智能分块策略，避免过度并发
5. **状态管理**：manifest 独立管理，支持清理

## 2. 架构设计

### 2.1 模块结构
```
domain/transfer/
├── __init__.py           # 导出接口
├── models.py             # 数据模型
├── parser.py             # 路径解析
├── manifest.py           # Manifest 管理
├── chunking.py           # 分块策略（重命名自 chunk.py）
├── engine.py             # 传输引擎（统一 downloader/uploader）
├── verifier.py           # 校验器（新增）
├── progress.py           # 进度管理（新增）
└── service.py            # 服务层
```

### 2.2 数据流
```
CLI → Service → Engine → SFTP
          ↓
      Manifest ← Chunking
          ↓
      Progress → Rich Progress Bar
          ↓
      Verifier → SHA256
```

## 3. 核心组件设计

### 3.1 数据模型 (models.py)

#### TransferConfig
```python
@dataclass
class TransferConfig:
    # 传输控制
    resume: bool = True
    force: bool = False
    parallel: int = 4
    aria2: bool = False
    chunk_size: int = 4 * 1024 * 1024  # 4MB
    
    # 高级选项
    preserve_permissions: bool = False
    compress: bool = False
    limit_rate: Optional[int] = None
    
    # 连接设置
    ssh_port: int = 22
    timeout: int = 30
    
    # 重试策略
    max_retries: int = 3
    retry_delay: float = 1.0
```

#### Endpoint
```python
@dataclass
class Endpoint:
    path: str
    is_local: bool
    host: Optional[str] = None
    user: Optional[str] = None
    port: int = 22
    key_file: Optional[str] = None
```

#### TransferTask
```python
@dataclass
class TransferTask:
    """完整的传输任务描述"""
    id: str  # 唯一标识
    src: Endpoint
    dst: Endpoint
    config: TransferConfig
    
    # 文件信息
    file_size: int
    file_mtime: float
    file_hash: Optional[str] = None
    
    # 状态
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
```

#### Chunk
```python
@dataclass
class Chunk:
    index: int
    offset: int
    size: int
    status: ChunkStatus = ChunkStatus.PENDING
    sha256: Optional[str] = None
    attempts: int = 0
    error: Optional[str] = None
```

### 3.2 路径解析 (parser.py)

#### 功能
- 解析 SCP 格式路径
- 从 SSH config 加载配置
- 解析相对路径和绝对路径
- 扩展 `~` 为用户主目录

#### 关键函数
```python
def parse_path(path: str, ssh_port: int = 22) -> Endpoint:
    """解析路径为 Endpoint"""
    
def resolve_path(client: Optional[RemoteClient], endpoint: Endpoint) -> Endpoint:
    """解析相对路径和 ~ 扩展"""
    
def generate_task_id(src: Endpoint, dst: Endpoint) -> str:
    """生成任务唯一标识"""
```

### 3.3 Manifest 管理 (manifest.py)

#### Manifest 结构
```json
{
  "version": "2.0",
  "task_id": "sha256_hash",
  "src": { ... },
  "dst": { ... },
  "file_size": 123456,
  "file_mtime": 1234567890.0,
  "file_hash": "sha256...",
  "chunks": [
    {
      "index": 0,
      "offset": 0,
      "size": 4194304,
      "status": "completed",
      "sha256": "...",
      "attempts": 1
    }
  ],
  "config": { ... },
  "created_at": 1234567890.0,
  "updated_at": 1234567890.0
}
```

#### 关键函数
```python
class ManifestManager:
    def load(self, task_id: str) -> Optional[Manifest]:
        """加载 manifest"""
    
    def save(self, manifest: Manifest) -> None:
        """保存 manifest"""
    
    def validate(self, manifest: Manifest, task: TransferTask) -> bool:
        """验证 manifest 是否有效"""
    
    def cleanup(self, task_id: str) -> None:
        """清理 manifest"""
    
    def list_all(self) -> List[str]:
        """列出所有 manifest"""
```

### 3.4 分块策略 (chunking.py)

#### 分块规则
1. **小文件（< 4MB）**：单块传输
2. **中等文件（4MB - 100MB）**：4MB/块
3. **大文件（> 100MB）**：自适应大小
4. **Aria2 模式**：1MB/块，更多并发

#### 关键函数
```python
class ChunkStrategy:
    def calculate_chunks(self, file_size: int, config: TransferConfig) -> List[Chunk]:
        """计算分块"""
    
    def get_pending_chunks(self, chunks: List[Chunk]) -> List[Chunk]:
        """获取待传输的块"""
    
    def should_retry_chunk(self, chunk: Chunk, config: TransferConfig) -> bool:
        """判断是否应该重试"""
```

### 3.5 传输引擎 (engine.py)

#### 统一的传输引擎
```python
class TransferEngine:
    """基础传输引擎"""
    def transfer_chunk(self, chunk: Chunk, task: TransferTask) -> bytes:
        """传输单个块"""

class ParallelEngine(TransferEngine):
    """并发传输引擎"""
    def transfer_chunks(self, chunks: List[Chunk], task: TransferTask) -> None:
        """并发传输多个块"""

class Aria2Engine(ParallelEngine):
    """Aria2 模式引擎"""
    # 更激进的并发策略
```

#### 关键改进
1. **统一接口**：下载和上传使用相同接口
2. **智能调度**：根据网络状况动态调整并发数
3. **错误处理**：每个块独立重试，不影响其他块
4. **进度回调**：实时报告传输进度

### 3.6 校验器 (verifier.py)

#### 功能
- 计算文件 SHA256
- 计算块 SHA256
- 验证文件完整性
- 验证块完整性

```python
class Verifier:
    @staticmethod
    def compute_file_hash(file: Path) -> str:
        """计算文件 SHA256"""
    
    @staticmethod
    def compute_chunk_hash(data: bytes) -> str:
        """计算块 SHA256"""
    
    @staticmethod
    def verify_file(file: Path, expected_hash: str) -> bool:
        """验证文件"""
    
    @staticmethod
    def verify_chunk(data: bytes, chunk: Chunk) -> bool:
        """验证块"""
```

### 3.7 进度管理 (progress.py)

#### 功能
- 跟踪传输进度
- 计算传输速度
- 估算剩余时间
- 提供回调接口

```python
class ProgressTracker:
    def __init__(self, total_size: int):
        self.total_size = total_size
        self.transferred = 0
        self.start_time = time.time()
    
    def update(self, bytes_transferred: int) -> None:
        """更新进度"""
    
    def get_speed(self) -> float:
        """获取传输速度（bytes/s）"""
    
    def get_eta(self) -> float:
        """获取预计剩余时间（秒）"""
    
    def get_progress(self) -> tuple[int, int]:
        """获取进度（已传输，总大小）"""
```

### 3.8 服务层 (service.py)

#### 核心流程
```python
class TransferService:
    def transfer(self, src: str, dst: str, config: TransferConfig) -> TransferResult:
        # 1. 解析路径
        src_endpoint = parse_path(src)
        dst_endpoint = parse_path(dst)
        
        # 2. 建立连接
        connections = self._establish_connections(src_endpoint, dst_endpoint)
        
        # 3. 获取文件信息
        file_info = self._get_file_info(src_endpoint, connections)
        
        # 4. 创建任务
        task = TransferTask(
            id=generate_task_id(src_endpoint, dst_endpoint),
            src=src_endpoint,
            dst=dst_endpoint,
            config=config,
            **file_info
        )
        
        # 5. 加载或创建 manifest
        manifest = self._load_or_create_manifest(task)
        
        # 6. 计算分块
        chunks = self._calculate_chunks(task, manifest)
        
        # 7. 执行传输
        result = self._execute_transfer(task, chunks, connections)
        
        # 8. 验证完整性
        self._verify_transfer(task, result)
        
        # 9. 保存 manifest
        self._save_manifest(task, chunks)
        
        # 10. 清理资源
        self._cleanup(connections)
        
        return result
```

## 4. 错误处理策略

### 4.1 连接错误
- 自动重试（最多 3 次）
- 指数退避（1s, 2s, 4s）
- 清晰的错误消息

### 4.2 传输错误
- 块级别重试
- 失败块不影响其他块
- 保存失败信息到 manifest

### 4.3 校验错误
- 自动重新下载失败的块
- 提供跳过校验选项
- 记录校验失败日志

## 5. 性能优化

### 5.1 智能分块
- 根据文件大小自适应
- 避免过小或过大的块
- 考虑网络延迟和带宽

### 5.2 并发控制
- 默认 4 个并发连接
- Aria2 模式最多 16 个
- 根据错误率动态调整

### 5.3 内存优化
- 流式读写，不加载整个文件
- 块缓冲区大小限制
- 及时释放资源

## 6. 用户体验

### 6.1 进度显示
```
Transferring: file.bin → host:/path/file.bin
████████████████████████████░░░░  75% • 150 MB/200 MB • 5.2 MB/s • ETA: 10s
```

### 6.2 日志输出
- INFO：正常流程（resume, 完成）
- WARNING：可恢复错误（重试）
- ERROR：不可恢复错误
- DEBUG：详细调试信息（-v）

### 6.3 错误消息
- 清晰描述问题
- 提供解决建议
- 显示相关上下文

## 7. 测试策略

### 7.1 单元测试
- 路径解析
- 分块计算
- 校验功能
- Manifest 操作

### 7.2 集成测试
- 小文件传输
- 大文件传输
- 断点续传
- 并发传输
- 错误恢复

### 7.3 性能测试
- 不同文件大小
- 不同并发数
- 不同网络条件

## 8. 后续扩展

### 8.1 计划功能
- [ ] 目录传输（递归）
- [ ] 文件同步（双向）
- [ ] 增量传输（rsync 算法）
- [ ] 压缩传输（gzip）
- [ ] 加密传输（额外加密层）
- [ ] 多源传输（从多个源下载）
- [ ] P2P 传输（节点间直接传输）

### 8.2 优化方向
- [ ] 更智能的分块策略
- [ ] 网络状况自适应
- [ ] 传输优先级
- [ ] 带宽分配
- [ ] 缓存机制

## 9. 兼容性

### 9.1 向后兼容
- 支持 v1.0 manifest 格式
- 自动迁移旧格式
- 保留旧的 API

### 9.2 SCP 兼容
- 完全兼容 SCP 路径语法
- 支持常用 SCP 参数
- 行为一致性

## 10. 安全考虑

### 10.1 数据安全
- 使用 SSH 加密通道
- 支持密钥认证
- 临时文件权限控制

### 10.2 操作安全
- 避免覆盖重要文件（需确认）
- 原子操作（临时文件 + rename）
- 错误时自动清理

## 11. 实现计划

### Phase 1: 核心功能（当前阶段）
1. ✅ 数据模型重构
2. ✅ 路径解析优化
3. ⏳ Manifest 管理重写
4. ⏳ 分块策略优化
5. ⏳ 传输引擎统一
6. ⏳ 进度管理独立
7. ⏳ 服务层重构

### Phase 2: 功能完善
1. 校验器独立
2. 错误处理完善
3. 性能优化
4. 用户体验改进

### Phase 3: 扩展功能
1. 目录传输
2. 压缩传输
3. 增量传输
4. 高级功能

---

**设计版本**: v2.0  
**创建日期**: 2024-11-26  
**状态**: 设计中

