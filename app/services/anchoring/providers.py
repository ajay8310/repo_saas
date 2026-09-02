"""
Anchor providers.

``LocalLedgerAnchorProvider``
    An append-only, hash-chained log in the platform's own database.  Each entry
    commits to its predecessor, so removing or editing a historical root breaks
    every subsequent link and is detectable.  This is a transparency log, not a
    blockchain: it establishes internal tamper-evidence without an external
    dependency, and is the default so anchoring is exercised end to end from a
    clean install.  It does *not* provide third-party non-repudiation — for that
    the root must leave the platform's trust boundary.

``EvmAnchorProvider``
    Publishes roots to an EVM chain (Polygon, a permissioned Besu network, or a
    testnet) over JSON-RPC.  Requires a signed-transaction endpoint; the private
    key deliberately never enters this process, so signing is delegated to a
    configured signer service rather than held in application memory.

``FabricAnchorProvider``
    Placeholder for Hyperledger Fabric, which is common in Indian government
    deployments.  Raises on use with a message naming the setting to configure,
    rather than pretending to anchor.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.anchoring.base import (
    AnchorReceipt,
    AnchorUnavailableError,
)

logger = logging.getLogger(__name__)


class LocalLedgerAnchorProvider:
    """Append-only hash-chained ledger held in ``anchor_ledger``."""

    name = "local"

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def publish(self, root_hex: str, *, batch_id: str) -> AnchorReceipt:
        import hashlib

        # Chain to the current tip so history cannot be rewritten silently.
        tip = (
            await self._db.execute(
                text(
                    "SELECT seq, entry_hash FROM anchor_ledger "
                    "ORDER BY seq DESC LIMIT 1"
                )
            )
        ).first()

        prev_seq = tip[0] if tip else 0
        prev_hash = tip[1] if tip else "0" * 64
        seq = prev_seq + 1
        anchored_at = datetime.now(UTC)

        entry_hash = hashlib.sha256(
            f"{seq}|{prev_hash}|{root_hex}|{anchored_at.isoformat()}".encode()
        ).hexdigest()

        await self._db.execute(
            text(
                """
                INSERT INTO anchor_ledger
                    (seq, prev_hash, root_hex, entry_hash, anchored_at, batch_id)
                VALUES
                    (:seq, :prev_hash, :root_hex, :entry_hash, :anchored_at, :batch_id)
                """
            ),
            {
                "seq": seq,
                "prev_hash": prev_hash,
                "root_hex": root_hex,
                "entry_hash": entry_hash,
                "anchored_at": anchored_at,
                "batch_id": batch_id,
            },
        )
        await self._db.commit()

        return AnchorReceipt(
            provider=self.name,
            ledger_ref=str(seq),
            root_hex=root_hex,
            anchored_at=anchored_at,
            metadata={"entry_hash": entry_hash, "prev_hash": prev_hash},
        )

    async def resolve(self, ledger_ref: str) -> str | None:
        try:
            seq = int(ledger_ref)
        except ValueError:
            return None
        row = (
            await self._db.execute(
                text("SELECT root_hex FROM anchor_ledger WHERE seq = :seq"),
                {"seq": seq},
            )
        ).first()
        return row[0] if row else None


class EvmAnchorProvider:
    """Publishes roots to an EVM-compatible chain via JSON-RPC.

    The root is written as transaction calldata to a contract that emits it as
    an event.  Calldata is enough: the goal is a timestamped, immutable record
    of a 32-byte value, which needs no contract storage and keeps gas minimal.

    Signing is delegated to ``anchor_signer_url`` rather than performed here, so
    no private key is loaded into the API or worker process.
    """

    name = "evm"

    def __init__(
        self,
        rpc_url: str,
        signer_url: str,
        contract_address: str,
        timeout_seconds: float = 20.0,
    ) -> None:
        if not rpc_url or not signer_url or not contract_address:
            raise AnchorUnavailableError(
                "EVM anchoring requires anchor_rpc_url, anchor_signer_url and "
                "anchor_contract_address"
            )
        self._rpc_url = rpc_url
        self._signer_url = signer_url
        self._contract = contract_address
        self._timeout = timeout_seconds

    async def publish(self, root_hex: str, *, batch_id: str) -> AnchorReceipt:
        payload = {
            "to": self._contract,
            # 0x-prefixed 32-byte root as calldata.
            "data": "0x" + root_hex,
            "batch_id": batch_id,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                # The signer holds the key, signs, and broadcasts.
                response = await client.post(f"{self._signer_url}/sign-and-send", json=payload)
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
            raise AnchorUnavailableError(f"EVM anchor failed: {exc}") from exc

        tx_hash = body.get("transaction_hash") or body.get("txHash")
        if not tx_hash:
            raise AnchorUnavailableError(
                "Signer did not return a transaction hash; treating as unpublished"
            )

        return AnchorReceipt(
            provider=self.name,
            ledger_ref=tx_hash,
            root_hex=root_hex,
            anchored_at=datetime.now(UTC),
            metadata={"contract": self._contract, "chain_rpc": self._rpc_url},
        )

    async def resolve(self, ledger_ref: str) -> str | None:
        request: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getTransactionByHash",
            "params": [ledger_ref],
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self._rpc_url, json=request)
                response.raise_for_status()
                result = response.json().get("result")
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Could not resolve anchor %s: %s", ledger_ref, exc)
            return None

        if not result:
            return None
        data = (result.get("input") or "").removeprefix("0x")
        return data or None


class FabricAnchorProvider:
    """Hyperledger Fabric anchoring — not implemented.

    Fails loudly rather than silently doing nothing, so a deployment that
    selects it cannot believe it is anchoring when it is not.
    """

    name = "fabric"

    def __init__(self, *_: object, **__: object) -> None:
        raise AnchorUnavailableError(
            "The Fabric anchor provider is not implemented. Implement publish()/"
            "resolve() against your channel's chaincode, or set "
            "anchor_provider='local' or 'evm'."
        )

    async def publish(self, root_hex: str, *, batch_id: str) -> AnchorReceipt:
        raise AnchorUnavailableError("Fabric anchoring is not implemented")

    async def resolve(self, ledger_ref: str) -> str | None:
        raise AnchorUnavailableError("Fabric anchoring is not implemented")
