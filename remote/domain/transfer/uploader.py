"""
Upload engine implementations
"""
import time
import threading
from pathlib import Path
from typing import List, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from ...core.client import RemoteClient
from ...core.exceptions import TransferError
from ...core.logging import get_logger
from .models import Chunk, ChunkStatus, TransferConfig
from .chunk import compute_chunk_hash

logger = get_logger(__name__)


class UploadEngine:
    """Base upload engine (single connection)"""
    
    def __init__(self, client: RemoteClient, config: TransferConfig):
        """
        Initialize upload engine.
        
        Args:
            client: RemoteClient instance
            config: Transfer configuration
        """
        self.client = client
        self.config = config
    
    def upload_chunk(
        self,
        local_file: Path,
        chunk: Chunk,
        remote_path: str,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> None:
        """
        Upload a single chunk.
        
        Args:
            local_file: Local file path
            chunk: Chunk to upload
            remote_path: Remote file path
            progress_callback: Optional progress callback
        
        Raises:
            TransferError: If upload fails
        """
        sftp = self.client.open_sftp()
        
        try:
            # Read chunk from local file
            with open(local_file, 'rb') as local_f:
                local_f.seek(chunk.offset)
                data = local_f.read(chunk.size)
                
                if len(data) != chunk.size:
                    raise TransferError(
                        f"Chunk {chunk.index}: expected {chunk.size} bytes, got {len(data)}"
                    )
            
            # Write chunk to remote file
            # File should already exist with correct size (ensured by service)
            with sftp.open(remote_path, 'r+b') as remote_file:
                remote_file.seek(chunk.offset)
                remote_file.write(data)
            
            # Apply rate limiting if configured
            if self.config.limit_rate:
                self._apply_rate_limit(len(data))
            
            if progress_callback:
                progress_callback(len(data))
                
        except Exception as e:
            raise TransferError(f"Failed to upload chunk {chunk.index}: {e}") from e
    
    def _apply_rate_limit(self, bytes_transferred: int) -> None:
        """Apply rate limiting"""
        if not self.config.limit_rate:
            return
        
        # Calculate sleep time based on rate limit
        sleep_time = bytes_transferred / self.config.limit_rate
        if sleep_time > 0:
            time.sleep(sleep_time)


class ParallelUploadEngine(UploadEngine):
    """Parallel upload engine (multiple connections)"""
    
    def upload_chunks(
        self,
        local_file: Path,
        chunks: List[Chunk],
        remote_path: str,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> None:
        """
        Upload multiple chunks in parallel.
        
        Args:
            local_file: Local file path
            chunks: List of chunks to upload
            remote_path: Remote file path
            progress_callback: Optional progress callback
        """
        failed_chunks = []
        
        def upload_single_chunk(chunk: Chunk) -> None:
            """Upload single chunk"""
            try:
                self.upload_chunk(
                    local_file,
                    chunk,
                    remote_path,
                    progress_callback,
                )
            except Exception as e:
                logger.error(f"Failed to upload chunk {chunk.index}: {e}")
                failed_chunks.append(chunk.index)
                raise
        
        # Use thread pool for parallel uploads
        with ThreadPoolExecutor(max_workers=self.config.parallel) as executor:
            futures = {
                executor.submit(upload_single_chunk, chunk): chunk
                for chunk in chunks
            }
            
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception:
                    pass  # Already logged
        
        if failed_chunks:
            raise TransferError(f"Failed to upload chunks: {failed_chunks}")


class Aria2UploadEngine(ParallelUploadEngine):
    """Aria2-style upload engine (aggressive parallel with small chunks)"""
    
    def upload_chunks(
        self,
        local_file: Path,
        chunks: List[Chunk],
        remote_path: str,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> None:
        """
        Upload chunks with aria2-style aggressive scheduling.
        
        Args:
            local_file: Local file path
            chunks: List of chunks to upload
            remote_path: Remote file path
            progress_callback: Optional progress callback
        """
        max_retries = 3
        max_workers = min(self.config.parallel * 2, len(chunks))
        
        failed_chunks = []
        
        def upload_with_retry(chunk: Chunk, retry_count: int = 0) -> None:
            """Upload chunk with retry"""
            try:
                self.upload_chunk(
                    local_file,
                    chunk,
                    remote_path,
                    progress_callback,
                )
            except Exception as e:
                if retry_count < max_retries:
                    logger.debug(f"Retrying chunk {chunk.index} (attempt {retry_count + 1})")
                    time.sleep(0.1 * (retry_count + 1))  # Exponential backoff
                    return upload_with_retry(chunk, retry_count + 1)
                else:
                    logger.error(f"Failed to upload chunk {chunk.index} after {max_retries} retries")
                    failed_chunks.append(chunk.index)
                    raise
        
        # Upload with aggressive parallelism
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(upload_with_retry, chunk): chunk
                for chunk in chunks
            }
            
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception:
                    pass  # Already logged
        
        # Retry failed chunks
        if failed_chunks:
            retry_chunks = [c for c in chunks if c.index in failed_chunks]
            logger.info(f"Retrying {len(retry_chunks)} failed chunks")
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(upload_with_retry, chunk): chunk
                    for chunk in retry_chunks
                }
                
                for future in as_completed(futures):
                    try:
                        future.result()
                        failed_chunks.remove(chunk.index)
                    except Exception:
                        pass
        
        if failed_chunks:
            raise TransferError(f"Failed to upload chunks after retries: {failed_chunks}")

