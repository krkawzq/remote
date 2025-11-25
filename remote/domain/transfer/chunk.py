"""
Chunk scheduling and management
"""
import hashlib
from typing import List, Optional
from pathlib import Path

from .models import Chunk, ChunkStatus, TransferConfig


class ChunkScheduler:
    """Chunk scheduler for transfer operations"""
    
    def __init__(self, config: TransferConfig):
        """
        Initialize chunk scheduler.
        
        Args:
            config: Transfer configuration
        """
        self.config = config
    
    def create_chunks(self, file_size: int) -> List[Chunk]:
        """
        Create chunk list for a file.
        
        Args:
            file_size: Total file size in bytes
        
        Returns:
            List of Chunk objects
        """
        if file_size == 0:
            return []
        
        # Determine chunk size and count
        if self.config.aria2:
            # Aria2 mode: use smaller chunks, more of them
            chunk_size = max(1024 * 1024, self.config.chunk // 4)  # At least 1MB, or 1/4 of configured size
            num_chunks = min(self.config.split, (file_size + chunk_size - 1) // chunk_size)
            # Adjust chunk_size to distribute evenly
            chunk_size = (file_size + num_chunks - 1) // num_chunks
        else:
            # Normal mode: use configured chunk size
            chunk_size = self.config.chunk
            num_chunks = (file_size + chunk_size - 1) // chunk_size
        
        # Optimize for small files
        if file_size < chunk_size * 2:
            # Small file: use single chunk
            num_chunks = 1
            chunk_size = file_size
        
        chunks = []
        offset = 0
        
        for i in range(num_chunks):
            # Last chunk may be smaller
            size = min(chunk_size, file_size - offset)
            if size <= 0:
                break
            
            chunk = Chunk(
                index=i,
                offset=offset,
                size=size,
                status=ChunkStatus.PENDING,
            )
            chunks.append(chunk)
            offset += size
        
        return chunks
    
    def get_pending_chunks(self, chunks: List[Chunk]) -> List[Chunk]:
        """
        Get list of pending chunks.
        
        Args:
            chunks: List of all chunks
        
        Returns:
            List of pending chunks
        """
        return [c for c in chunks if c.status == ChunkStatus.PENDING]
    
    def get_failed_chunks(self, chunks: List[Chunk]) -> List[Chunk]:
        """
        Get list of failed chunks.
        
        Args:
            chunks: List of all chunks
        
        Returns:
            List of failed chunks
        """
        return [c for c in chunks if c.status == ChunkStatus.FAILED]
    
    def optimize_chunk_count(self, file_size: int, chunks: List[Chunk]) -> List[Chunk]:
        """
        Optimize chunk count for small files.
        
        For small files, reduce chunk count to avoid overhead.
        
        Args:
            file_size: Total file size
            chunks: Existing chunks
        
        Returns:
            Optimized chunk list
        """
        # If file is small enough, use single chunk
        if file_size < self.config.chunk * 2 and len(chunks) > 1:
            return [Chunk(
                index=0,
                offset=0,
                size=file_size,
                status=ChunkStatus.PENDING,
            )]
        
        return chunks


def compute_chunk_hash(data: bytes, use_sha256: bool = False) -> str:
    """
    Compute hash for chunk data.
    
    Args:
        data: Chunk data bytes
        use_sha256: If True, use SHA256; otherwise use SHA1
    
    Returns:
        Hash hex string
    """
    if use_sha256:
        return hashlib.sha256(data).hexdigest()
    return hashlib.sha1(data).hexdigest()


def compute_file_hash(file_path: Path, use_sha256: bool = True) -> str:
    """
    Compute hash for entire file.
    
    Args:
        file_path: File path
        use_sha256: If True, use SHA256; otherwise use SHA1
    
    Returns:
        Hash hex string
    """
    hash_func = hashlib.sha256 if use_sha256 else hashlib.sha1
    
    with open(file_path, 'rb') as f:
        hasher = hash_func()
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            hasher.update(chunk)
    
    return hasher.hexdigest()

