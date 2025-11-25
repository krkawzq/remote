"""
Transfer service - main business logic
"""
from pathlib import Path
from typing import Optional, Callable

from ...core.client import RemoteClient
from ...core.exceptions import TransferError, ConnectionError
from ...core.logging import get_logger
from ...core.interfaces import ConnectionFactory
from ...infrastructure.state.transfer_store import TransferManifestStore
from .models import TransferConfig, Endpoint, Manifest, Chunk, ChunkStatus
from .parser import parse_scp_path, resolve_remote_path, generate_manifest_key
from .manifest import (
    get_local_file_info,
    get_remote_file_info,
    validate_manifest,
    create_manifest,
)
from .chunk import ChunkScheduler, compute_chunk_hash, compute_file_hash
from .downloader import (
    TransferEngine,
    ParallelTransferEngine,
    Aria2TransferEngine,
    write_chunks_to_file,
)
from .uploader import (
    UploadEngine,
    ParallelUploadEngine,
    Aria2UploadEngine,
)

logger = get_logger(__name__)


class TransferService:
    """
    Transfer service - pure business logic.
    
    Handles file transfer with resume support, parallel downloads, and aria2 mode.
    """
    
    def __init__(
        self,
        connection_factory: ConnectionFactory,
        manifest_store: Optional[TransferManifestStore] = None,
    ):
        """
        Initialize transfer service.
        
        Args:
            connection_factory: SSH connection factory
            manifest_store: Manifest storage (optional, creates default if None)
        """
        self.connection_factory = connection_factory
        self.manifest_store = manifest_store or TransferManifestStore()
        self._src_client: Optional[RemoteClient] = None
        self._dst_client: Optional[RemoteClient] = None
    
    def transfer(
        self,
        src_path: str,
        dst_path: str,
        config: TransferConfig,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> tuple[int, int]:
        """
        Transfer file from source to destination.
        
        Args:
            src_path: Source path (local or remote)
            dst_path: Destination path (local or remote)
            config: Transfer configuration
            progress_callback: Optional progress callback (transferred_bytes, total_bytes)
        
        Returns:
            (transferred_bytes, total_bytes) tuple
        
        Raises:
            TransferError: If transfer fails
        """
        try:
            # Parse endpoints
            src_endpoint = parse_scp_path(src_path, config.ssh_port)
            dst_endpoint = parse_scp_path(dst_path, config.ssh_port)
            
            # Establish connections
            self._establish_connections(src_endpoint, dst_endpoint, config)
            
            # Resolve remote paths
            if not src_endpoint.is_local and self._src_client:
                src_endpoint.path = resolve_remote_path(self._src_client, src_endpoint)
            if not dst_endpoint.is_local and self._dst_client:
                dst_endpoint.path = resolve_remote_path(self._dst_client, dst_endpoint)
            
            # Get file info
            if src_endpoint.is_local:
                file_size, file_mtime = get_local_file_info(Path(src_endpoint.path))
                if file_size == 0:
                    raise TransferError(f"Source file is empty: {src_endpoint.path}")
            else:
                file_size, file_mtime = get_remote_file_info(self._src_client, src_endpoint.path)
            
            # Determine transfer direction
            is_download = src_endpoint.is_local == False and dst_endpoint.is_local == True
            is_upload = src_endpoint.is_local == True and dst_endpoint.is_local == False
            
            if not (is_download or is_upload):
                raise TransferError("Only local<->remote transfers are supported")
            
            # Load or create manifest
            manifest_key = generate_manifest_key(src_endpoint, dst_endpoint)
            manifest = self._load_or_create_manifest(
                manifest_key,
                src_endpoint,
                dst_endpoint,
                file_size,
                file_mtime,
                config,
            )
            
            # Create chunk scheduler
            scheduler = ChunkScheduler(config)
            
            # Create or reuse chunks
            if not manifest.chunks or len(manifest.chunks) == 0:
                chunks = scheduler.create_chunks(file_size)
            else:
                chunks = manifest.chunks
                # Validate chunks match file size
                total_chunk_size = sum(c.size for c in chunks)
                if total_chunk_size != file_size:
                    logger.warning("Chunk size mismatch, recreating chunks")
                    chunks = scheduler.create_chunks(file_size)
            
            # Calculate initial progress
            total_bytes = sum(c.size for c in chunks)
            completed_chunks = [c for c in chunks if c.status in (ChunkStatus.DOWNLOADED, ChunkStatus.VERIFIED)]
            initial_transferred = sum(c.size for c in completed_chunks)
            
            # Report initial progress
            if progress_callback and initial_transferred > 0:
                progress_callback(initial_transferred, total_bytes)
            
            # Get pending chunks
            if config.force:
                # Force mode: reset all chunks
                for chunk in chunks:
                    chunk.status = ChunkStatus.PENDING
                pending_chunks = chunks
            else:
                # Resume mode: only transfer pending chunks
                pending_chunks = scheduler.get_pending_chunks(chunks)
                if not pending_chunks:
                    logger.info("All chunks already downloaded")
                    # Verify file integrity
                    self._verify_file_integrity(
                        src_endpoint,
                        dst_endpoint,
                        chunks,
                        is_download,
                    )
                    # Update manifest
                    manifest.chunks = chunks
                    self.manifest_store.save(manifest_key, manifest.to_dict())
                    if progress_callback:
                        progress_callback(total_bytes, total_bytes)
                    return (total_bytes, total_bytes)
            
            # Perform transfer
            if is_download:
                self._download_file(
                    src_endpoint,
                    dst_endpoint,
                    chunks,
                    pending_chunks,
                    config,
                    progress_callback,
                    initial_transferred,
                    total_bytes,
                )
            else:
                self._upload_file(
                    src_endpoint,
                    dst_endpoint,
                    chunks,
                    pending_chunks,
                    config,
                    progress_callback,
                    initial_transferred,
                    total_bytes,
                )
            
            # Verify and save manifest
            self._verify_file_integrity(
                src_endpoint,
                dst_endpoint,
                chunks,
                is_download,
            )
            
            # Update manifest with completed chunks
            manifest.chunks = chunks
            self.manifest_store.save(manifest_key, manifest.to_dict())
            
            logger.info("Transfer completed successfully")
            
            final_transferred = sum(c.size for c in chunks if c.status in (ChunkStatus.DOWNLOADED, ChunkStatus.VERIFIED))
            return (final_transferred, total_bytes)
            
        finally:
            self._cleanup_connections()
    
    def _establish_connections(
        self,
        src_endpoint: Endpoint,
        dst_endpoint: Endpoint,
        config: TransferConfig,
    ) -> None:
        """Establish SSH connections if needed"""
        # Source connection
        if not src_endpoint.is_local:
            src_params = {
                "host": src_endpoint.host,
                "user": src_endpoint.user or "root",
                "port": src_endpoint.port,
            }
            if src_endpoint.key_file:
                src_params["key"] = src_endpoint.key_file
            try:
                self._src_client = self.connection_factory.create(src_params)
            except Exception as e:
                raise ConnectionError(f"Failed to connect to source: {e}") from e
        
        # Destination connection
        if not dst_endpoint.is_local:
            dst_params = {
                "host": dst_endpoint.host,
                "user": dst_endpoint.user or "root",
                "port": dst_endpoint.port,
            }
            if dst_endpoint.key_file:
                dst_params["key"] = dst_endpoint.key_file
            try:
                self._dst_client = self.connection_factory.create(dst_params)
            except Exception as e:
                raise ConnectionError(f"Failed to connect to destination: {e}") from e
    
    def _load_or_create_manifest(
        self,
        manifest_key: str,
        src_endpoint: Endpoint,
        dst_endpoint: Endpoint,
        file_size: int,
        file_mtime: float,
        config: TransferConfig,
    ) -> Manifest:
        """Load existing manifest or create new one"""
        if config.force:
            # Force mode: don't load manifest
            return create_manifest(
                src_endpoint,
                dst_endpoint,
                file_size,
                file_mtime,
                config,
            )
        
        # Try to load existing manifest
        manifest_data = self.manifest_store.load(manifest_key)
        if manifest_data:
            manifest = Manifest.from_dict(manifest_data)
            
            # Validate manifest
            if validate_manifest(
                manifest,
                src_endpoint,
                dst_endpoint,
                self._src_client,
                self._dst_client,
            ):
                logger.info("Resuming transfer from manifest")
                return manifest
            else:
                logger.warning("Manifest validation failed, starting fresh")
        
        # Create new manifest
        return create_manifest(
            src_endpoint,
            dst_endpoint,
            file_size,
            file_mtime,
            config,
        )
    
    def _download_file(
        self,
        src_endpoint: Endpoint,
        dst_endpoint: Endpoint,
        chunks: list[Chunk],
        pending_chunks: list[Chunk],
        config: TransferConfig,
        progress_callback: Optional[Callable[[int, int], None]],
        initial_transferred: int,
        total_bytes: int,
    ) -> None:
        """Download file from remote to local"""
        if not pending_chunks:
            return
        
        # Select engine based on config
        if config.aria2:
            engine = Aria2TransferEngine(self._src_client, config)
        elif config.parallel > 1:
            engine = ParallelTransferEngine(self._src_client, config)
        else:
            engine = TransferEngine(self._src_client, config)
        
        local_file = Path(dst_endpoint.path)
        
        # Create wrapper progress callback
        transferred = initial_transferred
        
        def wrapped_callback(bytes_transferred: int) -> None:
            nonlocal transferred
            transferred += bytes_transferred
            if progress_callback:
                progress_callback(transferred, total_bytes)
        
        # Download chunks
        if isinstance(engine, TransferEngine) and len(pending_chunks) == 1:
            # Single chunk: use simple download
            chunk_data = engine.download_chunk(
                src_endpoint.path,
                pending_chunks[0],
                local_file,
                wrapped_callback,
            )
            write_chunks_to_file(local_file, pending_chunks, [chunk_data])
        else:
            # Multiple chunks: use parallel download
            if isinstance(engine, (ParallelTransferEngine, Aria2TransferEngine)):
                chunk_data_list = engine.download_chunks(
                    src_endpoint.path,
                    pending_chunks,
                    local_file,
                    wrapped_callback,
                )
            else:
                # Fallback: download sequentially
                chunk_data_list = []
                for chunk in pending_chunks:
                    data = engine.download_chunk(
                        src_endpoint.path,
                        chunk,
                        local_file,
                        wrapped_callback,
                    )
                    chunk_data_list.append(data)
            
            write_chunks_to_file(local_file, pending_chunks, chunk_data_list)
        
        # Mark chunks as downloaded
        for chunk in pending_chunks:
            chunk.status = ChunkStatus.DOWNLOADED
    
    def _upload_file(
        self,
        src_endpoint: Endpoint,
        dst_endpoint: Endpoint,
        chunks: list[Chunk],
        pending_chunks: list[Chunk],
        config: TransferConfig,
        progress_callback: Optional[Callable[[int, int], None]],
        initial_transferred: int,
        total_bytes: int,
    ) -> None:
        """Upload file from local to remote"""
        if not pending_chunks:
            return
        
        # Ensure remote directory exists
        from ...domain.sync.file_sync import ensure_remote_dir
        ensure_remote_dir(self._dst_client, dst_endpoint.path)
        
        # Ensure remote file exists with correct size
        self._ensure_remote_file_size(dst_endpoint.path, total_bytes)
        
        # Select engine based on config
        if config.aria2:
            engine = Aria2UploadEngine(self._dst_client, config)
        elif config.parallel > 1:
            engine = ParallelUploadEngine(self._dst_client, config)
        else:
            engine = UploadEngine(self._dst_client, config)
        
        local_file = Path(src_endpoint.path)
        
        # Create wrapper progress callback
        transferred = initial_transferred
        
        def wrapped_callback(bytes_transferred: int) -> None:
            nonlocal transferred
            transferred += bytes_transferred
            if progress_callback:
                progress_callback(transferred, total_bytes)
        
        # Upload chunks
        if isinstance(engine, UploadEngine) and len(pending_chunks) == 1:
            # Single chunk: use simple upload
            engine.upload_chunk(
                local_file,
                pending_chunks[0],
                dst_endpoint.path,
                wrapped_callback,
            )
        else:
            # Multiple chunks: use parallel upload
            if isinstance(engine, (ParallelUploadEngine, Aria2UploadEngine)):
                engine.upload_chunks(
                    local_file,
                    pending_chunks,
                    dst_endpoint.path,
                    wrapped_callback,
                )
            else:
                # Fallback: upload sequentially
                for chunk in pending_chunks:
                    engine.upload_chunk(
                        local_file,
                        chunk,
                        dst_endpoint.path,
                        wrapped_callback,
                    )
        
        # Mark chunks as downloaded
        for chunk in pending_chunks:
            chunk.status = ChunkStatus.DOWNLOADED
    
    def _ensure_remote_file_size(self, remote_path: str, file_size: int) -> None:
        """Ensure remote file exists with correct size"""
        sftp = self._dst_client.open_sftp()
        try:
            stat = sftp.stat(remote_path)
            if stat.st_size != file_size:
                # File exists but wrong size, truncate it
                with sftp.open(remote_path, 'wb') as f:
                    f.truncate(file_size)
        except IOError:
            # File doesn't exist, create it with correct size
            with sftp.open(remote_path, 'wb') as f:
                f.truncate(file_size)
    
    def _verify_file_integrity(
        self,
        src_endpoint: Endpoint,
        dst_endpoint: Endpoint,
        chunks: list[Chunk],
        is_download: bool,
    ) -> None:
        """Verify file integrity"""
        if is_download:
            # Verify downloaded file
            local_file = Path(dst_endpoint.path)
            if not local_file.exists():
                raise TransferError(f"Downloaded file not found: {local_file}")
            
            # Check file size
            actual_size = local_file.stat().st_size
            expected_size = sum(c.size for c in chunks)
            if actual_size != expected_size:
                raise TransferError(
                    f"File size mismatch: expected {expected_size}, got {actual_size}"
                )
            
            # Compute file hash
            file_hash = compute_file_hash(local_file, use_sha256=True)
            logger.debug(f"File hash: {file_hash}")
            
            # Mark all chunks as verified
            for chunk in chunks:
                if chunk.status == ChunkStatus.DOWNLOADED:
                    chunk.status = ChunkStatus.VERIFIED
        else:
            # For upload, check remote file size
            try:
                sftp = self._dst_client.open_sftp()
                stat = sftp.stat(dst_endpoint.path)
                expected_size = sum(c.size for c in chunks)
                if stat.st_size != expected_size:
                    raise TransferError(
                        f"Remote file size mismatch: expected {expected_size}, got {stat.st_size}"
                    )
            except Exception as e:
                raise TransferError(f"Failed to verify remote file: {e}") from e
            
            # Mark all chunks as verified
            for chunk in chunks:
                if chunk.status == ChunkStatus.DOWNLOADED:
                    chunk.status = ChunkStatus.VERIFIED
    
    def _cleanup_connections(self) -> None:
        """Clean up SSH connections"""
        if self._src_client:
            try:
                self._src_client.close()
            except Exception:
                pass
            self._src_client = None
        
        if self._dst_client:
            try:
                self._dst_client.close()
            except Exception:
                pass
            self._dst_client = None
