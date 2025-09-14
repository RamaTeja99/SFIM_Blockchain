import asyncio
import os
import sys
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import List, Dict

import aiofiles
import websockets

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from merkle import merkle_root
from models import init_database, SessionLocal, IntegrityEvent, AuditLog

# Configuration
WATCH_PATHS = [Path(p) for p in os.getenv('WATCH_PATHS', './watched').split(',')]
NODE_WS_URL = os.getenv('NODE_WS_URL', 'ws://localhost:7000/ws')
SCAN_INTERVAL = int(os.getenv('SCAN_INTERVAL', '10'))
DATABASE_URL = os.getenv('SFIM_DB', f'sqlite:///./data/agent_sfim.db')

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("FileAgent")


class FileMonitor:
    """Monitors files and computes Merkle roots"""

    def __init__(self, watch_paths: List[Path]):
        self.watch_paths = watch_paths
        self.file_hashes: Dict[Path, bytes] = {}

        # Ensure watch paths exist
        for path in self.watch_paths:
            path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Monitoring path: {path}")

    async def scan_files(self) -> tuple[List[bytes], Dict[str, str]]:
        """Scan all files and return hashes and metadata"""
        file_hashes = []
        file_metadata = {}

        for watch_path in self.watch_paths:
            if not watch_path.exists():
                continue

            # Recursively scan all files
            for file_path in watch_path.rglob('*'):
                if file_path.is_file():
                    try:
                        # Read file and compute hash
                        async with aiofiles.open(file_path, 'rb') as f:
                            content = await f.read()
                        file_hash = hashlib.sha512(content).digest()
                        file_hashes.append(file_hash)

                        # Store metadata
                        stat = file_path.stat()
                        file_metadata[str(file_path)] = {
                            'hash': file_hash.hex(),
                            'size': stat.st_size,
                            'mtime': stat.st_mtime,
                            'relative_path': str(file_path.relative_to(watch_path))
                        }

                        # Check if file changed
                        if file_path in self.file_hashes:
                            if self.file_hashes[file_path] != file_hash:
                                logger.info(f"File changed: {file_path}")
                        else:
                            logger.info(f"New file detected: {file_path}")

                        self.file_hashes[file_path] = file_hash

                    except Exception as e:
                        logger.error(f"Error reading file {file_path}: {e}")

        return file_hashes, file_metadata

    async def compute_merkle_root(self) -> tuple[bytes, Dict[str, str]]:
        """Compute Merkle root of all monitored files"""
        file_hashes, file_metadata = await self.scan_files()

        if not file_hashes:
            logger.warning("No files found in watch paths")
            return b'', {}

        root = merkle_root(file_hashes)
        logger.info(f"Computed Merkle root: {root.hex()[:32]}... ({len(file_hashes)} files)")

        return root, file_metadata


class FileAgent:
    """Main file monitoring agent"""

    def __init__(self):
        self.monitor = FileMonitor(WATCH_PATHS)
        self.running = False

        # Initialize database
        init_database(DATABASE_URL)

    async def log_event(self, event_type: str, message: str, details: str = None):
        """Log event to database"""
        try:
            db = SessionLocal()
            log_entry = AuditLog(
                event_type=event_type,
                message=message,
                details=details,
                severity='info'
            )
            db.add(log_entry)
            db.commit()
            db.close()
        except Exception as e:
            logger.error(f"Error logging to database: {e}")

    async def connect_and_monitor(self):
        """Connect to node and start monitoring"""
        while self.running:
            try:
                async with websockets.connect(NODE_WS_URL) as websocket:
                    logger.info(f"Connected to node at {NODE_WS_URL}")

                    while self.running:
                        # Monitor files and send integrity events
                        root, metadata = await self.monitor.compute_merkle_root()

                        if root:
                            message = {
                                'type': 'integrity_event',
                                'merkle_root': root.hex(),
                                'file_count': len(metadata),
                                'timestamp': int(time.time() * 1000),
                                'metadata': metadata
                            }

                            await websocket.send(json.dumps(message))
                            logger.info(f"Sent integrity event: {root.hex()[:16]}...")

                            await self.log_event(
                                'file_scan',
                                f'Submitted Merkle root with {len(metadata)} files',
                                json.dumps({'root': root.hex(), 'file_count': len(metadata)})
                            )

                        await asyncio.sleep(SCAN_INTERVAL)

            except Exception as e:
                logger.error(f"Connection failed: {e}")
                await asyncio.sleep(5)  # Retry after 5 seconds

    async def start(self):
        """Start the file monitoring agent"""
        logger.info("Starting File Monitoring Agent")
        logger.info(f"Watch paths: {[str(p) for p in self.monitor.watch_paths]}")
        logger.info(f"Scan interval: {SCAN_INTERVAL} seconds")
        logger.info(f"Node WebSocket: {NODE_WS_URL}")

        self.running = True
        await self.log_event('system', 'File monitoring agent started')

        try:
            await self.connect_and_monitor()
        except KeyboardInterrupt:
            logger.info("Received interrupt signal")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
        finally:
            await self.stop()

    async def stop(self):
        """Stop the file monitoring agent"""
        logger.info("Stopping File Monitoring Agent")
        self.running = False
        await self.log_event('system', 'File monitoring agent stopped')


async def main():
    """Main entry point"""
    agent = FileAgent()
    try:
        await agent.start()
    except KeyboardInterrupt:
        logger.info("Agent stopped by user")
    except Exception as e:
        logger.error(f"Agent failed: {e}")
    finally:
        await agent.stop()


if __name__ == "__main__":
    asyncio.run(main())
