import asyncio
import os
import sys
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import List, Dict, Set
import aiofiles
import websockets

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.merkle import merkle_root
from backend.models import init_database, SessionLocal, IntegrityEvent, AuditLog

# Configuration
WATCH_PATHS = os.getenv('WATCH_PATHS', '/watched').split(',')
NODE_WS_URL = os.getenv('NODE_WS', 'ws://localhost:7000/ws')
SCAN_INTERVAL = int(os.getenv('SCAN_INTERVAL', '10'))  # seconds
DATABASE_URL = os.getenv('SFIM_DB', 'sqlite:///sfim_audit.db')

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("FileAgent")


class FileMonitor:
    """Monitors files and computes Merkle roots"""

    def __init__(self, watch_paths: List[str]):
        self.watch_paths = [Path(p) for p in watch_paths]
        self.last_scan_times: Dict[Path, float] = {}
        self.file_hashes: Dict[Path, bytes] = {}

        # Ensure watch paths exist
        for path in self.watch_paths:
            path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Monitoring path: {path}")

    async def scan_files(self) -> tuple[List[bytes], Dict[str, str]]:
        """
        Scan all files in watch paths and return file hashes and metadata
        Returns: (file_hashes, file_metadata)
        """
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


class PBFTClient:
    """Client for communicating with PBFT network"""

    def __init__(self, node_ws_url: str):
        self.node_ws_url = node_ws_url
        self.websocket = None
        self.connected = False

    async def connect(self):
        """Connect to PBFT node"""
        try:
            self.websocket = await websockets.connect(self.node_ws_url)
            self.connected = True
            logger.info(f"Connected to PBFT node: {self.node_ws_url}")
        except Exception as e:
            logger.error(f"Failed to connect to PBFT node: {e}")
            self.connected = False

    async def submit_merkle_root(self, merkle_root_bytes: bytes, metadata: Dict[str, str]):
        """Submit Merkle root to PBFT network"""
        if not self.connected or not self.websocket:
            await self.connect()

        if not self.connected:
            logger.error("Not connected to PBFT network")
            return False

        try:
            message = {
                'type': 'integrity_event',
                'merkle_root': merkle_root_bytes.hex(),
                'file_count': len(metadata),
                'timestamp': int(time.time() * 1000),
                'metadata': metadata
            }

            await self.websocket.send(json.dumps(message))
            logger.info(f"Submitted Merkle root: {merkle_root_bytes.hex()[:32]}...")
            return True

        except Exception as e:
            logger.error(f"Error submitting Merkle root: {e}")
            self.connected = False
            return False

    async def close(self):
        """Close connection"""
        if self.websocket:
            await self.websocket.close()
            self.connected = False


class FileAgent:
    """Main file monitoring agent"""

    def __init__(self):
        self.monitor = FileMonitor(WATCH_PATHS)
        self.pbft_client = PBFTClient(NODE_WS_URL)
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

    async def run_scan_cycle(self):
        """Run one complete scan cycle"""
        try:
            # Compute current Merkle root
            root, metadata = await self.monitor.compute_merkle_root()

            if root:
                # Submit to PBFT network
                success = await self.pbft_client.submit_merkle_root(root, metadata)

                if success:
                    await self.log_event(
                        'file_scan',
                        f'Submitted Merkle root with {len(metadata)} files',
                        json.dumps({'root': root.hex(), 'file_count': len(metadata)})
                    )
                else:
                    await self.log_event(
                        'error',
                        'Failed to submit Merkle root to PBFT network',
                        json.dumps({'root': root.hex()})
                    )
            else:
                logger.info("No files to monitor")

        except Exception as e:
            logger.error(f"Error in scan cycle: {e}")
            await self.log_event('error', f'Scan cycle error: {str(e)}')

    async def start(self):
        """Start the file monitoring agent"""
        logger.info("Starting File Monitoring Agent")
        logger.info(f"Watch paths: {[str(p) for p in self.monitor.watch_paths]}")
        logger.info(f"Scan interval: {SCAN_INTERVAL} seconds")
        logger.info(f"PBFT node: {NODE_WS_URL}")

        self.running = True
        await self.log_event('system', 'File monitoring agent started')

        # Connect to PBFT network
        await self.pbft_client.connect()

        # Main monitoring loop
        while self.running:
            try:
                await self.run_scan_cycle()
                await asyncio.sleep(SCAN_INTERVAL)
            except KeyboardInterrupt:
                logger.info("Received interrupt signal")
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                await asyncio.sleep(5)  # Brief pause before retrying

        await self.stop()

    async def stop(self):
        """Stop the file monitoring agent"""
        logger.info("Stopping File Monitoring Agent")
        self.running = False
        await self.pbft_client.close()
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