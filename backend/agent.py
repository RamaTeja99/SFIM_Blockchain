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

# FIXED: Proper import path resolution
current_dir = Path(__file__).parent.resolve()
backend_dir = current_dir / "backend" if (current_dir / "backend").exists() else current_dir
sys.path.insert(0, str(backend_dir))

# FIXED: Import with proper error handling
try:
    from merkle import merkle_root
    from models import db_manager, create_db_session, IntegrityEvent, AuditLog

    logger = logging.getLogger("BlockchainFileScanner")
    logger.info("✅ Imports successful")
except ImportError as e:
    print(f"❌ Import error: {e}")
    print(f"Current directory: {current_dir}")
    print(f"Backend directory: {backend_dir}")
    print(f"Files in backend: {list(backend_dir.glob('*.py'))}")
    raise e

# Configuration
WATCH_PATHS = [Path(p) for p in os.getenv('WATCH_PATHS', './watched').split(',')]
NODE_WS_URL = os.getenv('NODE_WS_URL', 'ws://localhost:7000/ws')
SCAN_INTERVAL = int(os.getenv('SCAN_INTERVAL', '30'))
DATABASE_URL = os.getenv('SFIM_DB', f'sqlite:///./data/agent_sfim.db')

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


class BlockchainFileMonitor:
    """Enhanced file monitor that integrates with blockchain workflow"""

    def __init__(self, watch_paths: List[Path]):
        self.watch_paths = watch_paths
        self.file_hashes: Dict[Path, bytes] = {}
        self.last_merkle_root = None

        # Ensure watch paths exist
        for path in self.watch_paths:
            path.mkdir(parents=True, exist_ok=True)
            logger.info(f"🔍 Monitoring blockchain path: {path}")

    async def scan_files(self) -> tuple[List[bytes], Dict[str, str]]:
        """Scan all files and return hashes and metadata for blockchain"""
        file_hashes = []
        file_metadata = {}

        for watch_path in self.watch_paths:
            if not watch_path.exists():
                continue

            # Recursively scan all files
            for file_path in watch_path.rglob('*'):
                if file_path.is_file():
                    try:
                        # Read file and compute SHA-512 hash (blockchain standard)
                        async with aiofiles.open(file_path, 'rb') as f:
                            content = await f.read()

                        file_hash = hashlib.sha512(content).digest()
                        file_hashes.append(file_hash)

                        # Store metadata for blockchain
                        stat = file_path.stat()
                        file_metadata[str(file_path)] = {
                            'hash': file_hash.hex(),
                            'size': stat.st_size,
                            'mtime': stat.st_mtime,
                            'relative_path': str(file_path.relative_to(watch_path))
                        }

                        # Check if file changed (blockchain event)
                        if file_path in self.file_hashes:
                            if self.file_hashes[file_path] != file_hash:
                                logger.info(f"🔄 Blockchain file changed: {file_path}")
                        else:
                            logger.info(f"📄 New blockchain file detected: {file_path}")

                        self.file_hashes[file_path] = file_hash

                    except Exception as e:
                        logger.error(f"❌ Error scanning file {file_path}: {e}")

        return file_hashes, file_metadata

    async def compute_blockchain_merkle_root(self) -> tuple[bytes, Dict[str, str]]:
        """Compute Merkle root for blockchain consensus"""
        file_hashes, file_metadata = await self.scan_files()

        if not file_hashes:
            logger.debug("⚠️ No files found in blockchain watch paths")
            return b'', {}

        # Compute Merkle root for blockchain
        try:
            root = merkle_root(file_hashes)

            # Check if Merkle root changed (new blockchain event)
            if self.last_merkle_root != root:
                logger.info(f"🌳 New Merkle root for blockchain: {root.hex()[:32]}... ({len(file_hashes)} files)")
                self.last_merkle_root = root
                return root, file_metadata
            else:
                logger.debug(f"✅ Merkle root unchanged: {root.hex()[:16]}...")
                return b'', {}  # No change
        except Exception as e:
            logger.error(f"❌ Error computing Merkle root: {e}")
            return b'', {}


