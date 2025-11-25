"""
Download engine implementations
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


class TransferEngine:
    """Base transfer engine (single connection)"""
    
    def __init__(self, client: RemoteClient, config: TransferConfig):
        """
        Initialize transfer engine.
        
        Args:
            client: RemoteClient instance
            config: Transfer configuration
        """
        self.client = client
        self.config = config
    
    def download_chunk(
        self,
        remote_path: str,
        chunk: Chunk,
        local_file: Path,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> bytes:
        """
        Download a single chunk.
        
        Args:
            remote_path: Remote file path
            chunk: Chunk to download
            local_file: Local file path (for writing)
            progress_callback: Optional progress callback
        
        Returns:
            Downloaded chunk data
        
        Raises:
            TransferError: If download fails
        """
        sftp = self.client.open_sftp()
        
        try:
            with sftp.open(remote_path, 'rb') as remote_file:
                # Seek to chunk offset
                remote_file.seek(chunk.offset)
                # Read chunk data
                data = remote_file.read(chunk.size)
                
                if len(data) != chunk.size:
                    raise TransferError(
                        f"Chunk {chunk.index}: expected {chunk.size} bytes, got {len(data)}"
                    )
                
                # Apply rate limiting if configured
                if self.config.limit_rate:
                    self._apply_rate_limit(len(data))
                
                if progress_callback:
                    progress_callback(len(data))
                
                return data
        except Exception as e:
            raise TransferError(f"Failed to download chunk {chunk.index}: {e}") from e
    
    def _apply_rate_limit(self, bytes_transferred: int) -> None:
        """Apply rate limiting"""
        if not self.config.limit_rate:
            return
        
        # Calculate sleep time based on rate limit
        sleep_time = bytes_transferred / self.config.limit_rate
        if sleep_time > 0:
            time.sleep(sleep_time)


class ParallelTransferEngine(TransferEngine):
    """Parallel transfer engine (multiple connections)"""
    
    def download_chunks(
        self,
        remote_path: str,
        chunks: List[Chunk],
        local_file: Path,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> List[bytes]:
        """
        Download multiple chunks in parallel.
        
        Args:
            remote_path: Remote file path
            chunks: List of chunks to download
            local_file: Local file path
            progress_callback: Optional progress callback
        
        Returns:
            List of chunk data (in order)
        """
        # Create multiple SFTP connections for parallel access
        # Note: Paramiko SFTPClient can share the same SSH connection
        # but we'll create separate clients for true parallelism
        
        results = {}
        failed_chunks = []
        
        def download_single_chunk(chunk: Chunk) -> tuple[int, bytes]:
            """Download single chunk"""
            try:
                data = self.download_chunk(
                    remote_path,
                    chunk,
                    local_file,
                    progress_callback,
                )
                return (chunk.index, data)
            except Exception as e:
                logger.error(f"Failed to download chunk {chunk.index}: {e}")
                failed_chunks.append(chunk.index)
                raise
        
        # Use thread pool for parallel downloads
        with ThreadPoolExecutor(max_workers=self.config.parallel) as executor:
            futures = {
                executor.submit(download_single_chunk, chunk): chunk
                for chunk in chunks
            }
            
            for future in as_completed(futures):
                try:
                    index, data = future.result()
                    results[index] = data
                except Exception:
                    pass  # Already logged
        
        # Return results in chunk order
        if failed_chunks:
            raise TransferError(f"Failed to download chunks: {failed_chunks}")
        
        return [results[i] for i in range(len(chunks))]


class Aria2TransferEngine(ParallelTransferEngine):
    """Aria2-style transfer engine (aggressive parallel with small chunks)"""
    
    def download_chunks(
        self,
        remote_path: str,
        chunks: List[Chunk],
        local_file: Path,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> List[bytes]:
        """
        Download chunks with aria2-style aggressive scheduling.
        
        Features:
        - More parallel connections
        - Dynamic reassignment of failed chunks
        - Fast retry on failure
        
        Args:
            remote_path: Remote file path
            chunks: List of chunks to download
            local_file: Local file path
            progress_callback: Optional progress callback
        
        Returns:
            List of chunk data (in order)
        """
        max_retries = 3
        max_workers = min(self.config.parallel * 2, len(chunks))
        
        pending_chunks = chunks.copy()
        results = {}
        failed_chunks = []
        
        def download_with_retry(chunk: Chunk, retry_count: int = 0) -> tuple[int, bytes]:
            """Download chunk with retry"""
            try:
                data = self.download_chunk(
                    remote_path,
                    chunk,
                    local_file,
                    progress_callback,
                )
                return (chunk.index, data)
            except Exception as e:
                if retry_count < max_retries:
                    logger.debug(f"Retrying chunk {chunk.index} (attempt {retry_count + 1})")
                    time.sleep(0.1 * (retry_count + 1))  # Exponential backoff
                    return download_with_retry(chunk, retry_count + 1)
                else:
                    logger.error(f"Failed to download chunk {chunk.index} after {max_retries} retries")
                    failed_chunks.append(chunk.index)
                    raise
        
        # Download with aggressive parallelism
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(download_with_retry, chunk): chunk
                for chunk in pending_chunks
            }
            
            for future in as_completed(futures):
                try:
                    index, data = future.result()
                    results[index] = data
                except Exception:
                    pass  # Already logged
        
        # Retry failed chunks
        if failed_chunks:
            retry_chunks = [c for c in chunks if c.index in failed_chunks]
            logger.info(f"Retrying {len(retry_chunks)} failed chunks")
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(download_with_retry, chunk): chunk
                    for chunk in retry_chunks
                }
                
                for future in as_completed(futures):
                    try:
                        index, data = future.result()
                        results[index] = data
                        failed_chunks.remove(index)
                    except Exception:
                        pass
        
        if failed_chunks:
            raise TransferError(f"Failed to download chunks after retries: {failed_chunks}")
        
        return [results[i] for i in range(len(chunks))]


def write_chunks_to_file(
    local_file: Path,
    chunks: List[Chunk],
    chunk_data: List[bytes],
) -> None:
    """
    Write downloaded chunks to local file.
    
    Args:
        local_file: Local file path
        chunks: List of chunks (for ordering)
        chunk_data: List of chunk data bytes
    """
    local_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Write to temporary file first
    temp_file = local_file.with_suffix(local_file.suffix + '.part')
    
    with open(temp_file, 'wb') as f:
        for chunk, data in zip(chunks, chunk_data):
            # Seek to chunk offset
            f.seek(chunk.offset)
            f.write(data)
    
    # Rename to final file
    temp_file.replace(local_file)

