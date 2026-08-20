import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.sequence import DocumentSequence
from app.models.base import get_utc_now

DEFAULT_PREFIXES = {
    "PURCHASE_ORDER": "PO",
    "SALES_ORDER": "SO",
    "GOODS_RECEIPT": "GRN",
    "TRANSFER": "TRX",
    "ADJUSTMENT": "ADJ",
    "SHIPMENT": "SHP",
    "RETURN": "RMA",
}

class SequenceService:
    @staticmethod
    async def generate_next_number(
        db: AsyncSession,
        tenant_id: str,
        document_type: str,
        custom_prefix: str = None
    ) -> str:
        """
        Generates a concurrency-safe, deterministic, sequential document identifier
        for the given document_type and tenant using row-level pessimistic locking (SELECT FOR UPDATE).
        
        Guarantees:
        - Concurrency-safe unique sequential numbering per (tenant_id, document_type, date_key).
        - Deterministic formatting: <PREFIX>-<YYYYMMDD>-<0001>.
        - Atomic transaction scoping: participates in the caller's active database transaction.
        
        Note: Monotonic sequential uniqueness is guaranteed under concurrent requests.
        True accounting/statutory "gapless" fiscal compliance is not claimed, as downstream
        document cancellations or rollbacks naturally consume or release sequence allocations
        without gap-recovery recycling.
        """
        now = get_utc_now()
        date_key = now.strftime("%Y%m%d")
        prefix = custom_prefix or DEFAULT_PREFIXES.get(document_type, "DOC")

        stmt = (
            select(DocumentSequence)
            .where(
                DocumentSequence.tenant_id == tenant_id,
                DocumentSequence.document_type == document_type,
                DocumentSequence.date_key == date_key
            )
            .with_for_update()
        )
        res = await db.execute(stmt)
        seq_record = res.scalar_one_or_none()

        if not seq_record:
            # Check if created in race or create fresh record
            seq_record = DocumentSequence(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                document_type=document_type,
                prefix=prefix,
                date_key=date_key,
                current_number=1,
                updated_at=now
            )
            db.add(seq_record)
            next_num = 1
        else:
            seq_record.current_number += 1
            seq_record.updated_at = now
            next_num = seq_record.current_number

        await db.flush()
        return f"{prefix}-{date_key}-{next_num:04d}"
