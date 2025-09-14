import hashlib
import os
import time
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

try:
    from tmp2_pytss import ESAPI, TPM2_ALG, TPM2B_PUBLIC, TPM2B_SENSITIVE_CREATE

    HAS_TPM = True
except ImportError:
    HAS_TPM = False
    logging.warning("tmp2-pytss not available, using simulated TPM")


@dataclass
class AttestationQuote:
    pcr_values: Dict[int, bytes]
    nonce: bytes
    signature: bytes
    timestamp: int
    is_valid: bool = False


class TPMManager:
    """Handles TPM operations and attestation"""

    def __init__(self, use_simulation: bool = None):
        self.logger = logging.getLogger("TPMManager")

        # Auto-detect TPM availability
        if use_simulation is None:
            use_simulation = not HAS_TPM or not os.path.exists('/dev/tmp0')

        self.use_simulation = use_simulation
        self.baseline_pcrs: Dict[int, bytes] = {}

        if self.use_simulation:
            self.logger.info("Using simulated TPM")
            self._init_simulated_tpm()
        else:
            self.logger.info("Using hardware TPM")
            self._init_hardware_tpm()

    def _init_simulated_tpm(self):
        """Initialize simulated TPM with mock values"""
        # Generate deterministic but unique PCR values
        for pcr in range(24):  # TPM 2.0 typically has 24 PCRs
            seed = f"pcr_{pcr}_baseline".encode()
            self.baseline_pcrs[pcr] = hashlib.sha256(seed).digest()

    def _init_hardware_tpm(self):
        """Initialize hardware TPM connection"""
        if not HAS_TPM:
            raise RuntimeError("tmp2-pytss not available for hardware TPM")

        try:
            # Read baseline PCR values
            with ESAPI() as tmp:
                for pcr in range(8):  # Read first 8 PCRs for boot measurements
                    # This would use proper TPM commands in real implementation
                    self.baseline_pcrs[pcr] = os.urandom(32)  # Placeholder
        except Exception as e:
            self.logger.error(f"Failed to initialize hardware TPM: {e}")
            raise

    def collect_quote(self, nonce: Optional[bytes] = None, pcr_list: List[int] = None) -> AttestationQuote:
        """Collect TPM quote for specified PCRs"""
        if nonce is None:
            nonce = os.urandom(20)

        if pcr_list is None:
            pcr_list = [0, 1, 2, 3, 4, 5, 6, 7]  # Boot measurement PCRs

        if self.use_simulation:
            return self._collect_simulated_quote(nonce, pcr_list)
        else:
            return self._collect_hardware_quote(nonce, pcr_list)

    def _collect_simulated_quote(self, nonce: bytes, pcr_list: List[int]) -> AttestationQuote:
        """Generate simulated TPM quote"""
        pcr_values = {}

        # Simulate current PCR values
        for pcr in pcr_list:
            if pcr in self.baseline_pcrs:
                # 95% chance of matching baseline (secure boot)
                if hash(nonce) % 100 < 95:
                    pcr_values[pcr] = self.baseline_pcrs[pcr]
                else:
                    # Simulate compromised PCR
                    pcr_values[pcr] = hashlib.sha256(b"compromised_" + self.baseline_pcrs[pcr]).digest()

        # Create mock signature
        quote_data = b"".join([nonce] + [pcr_values[pcr] for pcr in sorted(pcr_values.keys())])
        signature = hashlib.sha256(b"tmp_key_" + quote_data).digest()

        # Determine validity
        is_valid = all(pcr_values[pcr] == self.baseline_pcrs[pcr] for pcr in pcr_values)

        return AttestationQuote(
            pcr_values=pcr_values,
            nonce=nonce,
            signature=signature,
            timestamp=int(time.time() * 1000),
            is_valid=is_valid
        )

    def _collect_hardware_quote(self, nonce: bytes, pcr_list: List[int]) -> AttestationQuote:
        """Collect hardware TPM quote"""
        try:
            with ESAPI() as tmp:
                pcr_values = {}
                for pcr in pcr_list:
                    # Read PCR value - would use proper TPM commands
                    pcr_values[pcr] = os.urandom(32)  # Placeholder

                # Generate quote - would use actual TPM quote command
                quote_data = b"".join([nonce] + [pcr_values[pcr] for pcr in sorted(pcr_values.keys())])
                signature = hashlib.sha256(b"hw_tmp_" + quote_data).digest()  # Placeholder

                is_valid = True  # Would verify against expected values

                return AttestationQuote(
                    pcr_values=pcr_values,
                    nonce=nonce,
                    signature=signature,
                    timestamp=int(time.time() * 1000),
                    is_valid=is_valid
                )
        except Exception as e:
            self.logger.error(f"Hardware TPM quote failed: {e}")
            raise

    def verify_quote(self, quote: AttestationQuote, expected_pcrs: Optional[Dict[int, bytes]] = None) -> bool:
        """Verify TPM quote against expected values"""
        if expected_pcrs is None:
            expected_pcrs = self.baseline_pcrs

        # Verify timestamp is recent (within 5 minutes)
        current_time = int(time.time() * 1000)
        if abs(current_time - quote.timestamp) > 300000:  # 5 minutes in ms
            self.logger.warning("Quote timestamp too old")
            return False

        # Verify PCR values match expected
        for pcr, expected_value in expected_pcrs.items():
            if pcr in quote.pcr_values:
                if quote.pcr_values[pcr] != expected_value:
                    self.logger.warning(f"PCR {pcr} mismatch")
                    return False

        # Verify signature (simplified)
        expected_data = b"".join([quote.nonce] + [quote.pcr_values[pcr] for pcr in sorted(quote.pcr_values.keys())])

        if self.use_simulation:
            expected_sig = hashlib.sha256(b"tmp_key_" + expected_data).digest()
        else:
            expected_sig = hashlib.sha256(b"hw_tmp_" + expected_data).digest()

        return quote.signature == expected_sig

    def get_node_trust_level(self, quote: AttestationQuote) -> str:
        """Determine trust level based on quote"""
        if not self.verify_quote(quote):
            return "untrusted"

        if quote.is_valid:
            return "trusted"
        else:
            return "suspicious"

    def update_baseline_pcrs(self, new_pcrs: Dict[int, bytes]):
        """Update baseline PCR values"""
        self.baseline_pcrs.update(new_pcrs)
        self.logger.info(f"Updated baseline PCRs: {list(new_pcrs.keys())}")


