import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base


class ProductBulkBatchStatus(str, enum.Enum):
    uploaded = "uploaded"
    mapped = "mapped"
    first_generating = "first_generating"
    awaiting_template_approval = "awaiting_template_approval"
    approved_template = "approved_template"
    generating_all = "generating_all"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ProductBulkItemStatus(str, enum.Enum):
    pending = "pending"
    first_sample = "first_sample"
    generating = "generating"
    generated = "generated"
    approved = "approved"
    rejected = "rejected"
    failed = "failed"


class ProductBulkAssetStatus(str, enum.Enum):
    pending = "pending"
    generating = "generating"
    generated = "generated"
    approved = "approved"
    rejected = "rejected"
    failed = "failed"


class ProductTemplateDirectionStatus(str, enum.Enum):
    candidate = "candidate"
    approved = "approved"
    rejected = "rejected"


class ProductBulkBatch(Base):
    __tablename__ = "product_bulk_batches"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    suite_id: Mapped[str] = mapped_column(String, ForeignKey("suites.id"), nullable=False, index=True)
    created_by: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False, default="Product bulk batch")
    status: Mapped[ProductBulkBatchStatus] = mapped_column(
        Enum(ProductBulkBatchStatus),
        nullable=False,
        default=ProductBulkBatchStatus.uploaded,
        index=True,
    )
    source_excel_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_zip_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    creative_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    column_mapping: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    approved_template_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    brand_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    total_products: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_products: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_products: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    items: Mapped[list["ProductBulkItem"]] = relationship(
        "ProductBulkItem",
        back_populates="batch",
        cascade="all, delete-orphan",
    )
    assets: Mapped[list["ProductBulkAsset"]] = relationship(
        "ProductBulkAsset",
        back_populates="batch",
        cascade="all, delete-orphan",
    )
    template_directions: Mapped[list["ProductTemplateDirection"]] = relationship(
        "ProductTemplateDirection",
        back_populates="batch",
        cascade="all, delete-orphan",
    )


class ProductBulkItem(Base):
    __tablename__ = "product_bulk_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    batch_id: Mapped[str] = mapped_column(String, ForeignKey("product_bulk_batches.id"), nullable=False, index=True)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    product_name: Mapped[str] = mapped_column(Text, nullable=False)
    image_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    slogan: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    global_addition: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_row: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[ProductBulkItemStatus] = mapped_column(
        Enum(ProductBulkItemStatus),
        nullable=False,
        default=ProductBulkItemStatus.pending,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    batch: Mapped["ProductBulkBatch"] = relationship("ProductBulkBatch", back_populates="items")
    assets: Mapped[list["ProductBulkAsset"]] = relationship(
        "ProductBulkAsset",
        back_populates="item",
        cascade="all, delete-orphan",
    )


class ProductBulkAsset(Base):
    __tablename__ = "product_bulk_assets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    batch_id: Mapped[str] = mapped_column(String, ForeignKey("product_bulk_batches.id"), nullable=False, index=True)
    item_id: Mapped[str] = mapped_column(String, ForeignKey("product_bulk_items.id"), nullable=False, index=True)
    template_direction_id: Mapped[Optional[str]] = mapped_column(
        String,
        ForeignKey("product_template_directions.id"),
        nullable=True,
    )
    status: Mapped[ProductBulkAssetStatus] = mapped_column(
        Enum(ProductBulkAssetStatus),
        nullable=False,
        default=ProductBulkAssetStatus.pending,
        index=True,
    )
    media_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    media_type: Mapped[str] = mapped_column(String, nullable=False, default="image")
    prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    batch: Mapped["ProductBulkBatch"] = relationship("ProductBulkBatch", back_populates="assets")
    item: Mapped["ProductBulkItem"] = relationship("ProductBulkItem", back_populates="assets")


class ProductTemplateDirection(Base):
    __tablename__ = "product_template_directions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    batch_id: Mapped[str] = mapped_column(String, ForeignKey("product_bulk_batches.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    visual_rules: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    prompt_rules: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    sample_asset_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[ProductTemplateDirectionStatus] = mapped_column(
        Enum(ProductTemplateDirectionStatus),
        nullable=False,
        default=ProductTemplateDirectionStatus.candidate,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    batch: Mapped["ProductBulkBatch"] = relationship("ProductBulkBatch", back_populates="template_directions")
