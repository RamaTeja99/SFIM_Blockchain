import asyncio
import json
import logging
import time
from typing import Dict, List, Optional, Set
from dataclasses import dataclass
from enum import Enum

try:
    from blspy import PrivateKey, PublicKey, AugSchemeMPL, G1Element, G2Element

    HAS_BLS = True
except ImportError:
    HAS_BLS = False
    logging.warning("blspy not available, using mock signatures")

import aiohttp
import websockets
from websockets.server import WebSocketServerProtocol


class Phase(Enum):
    PRE_PREPARE = "pre_prepare"
    PREPARE = "prepare"
    COMMIT = "commit"


@dataclass
class Message:
    phase: Phase
    digest: str
    node_id: int
    signature: str
    timestamp: int
    view: int = 0


class BLSManager:
    """Handles BLS signature operations"""

    def __init__(self, private_key_seed: bytes):
        if HAS_BLS:
            self.private_key = PrivateKey.from_seed(private_key_seed)
            self.public_key = self.private_key.get_g1()
        else:
            self.private_key = private_key_seed.hex()
            self.public_key = f"mock_pk_{private_key_seed.hex()[:16]}"

    def sign(self, message: bytes) -> str:
        """Sign message with private key"""
        if HAS_BLS:
            signature = AugSchemeMPL.sign(self.private_key, message)
            return bytes(signature).hex()
        else:
            import hashlib
            return hashlib.sha256(self.private_key.encode() + message).hexdigest()

    def verify(self, public_key: str, message: bytes, signature: str) -> bool:
        """Verify signature"""
        if HAS_BLS:
            try:
                pk = G1Element.from_bytes(bytes.fromhex(public_key))
                sig = G2Element.from_bytes(bytes.fromhex(signature))
                return AugSchemeMPL.verify(pk, message, sig)
            except Exception:
                return False
        else:
            import hashlib
            expected = hashlib.sha256(public_key.encode() + message).hexdigest()
            return signature == expected

    def aggregate(self, signatures: List[str]) -> str:
        """Aggregate multiple signatures"""
        if HAS_BLS:
            try:
                sigs = [G2Element.from_bytes(bytes.fromhex(sig)) for sig in signatures]
                agg_sig = AugSchemeMPL.aggregate(sigs)
                return bytes(agg_sig).hex()
            except Exception:
                return ""
        else:
            return "aggregated_" + "_".join(signatures[:3])


