import hashlib
from typing import List
LEAF_PREFIX = b'\x00'
NODE_PREFIX = b'\x01'


def _hash(prefix: bytes, *data: bytes) -> bytes:
    """Create SHA-512 hash with prefix"""
    hasher = hashlib.sha512()
    hasher.update(prefix)
    for chunk in data:
        hasher.update(chunk)
    return hasher.digest()


def hash_leaf(data: bytes) -> bytes:
    """Hash a leaf node with leaf prefix"""
    return _hash(LEAF_PREFIX, data)


def hash_node(left: bytes, right: bytes) -> bytes:
    """Hash an internal node with node prefix"""
    return _hash(NODE_PREFIX, left, right)


def merkle_root(leaves: List[bytes]) -> bytes:
    """
    Calculate Merkle root of given leaves
    Returns empty bytes if no leaves provided
    """
    if not leaves:
        return b''
    current_level = [hash_leaf(leaf) for leaf in leaves]

    while len(current_level) > 1:
        next_level = []
        for i in range(0, len(current_level), 2):
            if i + 1 == len(current_level):
                next_level.append(current_level[i])
            else:
                next_level.append(hash_node(current_level[i], current_level[i + 1]))
        current_level = next_level

    return current_level[0] if current_level else b''


def merkle_proof(leaves: List[bytes], index: int) -> List[bytes]:
    """Generate Merkle proof for leaf at given index"""
    if not leaves or index >= len(leaves):
        return []

    proof = []
    current_level = [hash_leaf(leaf) for leaf in leaves]
    current_index = index

    while len(current_level) > 1:
        if current_index % 2 == 0:
            if current_index + 1 < len(current_level):
                proof.append(current_level[current_index + 1])
        else:
            proof.append(current_level[current_index - 1])

        next_level = []
        for i in range(0, len(current_level), 2):
            if i + 1 == len(current_level):
                next_level.append(current_level[i])
            else:
                next_level.append(hash_node(current_level[i], current_level[i + 1]))

        current_level = next_level
        current_index //= 2

    return proof


def verify_proof(leaf: bytes, proof: List[bytes], root: bytes, index: int) -> bool:
    """Verify Merkle proof for given leaf"""
    current_hash = hash_leaf(leaf)
    current_index = index

    for sibling in proof:
        if current_index % 2 == 0:
            current_hash = hash_node(current_hash, sibling)
        else:
            current_hash = hash_node(sibling, current_hash)
        current_index //= 2

    return current_hash == root