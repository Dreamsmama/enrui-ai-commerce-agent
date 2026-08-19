"""Export/import tenant business demo data without account credentials or history."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import SessionLocal, init_db
from app.models import DesignSkill, KnowledgeDocument, Product, TenantMember, User
from app.rag import index_document


PRODUCT_FIELDS = [
    "name", "category", "price", "description", "target_users", "brand_name",
    "ingredients", "usage_method", "specifications", "learned_profile_enabled",
]
DOCUMENT_FIELDS = ["brand_name", "title", "doc_type", "filename", "content"]
SKILL_FIELDS = [
    "name", "scope", "category", "brand_name", "description", "design_principles",
    "module_guidance", "visual_rules", "copy_rules", "negative_rules",
    "primary_color", "accent_color", "enabled",
]


def tenant_for_email(db, email: str) -> str:
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise RuntimeError(f"账户不存在，请先注册：{email}")
    member = db.query(TenantMember).filter(
        TenantMember.user_id == user.id,
        TenantMember.status == "active",
    ).first()
    if not member:
        raise RuntimeError(f"账户没有可用租户：{email}")
    return member.tenant_id


def copy_asset_for_export(url: str, output_dir: Path, used_names: set[str]) -> str:
    if not url.startswith("/uploads/"):
        return url
    source = get_settings().upload_path / url.removeprefix("/uploads/")
    if not source.exists():
        return url
    name = source.name
    if name in used_names:
        name = f"{uuid.uuid4().hex[:8]}-{name}"
    used_names.add(name)
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, assets_dir / name)
    return f"assets/{name}"


def export_data(email: str, output_dir: Path) -> None:
    db = SessionLocal()
    try:
        tenant_id = tenant_for_email(db, email)
        products = db.query(Product).filter(Product.tenant_id == tenant_id).all()
        product_ids = {product.id for product in products}
        used_names: set[str] = set()
        payload = {"version": 1, "products": [], "documents": [], "skills": []}
        for product in products:
            item = {field: getattr(product, field) for field in PRODUCT_FIELDS}
            item["image_urls"] = [copy_asset_for_export(url, output_dir, used_names) for url in (product.image_urls or [])]
            item["detail_image_urls"] = [copy_asset_for_export(url, output_dir, used_names) for url in (product.detail_image_urls or [])]
            payload["products"].append(item)
        documents = db.query(KnowledgeDocument).filter(KnowledgeDocument.tenant_id == tenant_id).all()
        for document in documents:
            item = {field: getattr(document, field) for field in DOCUMENT_FIELDS}
            item["product_name"] = document.product.name if document.product_id in product_ids and document.product else None
            payload["documents"].append(item)
        skills = db.query(DesignSkill).filter(DesignSkill.tenant_id == tenant_id).all()
        for skill in skills:
            item = {field: getattr(skill, field) for field in SKILL_FIELDS}
            item["product_name"] = next((product.name for product in products if product.id == skill.product_id), None)
            payload["skills"].append(item)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"exported products={len(products)} documents={len(documents)} skills={len(skills)} to {output_dir}")
    finally:
        db.close()


def import_asset(url: str, package_dir: Path) -> str:
    if not url.startswith("assets/"):
        return url
    source = package_dir / url
    if not source.exists():
        raise RuntimeError(f"缺少素材文件：{source}")
    target_dir = get_settings().upload_path / "imported"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid.uuid4().hex}-{source.name}"
    shutil.copy2(source, target)
    return f"/uploads/imported/{target.name}"


async def import_data(email: str, package_dir: Path) -> None:
    payload = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    db = SessionLocal()
    try:
        tenant_id = tenant_for_email(db, email)
        product_map: dict[str, Product] = {}
        for item in payload["products"]:
            product = db.query(Product).filter(Product.tenant_id == tenant_id, Product.name == item["name"]).first()
            if not product:
                product = Product(tenant_id=tenant_id, name=item["name"])
                db.add(product)
            for field in PRODUCT_FIELDS:
                setattr(product, field, item[field])
            product.image_urls = [import_asset(url, package_dir) for url in item.get("image_urls", [])]
            product.detail_image_urls = [import_asset(url, package_dir) for url in item.get("detail_image_urls", [])]
            db.flush()
            product_map[product.name] = product
        db.commit()
        for item in payload["documents"]:
            document = db.query(KnowledgeDocument).filter(KnowledgeDocument.tenant_id == tenant_id, KnowledgeDocument.title == item["title"]).first()
            if not document:
                document = KnowledgeDocument(tenant_id=tenant_id, title=item["title"])
                db.add(document)
            for field in DOCUMENT_FIELDS:
                setattr(document, field, item[field])
            document.product_id = product_map[item["product_name"]].id if item.get("product_name") else None
            db.commit()
            db.refresh(document)
            await index_document(db, document)
        for item in payload["skills"]:
            skill = db.query(DesignSkill).filter(DesignSkill.tenant_id == tenant_id, DesignSkill.name == item["name"]).first()
            if not skill:
                skill = DesignSkill(tenant_id=tenant_id, name=item["name"])
                db.add(skill)
            for field in SKILL_FIELDS:
                setattr(skill, field, item[field])
            skill.product_id = product_map[item["product_name"]].id if item.get("product_name") else None
        db.commit()
        print(f"imported products={len(payload['products'])} documents={len(payload['documents'])} skills={len(payload['skills'])} for {email}")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--email", required=True)
    export_parser.add_argument("--output", required=True, type=Path)
    import_parser = subparsers.add_parser("import")
    import_parser.add_argument("--email", required=True)
    import_parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    init_db()
    if args.command == "export":
        export_data(args.email, args.output)
    else:
        asyncio.run(import_data(args.email, args.input))


if __name__ == "__main__":
    main()