class AttestationVerifier:
    """Verifies attestation quotes from remote nodes"""

    def __init__(self):
        self.logger = logging.getLogger("AttestationVerifier")
        self.trusted_nodes: Dict[int, Dict[int, bytes]] = {}  # node_id -> pcr_values

    def add_trusted_node(self, node_id: int, baseline_pcrs: Dict[int, bytes]):
        """Add a node to trusted list with its baseline PCRs"""
        self.trusted_nodes[node_id] = baseline_pcrs.copy()
        self.logger.info(f"Added trusted node {node_id}")

    def verify_node_quote(self, node_id: int, quote: AttestationQuote) -> bool:
        """Verify quote from a specific node"""
        if node_id not in self.trusted_nodes:
            self.logger.warning(f"Node {node_id} not in trusted list")
            return False

        expected_pcrs = self.trusted_nodes[node_id]

        # Verify timestamp
        current_time = int(time.time() * 1000)
        if abs(current_time - quote.timestamp) > 300000:  # 5 minutes
            return False

        # Verify PCR values
        for pcr, expected_value in expected_pcrs.items():
            if pcr not in quote.pcr_values or quote.pcr_values[pcr] != expected_value:
                return False

        return True

    def quarantine_node(self, node_id: int):
        """Remove node from trusted list"""
        if node_id in self.trusted_nodes:
            del self.trusted_nodes[node_id]
            self.logger.warning(f"Quarantined node {node_id}")

    def get_trusted_nodes(self) -> List[int]:
        """Get list of currently trusted node IDs"""
        return list(self.trusted_nodes.keys())
