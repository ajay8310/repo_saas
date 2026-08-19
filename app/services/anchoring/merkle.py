"""
Merkle tree over credential digests.

Anchoring one hash per credential on a ledger costs a transaction per issuance.
Batching them under a single Merkle root means one transaction per batch while
still letting any individual credential prove membership, which is what makes
on-chain anchoring affordable at scale.

Second-preimage resistance: leaves and internal nodes are hashed with different
domain prefixes (0x00 / 0x01), so an internal node cannot be replayed as a leaf.
This is the RFC 6962 construction.

Odd nodes are promoted unchanged rather than duplicated. Duplicating the last
node (the Bitcoin approach) admits distinct leaf sets with identical roots.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

_LEAF_PREFIX = b"\x00"
_NODE_PREFIX = b"\x01"


def leaf_hash(payload: bytes) -> bytes:
    """Hash a leaf with domain separation."""
    return hashlib.sha256(_LEAF_PREFIX + payload).digest()


def node_hash(left: bytes, right: bytes) -> bytes:
    """Hash two child nodes with domain separation."""
    return hashlib.sha256(_NODE_PREFIX + left + right).digest()


@dataclass(frozen=True, slots=True)
class InclusionProof:
    """Path from a leaf to the root.

    ``siblings`` is ordered leaf-to-root; each entry carries the sibling hash
    and which side it sits on.
    """

    leaf_index: int
    leaf_count: int
    siblings: tuple[tuple[str, str], ...]  # (position, hex digest), position in {L,R}

    def to_json(self) -> dict:
        return {
            "leaf_index": self.leaf_index,
            "leaf_count": self.leaf_count,
            "siblings": [{"position": p, "hash": h} for p, h in self.siblings],
        }

    @classmethod
    def from_json(cls, data: dict) -> InclusionProof:
        return cls(
            leaf_index=int(data["leaf_index"]),
            leaf_count=int(data["leaf_count"]),
            siblings=tuple(
                (str(s["position"]), str(s["hash"])) for s in data.get("siblings", [])
            ),
        )


class MerkleTree:
    """An immutable Merkle tree built from ordered leaf payloads."""

    def __init__(self, leaves: list[bytes]) -> None:
        if not leaves:
            raise ValueError("A Merkle tree needs at least one leaf")
        self._leaf_hashes = [leaf_hash(leaf) for leaf in leaves]
        self._levels = self._build(self._leaf_hashes)

    @staticmethod
    def _build(leaf_hashes: list[bytes]) -> list[list[bytes]]:
        levels = [leaf_hashes]
        current = leaf_hashes
        while len(current) > 1:
            nxt: list[bytes] = []
            for i in range(0, len(current) - 1, 2):
                nxt.append(node_hash(current[i], current[i + 1]))
            if len(current) % 2 == 1:
                # Promote the odd tail rather than duplicating it.
                nxt.append(current[-1])
            levels.append(nxt)
            current = nxt
        return levels

    @property
    def root(self) -> bytes:
        return self._levels[-1][0]

    @property
    def root_hex(self) -> str:
        return self.root.hex()

    @property
    def leaf_count(self) -> int:
        return len(self._leaf_hashes)

    def proof_for(self, index: int) -> InclusionProof:
        """Build the inclusion proof for the leaf at *index*."""
        if not 0 <= index < self.leaf_count:
            raise IndexError(f"Leaf index {index} out of range")

        siblings: list[tuple[str, str]] = []
        position = index

        for level in self._levels[:-1]:
            if position % 2 == 0:
                sibling = position + 1
                if sibling >= len(level):
                    # Promoted node: nothing to combine with at this level.
                    position //= 2
                    continue
                siblings.append(("R", level[sibling].hex()))
            else:
                siblings.append(("L", level[position - 1].hex()))
            position //= 2

        return InclusionProof(
            leaf_index=index,
            leaf_count=self.leaf_count,
            siblings=tuple(siblings),
        )


def verify_inclusion(payload: bytes, proof: InclusionProof, root_hex: str) -> bool:
    """Recompute the root from *payload* and *proof* and compare it to *root_hex*.

    A verifier only needs the credential, the proof, and the anchored root — not
    the rest of the batch, and not this platform's database.
    """
    computed = leaf_hash(payload)
    for position, sibling_hex in proof.siblings:
        sibling = bytes.fromhex(sibling_hex)
        computed = (
            node_hash(sibling, computed)
            if position == "L"
            else node_hash(computed, sibling)
        )
    return computed.hex() == root_hex


class MerkleTree:
    """An immutable Merkle tree built from ordered leaf payloads."""

    def __init__(self, leaves: list[bytes]) -> None:
        if not leaves:
            raise ValueError("A Merkle tree needs at least one leaf")
        self._leaf_hashes = [leaf_hash(leaf) for leaf in leaves]
        self._levels = self._build(self._leaf_hashes)

    @staticmethod
    def _build(leaf_hashes: list[bytes]) -> list[list[bytes]]:
        levels = [leaf_hashes]
        current = leaf_hashes
        while len(current) > 1:
            nxt: list[bytes] = []
            for i in range(0, len(current) - 1, 2):
                nxt.append(node_hash(current[i], current[i + 1]))
            if len(current) % 2 == 1:
                # Promote the odd tail rather than duplicating it.
                nxt.append(current[-1])
            levels.append(nxt)
            current = nxt
        return levels

    @property
    def root(self) -> bytes:
        return self._levels[-1][0]

    @property
    def root_hex(self) -> str:
        return self.root.hex()

    @property
    def leaf_count(self) -> int:
        return len(self._leaf_hashes)

    def proof_for(self, index: int) -> InclusionProof:
        """Build the inclusion proof for the leaf at *index*."""
        if not 0 <= index < self.leaf_count:
            raise IndexError(f"Leaf index {index} out of range")

        siblings: list[tuple[str, str]] = []
        position = index

        for level in self._levels[:-1]:
            if position % 2 == 0:
                sibling = position + 1
                if sibling >= len(level):
                    # Promoted node: nothing to combine with at this level.
                    position //= 2
                    continue
                siblings.append(("R", level[sibling].hex()))
            else:
                siblings.append(("L", level[position - 1].hex()))
            position //= 2

        return InclusionProof(
            leaf_index=index,
            leaf_count=self.leaf_count,
            siblings=tuple(siblings),
        )


def verify_inclusion(payload: bytes, proof: InclusionProof, root_hex: str) -> bool:
    """Recompute the root from *payload* and *proof* and compare it to *root_hex*.

    A verifier needs only the credential, the proof, and the anchored root — not
    the rest of the batch, and not this platform's database.
    """
    computed = leaf_hash(payload)
    for position, sibling_hex in proof.siblings:
        sibling = bytes.fromhex(sibling_hex)
        computed = (
            node_hash(sibling, computed)
            if position == "L"
            else node_hash(computed, sibling)
        )
    return computed.hex() == root_hex
