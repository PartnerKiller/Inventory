import os
import time
import base64
import hmac
import hashlib
import struct
import secrets
from typing import Tuple, List, Optional
from fastapi import HTTPException

class TOTPService:
    @staticmethod
    def generate_secret() -> str:
        """Generates a 160-bit cryptographically secure Base32 secret key."""
        random_bytes = secrets.token_bytes(20)
        return base64.b32encode(random_bytes).decode("utf-8").replace("=", "")

    @staticmethod
    def generate_qr_uri(secret: str, email: str, issuer: str = "AuraStock") -> str:
        """Formats the RFC 6238 standard OTPAuth URI for authenticator apps."""
        return f"otpauth://totp/{issuer}:{email}?secret={secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"

    @staticmethod
    def compute_totp(secret: str, time_step: Optional[int] = None) -> str:
        """Computes a 6-digit TOTP code for a given secret and timestep counter."""
        ts = int(time_step if time_step is not None else (time.time() // 30))
        # Ensure secret has proper Base32 padding
        padded_secret = secret + "=" * ((8 - len(secret) % 8) % 8)
        key = base64.b32decode(padded_secret, casefold=True)
        msg = struct.pack(">Q", ts)
        h = hmac.new(key, msg, hashlib.sha1).digest()
        offset = h[-1] & 0x0F
        code_int = struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF
        return f"{code_int % 1000000:06d}"

    @staticmethod
    def verify_totp(
        secret: str,
        code: str,
        last_timestep: int = 0,
        tolerance: int = 1
    ) -> Tuple[bool, int]:
        """
        Verifies a 6-digit TOTP code against secret with clock skew tolerance (±1 step).
        Enforces single-use replay protection by ensuring matched timestep > last_timestep.
        """
        if not code or len(code.strip()) != 6 or not code.strip().isdigit():
            return False, 0

        current_step = int(time.time() // 30)

        for step_offset in range(-tolerance, tolerance + 1):
            eval_step = current_step + step_offset
            expected_code = TOTPService.compute_totp(secret, time_step=eval_step)
            if hmac.compare_digest(expected_code, code.strip()):
                if eval_step <= last_timestep:
                    raise HTTPException(status_code=400, detail="TOTP Code Replay Detected: Code has already been used")
                return True, eval_step

        return False, 0

    @staticmethod
    def generate_recovery_codes(count: int = 10) -> Tuple[List[str], List[str]]:
        """Generates random single-use backup recovery codes and their SHA256 hashes."""
        raw_codes = []
        code_hashes = []
        for _ in range(count):
            part1 = secrets.token_hex(2).upper()
            part2 = secrets.token_hex(2).upper()
            part3 = secrets.token_hex(2).upper()
            code_str = f"{part1}-{part2}-{part3}"
            raw_codes.append(code_str)
            h = hashlib.sha256(code_str.encode("utf-8")).hexdigest()
            code_hashes.append(h)
        return raw_codes, code_hashes

    @staticmethod
    def hash_recovery_code(raw_code: str) -> str:
        return hashlib.sha256(raw_code.strip().upper().encode("utf-8")).hexdigest()