class PBFTNode:
    """PBFT Consensus Node Implementation - FIXED: Single node support"""

    def __init__(self, node_id: int, total_nodes: int, private_key_seed: bytes,
                 peers: List[str], port: int = 7000):
        self.node_id = node_id
        self.total_nodes = total_nodes
        self.peers = peers
        self.port = port
        self.bls = BLSManager(private_key_seed)

        self.view = 0
        self.sequence_number = 0
        self.current_digest = None

        self.prepare_messages: Dict[str, List[Message]] = {}
        self.commit_messages: Dict[str, List[Message]] = {}
        self.prepared_digests: Set[str] = set()
        self.committed_digests: Set[str] = set()

        self.connections: Dict[int, websockets.WebSocketServerProtocol] = {}
        self.server = None
        self.on_commit_callback = None

        self.logger = logging.getLogger(f"PBFTNode-{node_id}")

        # FIXED: Single node operation support
        self.single_node_mode = (total_nodes == 1 or len(peers) == 0)
        if self.single_node_mode:
            self.logger.info("🔧 Operating in single-node mode (consensus will be immediate)")

    @property
    def is_primary(self) -> bool:
        """Check if this node is the primary for current view"""
        return (self.view % self.total_nodes) == self.node_id

    @property
    def required_votes(self) -> int:
        """Number of votes required for consensus (2f + 1)"""
        if self.single_node_mode:
            return 1  # FIXED: Single node only needs itself
        return (2 * ((self.total_nodes - 1) // 3)) + 1

    async def start_server(self):
        """Start WebSocket server for peer connections"""
        if self.single_node_mode:
            self.logger.info("🔧 Skipping server start in single-node mode")
            return

        async def handle_connection(websocket: WebSocketServerProtocol):
            try:
                async for message in websocket:
                    await self.handle_message(json.loads(message))
            except websockets.exceptions.ConnectionClosed:
                pass
            except Exception as e:
                self.logger.error(f"Connection error: {e}")

        self.server = await websockets.serve(
            handle_connection, "0.0.0.0", self.port
        )
        self.logger.info(f"PBFT node {self.node_id} listening on port {self.port}")

    async def connect_to_peers(self):
        """Connect to peer nodes"""
        if self.single_node_mode:
            self.logger.info("🔧 Skipping peer connections in single-node mode")
            return

        for i, peer_url in enumerate(self.peers):
            if i != self.node_id:  # Don't connect to self
                try:
                    connection = await websockets.connect(peer_url)
                    self.connections[i] = connection
                    self.logger.info(f"Connected to peer {i} at {peer_url}")
                except Exception as e:
                    self.logger.error(f"Failed to connect to peer {i}: {e}")

    async def broadcast_message(self, message: Message):
        """Broadcast message to all connected peers"""
        if self.single_node_mode:
            # FIXED: In single node mode, simulate immediate consensus
            await self.handle_message({
                "phase": message.phase.value,
                "digest": message.digest,
                "node_id": message.node_id,
                "signature": message.signature,
                "timestamp": message.timestamp,
                "view": message.view,
                "public_key": self.bls.public_key
            })
            return

        message_json = json.dumps({
            "phase": message.phase.value,
            "digest": message.digest,
            "node_id": message.node_id,
            "signature": message.signature,
            "timestamp": message.timestamp,
            "view": message.view
        })

        for node_id, connection in self.connections.items():
            try:
                await connection.send(message_json)
            except Exception as e:
                self.logger.error(f"Failed to send to peer {node_id}: {e}")

    async def handle_message(self, data: dict):
        """Handle incoming consensus message"""
        try:
            message = Message(
                phase=Phase(data["phase"]),
                digest=data["digest"],
                node_id=data["node_id"],
                signature=data["signature"],
                timestamp=data["timestamp"],
                view=data.get("view", 0)
            )

            # FIXED: Skip signature verification in single node mode
            if not self.single_node_mode:
                message_bytes = f"{message.phase.value}:{message.digest}:{message.view}".encode()
                if not self.bls.verify(data.get("public_key", ""), message_bytes, message.signature):
                    self.logger.warning(f"Invalid signature from node {message.node_id}")
                    return

            if message.phase == Phase.PRE_PREPARE:
                await self.handle_pre_prepare(message)
            elif message.phase == Phase.PREPARE:
                await self.handle_prepare(message)
            elif message.phase == Phase.COMMIT:
                await self.handle_commit(message)

        except Exception as e:
            self.logger.error(f"Error handling message: {e}")

    async def handle_pre_prepare(self, message: Message):
        """Handle PRE-PREPARE message"""
        if not self.single_node_mode and not self.is_primary and message.node_id != (self.view % self.total_nodes):
            return

        self.current_digest = message.digest

        prepare_msg = Message(
            phase=Phase.PREPARE,
            digest=message.digest,
            node_id=self.node_id,
            signature=self.bls.sign(f"prepare:{message.digest}:{self.view}".encode()),
            timestamp=int(time.time() * 1000),
            view=self.view
        )

        await self.broadcast_message(prepare_msg)
        self.logger.info(f"Sent PREPARE for digest {message.digest[:16]}...")

    async def handle_prepare(self, message: Message):
        """Handle PREPARE message"""
        digest = message.digest

        if digest not in self.prepare_messages:
            self.prepare_messages[digest] = []

        self.prepare_messages[digest].append(message)

        if (len(self.prepare_messages[digest]) >= self.required_votes and
                digest not in self.prepared_digests):
            self.prepared_digests.add(digest)

            commit_msg = Message(
                phase=Phase.COMMIT,
                digest=digest,
                node_id=self.node_id,
                signature=self.bls.sign(f"commit:{digest}:{self.view}".encode()),
                timestamp=int(time.time() * 1000),
                view=self.view
            )

            await self.broadcast_message(commit_msg)
            self.logger.info(f"Sent COMMIT for digest {digest[:16]}...")

    async def handle_commit(self, message: Message):
        """Handle COMMIT message"""
        digest = message.digest

        if digest not in self.commit_messages:
            self.commit_messages[digest] = []

        self.commit_messages[digest].append(message)

        # Check if we have enough COMMIT messages
        if (len(self.commit_messages[digest]) >= self.required_votes and
                digest not in self.committed_digests):

            self.committed_digests.add(digest)
            self.logger.info(f"✅ CONSENSUS REACHED for digest {digest[:16]}...")

            # Execute the committed operation
            if self.on_commit_callback:
                await self.on_commit_callback(digest, self.commit_messages[digest])

    async def propose(self, digest: str):
        """Propose a new value (only primary can do this)"""
        if not self.single_node_mode and not self.is_primary:
            self.logger.warning("Only primary can propose values")
            return

        self.sequence_number += 1

        # FIXED: In single node mode, immediately proceed with consensus
        if self.single_node_mode:
            self.logger.info(f"🔧 Single-node immediate consensus for digest {digest[:16]}...")

            # Create a mock commit message for callback
            mock_commit_message = {
                'phase': 'commit',
                'digest': digest,
                'node_id': self.node_id,
                'signature': self.bls.sign(f"commit:{digest}:{self.view}".encode()),
                'timestamp': int(time.time() * 1000),
                'view': self.view
            }

            # Immediately commit in single node mode
            if digest not in self.committed_digests:
                self.committed_digests.add(digest)
                if self.on_commit_callback:
                    await self.on_commit_callback(digest, [mock_commit_message])
            return

        # Send PRE-PREPARE message
        pre_prepare_msg = Message(
            phase=Phase.PRE_PREPARE,
            digest=digest,
            node_id=self.node_id,
            signature=self.bls.sign(f"pre_prepare:{digest}:{self.view}".encode()),
            timestamp=int(time.time() * 1000),
            view=self.view
        )

        await self.broadcast_message(pre_prepare_msg)
        self.logger.info(f"Proposed digest {digest[:16]}...")

    def set_commit_callback(self, callback):
        """Set callback function for when consensus is reached"""
        self.on_commit_callback = callback

    async def start(self):
        """Start the PBFT node"""
        await self.start_server()
        await self.connect_to_peers()

        if self.single_node_mode:
            self.logger.info(f"✅ PBFT Node {self.node_id} started in single-node mode")
        else:
            self.logger.info(f"✅ PBFT Node {self.node_id} started in multi-node mode")

    async def stop(self):
        """Stop the PBFT node"""
        if self.server:
            self.server.close()
            await self.server.wait_closed()

        for connection in self.connections.values():
            await connection.close()

        self.logger.info(f"PBFT Node {self.node_id} stopped")