class BlockchainFileAgent:
    """Main blockchain file scanning agent integrated with PBFT consensus"""

    def __init__(self):
        self.monitor = BlockchainFileMonitor(WATCH_PATHS)
        self.running = False

        # FIXED: Initialize database with proper error handling
        try:
            logger.info("🔄 Initializing agent database...")
            db_manager.init_database(DATABASE_URL)
            logger.info("✅ Agent database initialized successfully")
        except Exception as e:
            logger.error(f"❌ Agent database initialization failed: {e}")
            raise e

    async def log_blockchain_event(self, event_type: str, message: str, details: str = None):
        """Log blockchain event to database - FIXED with proper session handling"""
        db = None
        try:
            db = create_db_session()  # FIXED: Use new database manager
            log_entry = AuditLog(
                event_type=event_type,
                message=message,
                details=details,
                severity='info'
            )
            db.add(log_entry)
            db.commit()
            logger.debug("✅ Blockchain event logged successfully")
        except Exception as e:
            logger.error(f"❌ Error logging blockchain event: {e}")
            if db:
                db.rollback()
        finally:
            if db:
                db.close()

    async def connect_and_monitor_blockchain(self):
        """Connect to blockchain node and start monitoring"""
        retry_count = 0
        max_retries = 3

        while self.running and retry_count < max_retries:
            try:
                logger.info(f"🔄 Attempting to connect to blockchain node... (Attempt {retry_count + 1})")
                async with websockets.connect(NODE_WS_URL, ping_timeout=20, ping_interval=10) as websocket:
                    logger.info(f"🔗 Connected to blockchain node at {NODE_WS_URL}")
                    retry_count = 0  # Reset retry count on successful connection

                    while self.running:
                        try:
                            # Monitor files and send blockchain integrity events
                            root, metadata = await self.monitor.compute_blockchain_merkle_root()

                            if root:  # Only send if Merkle root changed
                                # Create blockchain integrity event
                                blockchain_message = {
                                    'type': 'integrity_event',
                                    'merkle_root': root.hex(),
                                    'file_count': len(metadata),
                                    'timestamp': int(time.time() * 1000),
                                    'metadata': metadata,
                                    'source': 'blockchain_file_scanner'
                                }

                                await websocket.send(json.dumps(blockchain_message))
                                logger.info(
                                    f"📡 Sent blockchain integrity event: {root.hex()[:16]}... ({len(metadata)} files)")

                                await self.log_blockchain_event(
                                    'blockchain_scan',
                                    f'Submitted Merkle root with {len(metadata)} files to blockchain',
                                    json.dumps({'root': root.hex(), 'file_count': len(metadata)})
                                )

                            await asyncio.sleep(SCAN_INTERVAL)

                        except websockets.exceptions.ConnectionClosed:
                            logger.warning("🔴 Blockchain node connection closed")
                            break
                        except Exception as e:
                            logger.error(f"❌ Error during monitoring: {e}")
                            await asyncio.sleep(5)

            except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError, OSError) as e:
                retry_count += 1
                logger.warning(f"🔴 Blockchain connection failed (attempt {retry_count}): {e}")

                if retry_count < max_retries:
                    wait_time = min(10 * retry_count, 60)  # Exponential backoff, max 60s
                    logger.info(f"⏳ Retrying blockchain connection in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"❌ Max retries ({max_retries}) exceeded. Stopping agent.")
                    self.running = False
            except Exception as e:
                logger.error(f"❌ Unexpected error: {e}")
                await asyncio.sleep(10)

    async def start(self):
        """Start the blockchain file monitoring agent"""
        logger.info("🚀 Starting Blockchain File Monitoring Agent")
        logger.info(f"📂 Watch paths: {[str(p) for p in self.monitor.watch_paths]}")
        logger.info(f"⏱️ Scan interval: {SCAN_INTERVAL} seconds")
        logger.info(f"🔗 Blockchain node: {NODE_WS_URL}")

        self.running = True
        await self.log_blockchain_event('system', 'Blockchain file monitoring agent started')

        try:
            await self.connect_and_monitor_blockchain()
        except KeyboardInterrupt:
            logger.info("⛔ Received interrupt signal")
        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}")
        finally:
            await self.stop()

    async def stop(self):
        """Stop the blockchain file monitoring agent"""
        logger.info("⛔ Stopping Blockchain File Monitoring Agent")
        self.running = False
        await self.log_blockchain_event('system', 'Blockchain file monitoring agent stopped')


async def main():
    """Main entry point for blockchain file scanner"""
    agent = BlockchainFileAgent()
    try:
        await agent.start()
    except KeyboardInterrupt:
        logger.info("⛔ Agent stopped by user")
    except Exception as e:
        logger.error(f"❌ Agent failed: {e}")
    finally:
        await agent.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⛔ Program terminated by user")
    except Exception as e:
        logger.error(f"❌ Program failed: {e}")
        sys.exit(1)