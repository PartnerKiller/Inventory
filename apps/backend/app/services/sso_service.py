import uuid
import base64
import hashlib
import secrets
from typing import Dict, Any, Tuple, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from app.models.auth_security import SSOConfiguration
from app.schemas.auth_security import SSOConfigCreate, SSOConfigResponse, SSOInitiateResponse

class SSOService:
    @staticmethod
    def generate_pkce_pair() -> Tuple[str, str]:
        """Generates PKCE code_verifier and code_challenge using SHA256."""
        code_verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return code_verifier, code_challenge

    @staticmethod
    async def configure_sso(
        db: AsyncSession,
        tenant_id: str,
        config_in: SSOConfigCreate
    ) -> SSOConfigResponse:
        existing = (await db.execute(
            select(SSOConfiguration).where(SSOConfiguration.tenant_id == tenant_id)
        )).scalar_one_or_none()

        if existing:
            existing.domain = config_in.domain
            existing.provider_type = config_in.provider_type
            existing.issuer_url = config_in.issuer_url
            existing.client_id = config_in.client_id
            existing.client_secret = config_in.client_secret
            existing.is_active = config_in.is_active
            existing.allow_password_fallback = config_in.allow_password_fallback
            config = existing
        else:
            config = SSOConfiguration(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                domain=config_in.domain.lower().strip(),
                provider_type=config_in.provider_type,
                issuer_url=config_in.issuer_url,
                client_id=config_in.client_id,
                client_secret=config_in.client_secret,
                is_active=config_in.is_active,
                allow_password_fallback=config_in.allow_password_fallback
            )
            db.add(config)

        await db.commit()
        await db.refresh(config)

        return SSOConfigResponse(
            id=config.id,
            tenant_id=config.tenant_id,
            domain=config.domain,
            provider_type=config.provider_type,
            issuer_url=config.issuer_url,
            client_id=config.client_id,
            is_active=config.is_active,
            allow_password_fallback=config.allow_password_fallback,
            created_at=config.created_at
        )

    @staticmethod
    async def initiate_sso(
        db: AsyncSession,
        tenant_domain: str
    ) -> SSOInitiateResponse:
        config = (await db.execute(
            select(SSOConfiguration).where(
                SSOConfiguration.domain == tenant_domain.lower().strip(),
                SSOConfiguration.is_active == True
            )
        )).scalar_one_or_none()

        if not config:
            raise HTTPException(status_code=404, detail=f"No active SSO configuration found for domain '{tenant_domain}'")

        code_verifier, code_challenge = SSOService.generate_pkce_pair()
        state = f"state_{uuid.uuid4().hex}"
        nonce = f"nonce_{uuid.uuid4().hex}"

        auth_url = (
            f"{config.issuer_url.rstrip('/')}/authorize?"
            f"client_id={config.client_id}&"
            f"response_type=code&"
            f"scope=openid%20profile%20email&"
            f"state={state}&"
            f"nonce={nonce}&"
            f"code_challenge={code_challenge}&"
            f"code_challenge_method=S256"
        )

        return SSOInitiateResponse(auth_url=auth_url, state=state)

    @staticmethod
    def validate_oidc_claims(
        claims: Dict[str, Any],
        expected_issuer: str,
        expected_audience: str,
        expected_nonce: str,
        expected_domain: str
    ) -> Dict[str, Any]:
        """
        Strictly validates IdP claims:
        - Issuer matches
        - Audience matches client_id
        - Nonce matches challenge
        - email_verified is True
        - Email matches tenant's authorized domain
        """
        if claims.get("iss") != expected_issuer:
            raise HTTPException(status_code=400, detail=f"OIDC Issuer mismatch: expected {expected_issuer}, got {claims.get('iss')}")

        aud = claims.get("aud")
        if isinstance(aud, list):
            if expected_audience not in aud:
                raise HTTPException(status_code=400, detail="OIDC Audience mismatch")
        elif aud != expected_audience:
            raise HTTPException(status_code=400, detail="OIDC Audience mismatch")

        if claims.get("nonce") != expected_nonce:
            raise HTTPException(status_code=400, detail="OIDC Nonce validation failed")

        if not claims.get("email_verified", False):
            raise HTTPException(status_code=400, detail="Account Takeover Prevention: IdP email is not verified")

        email = claims.get("email", "").lower().strip()
        if not email or not email.endswith(f"@{expected_domain.lower()}"):
            raise HTTPException(status_code=400, detail=f"SSO Domain mismatch: email must belong to domain {expected_domain}")

        return claims
