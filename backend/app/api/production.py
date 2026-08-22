"""Product facts, immutable review snapshots, SKU batches and production analytics."""
from __future__ import annotations
import csv
import io
import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import AuthContext, current_auth
from app.database import get_db
from app.models import CanvasNode, CreativeGeneration, CreativePlan, CreativeProject, DetailPageTemplate, Product, ProductFact, ProductionQueueTask, ProjectReview, ProjectSnapshot, SkuBatch, SkuBatchItem, StoryboardModule
from app.schemas import DetailPageTemplateApply
from app.api.templates import apply_template
from app.services.redis_client import notify_queue

router=APIRouter(prefix="/production",tags=["production"])

class FactPayload(BaseModel): fact_key:str; label:str; value:str; source_type:str="manual"; source_ref:str=""
class SnapshotCompare(BaseModel): left_version:int; right_version:int

DEFAULT_FACTS=[("name","商品名称"),("brand_name","品牌"),("category","品类"),("description","核心卖点"),("target_users","目标用户"),("ingredients","成分"),("usage_method","使用方法"),("specifications","规格/套装组成")]

def ensure_product_facts(product:Product,db:Session,tenant_id:str)->list[ProductFact]:
    existing={f.fact_key:f for f in db.query(ProductFact).filter_by(product_id=product.id,tenant_id=tenant_id).all()}
    for key,label in DEFAULT_FACTS:
        value=str(getattr(product,key) or "")
        if key not in existing:
            row=ProductFact(tenant_id=tenant_id,product_id=product.id,fact_key=key,label=label,value=value,source_type="product_record",source_ref=f"product:{product.id}",status="confirmed" if value else "pending",confidence=1.0)
            db.add(row);existing[key]=row
        elif value and existing[key].value and value != existing[key].value and value not in existing[key].conflict_values:
            existing[key].conflict_values=[*existing[key].conflict_values,value];existing[key].status="conflict"
    db.commit();return list(existing.values())

@router.get("/products/{product_id}/facts")
def list_facts(product_id:int,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    product=db.query(Product).filter_by(id=product_id,tenant_id=auth.tenant_id).first()
    if not product:raise HTTPException(404,"商品不存在")
    rows=ensure_product_facts(product,db,auth.tenant_id)
    return sorted(rows,key=lambda x:x.id)

@router.put("/products/{product_id}/facts")
def upsert_fact(product_id:int,payload:FactPayload,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    product=db.query(Product).filter_by(id=product_id,tenant_id=auth.tenant_id).first()
    if not product:raise HTTPException(404,"商品不存在")
    row=db.query(ProductFact).filter_by(product_id=product_id,tenant_id=auth.tenant_id,fact_key=payload.fact_key).first()
    if not row: row=ProductFact(tenant_id=auth.tenant_id,product_id=product_id,fact_key=payload.fact_key,label=payload.label);db.add(row)
    if row.value and row.value != payload.value: row.conflict_values=list(dict.fromkeys([*row.conflict_values,row.value,payload.value]));row.status="conflict"
    row.value=payload.value;row.label=payload.label;row.source_type=payload.source_type;row.source_ref=payload.source_ref;row.confidence=1.0
    db.commit();db.refresh(row);return row

@router.post("/products/{product_id}/facts/{fact_id}/confirm")
def confirm_fact(product_id:int,fact_id:int,value:Optional[str]=None,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    row=db.query(ProductFact).filter_by(id=fact_id,product_id=product_id,tenant_id=auth.tenant_id).first()
    if not row:raise HTTPException(404,"事实不存在")
    if value is not None: row.value=value
    row.status="confirmed";row.conflict_values=[];row.confirmed_by=auth.user_id;row.confirmed_at=datetime.utcnow();db.commit();db.refresh(row);return row

def _snapshot_data(project_id:int,db:Session,tenant_id:str)->dict:
    project=db.query(CreativeProject).filter_by(id=project_id,tenant_id=tenant_id).first()
    modules=db.query(StoryboardModule).filter_by(project_id=project_id,tenant_id=tenant_id).order_by(StoryboardModule.sort_order).all()
    node_ids=[m.final_node_id or m.preview_node_id for m in modules if m.final_node_id or m.preview_node_id]
    nodes={n.id:n for n in db.query(CanvasNode).filter(CanvasNode.id.in_(node_ids)).all()} if node_ids else {}
    return {"project":{"name":project.name,"brief":project.brief,"platform":project.platform},"modules":[{"id":m.id,"sort_order":m.sort_order,"title":m.title,"objective":m.objective,"content_guidance":m.content_guidance,"visual_direction":m.visual_direction,"node_id":m.final_node_id or m.preview_node_id,"image_url":(nodes.get(m.final_node_id or m.preview_node_id).data.get("image_url") if nodes.get(m.final_node_id or m.preview_node_id) else "")} for m in modules]}

def _diff(previous:dict,current:dict)->dict:
    old={str(m["id"]):m for m in previous.get("modules",[])};new={str(m["id"]):m for m in current.get("modules",[])};changes=[]
    for key in sorted(set(old)|set(new)):
        if key not in old:changes.append({"module_id":key,"type":"added","after":new[key]})
        elif key not in new:changes.append({"module_id":key,"type":"removed","before":old[key]})
        else:
            fields={f:{"before":old[key].get(f),"after":new[key].get(f)} for f in ("title","objective","content_guidance","visual_direction","image_url") if old[key].get(f)!=new[key].get(f)}
            if fields:changes.append({"module_id":key,"type":"changed","fields":fields})
    return {"change_count":len(changes),"changes":changes}

def create_project_snapshot(project_id:int,trigger:str,db:Session,auth:AuthContext)->ProjectSnapshot:
    rows=db.query(ProjectSnapshot).filter_by(project_id=project_id,tenant_id=auth.tenant_id).order_by(ProjectSnapshot.version.desc()).all();current=_snapshot_data(project_id,db,auth.tenant_id);previous=rows[0].snapshot if rows else {}
    row=ProjectSnapshot(tenant_id=auth.tenant_id,project_id=project_id,version=(rows[0].version+1 if rows else 1),trigger=trigger,snapshot=current,diff_from_previous=_diff(previous,current),created_by=auth.user_id);db.add(row);db.flush();return row

@router.get("/projects/{project_id}/snapshots")
def snapshots(project_id:int,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    rows=db.query(ProjectSnapshot).filter_by(project_id=project_id,tenant_id=auth.tenant_id).order_by(ProjectSnapshot.version.desc()).all()
    return [{"id":r.id,"version":r.version,"trigger":r.trigger,"diff":r.diff_from_previous,"snapshot":r.snapshot,"created_at":r.created_at} for r in rows]

@router.post("/projects/{project_id}/snapshots/compare")
def compare_snapshots(project_id:int,payload:SnapshotCompare,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    rows=db.query(ProjectSnapshot).filter(ProjectSnapshot.project_id==project_id,ProjectSnapshot.tenant_id==auth.tenant_id,ProjectSnapshot.version.in_([payload.left_version,payload.right_version])).all()
    by={r.version:r for r in rows}
    if len(by)!=2:raise HTTPException(404,"快照版本不存在")
    return _diff(by[payload.left_version].snapshot,by[payload.right_version].snapshot)

@router.post("/projects/{project_id}/snapshots/{version}/restore")
def restore_snapshot(project_id:int,version:int,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    project=db.query(CreativeProject).filter_by(id=project_id,tenant_id=auth.tenant_id).first();source=db.query(ProjectSnapshot).filter_by(project_id=project_id,tenant_id=auth.tenant_id,version=version).first()
    if not project or not source:raise HTTPException(404,"项目或快照不存在")
    if project.review_status=="finalized":raise HTTPException(409,"定稿项目不可恢复，请复制为新项目")
    db.query(StoryboardModule).filter_by(project_id=project_id,tenant_id=auth.tenant_id).delete()
    for item in source.snapshot.get("modules",[]):
        db.add(StoryboardModule(tenant_id=auth.tenant_id,project_id=project_id,sort_order=item.get("sort_order",0),module_type="restored",title=item.get("title","") ,objective=item.get("objective","") ,content_guidance=item.get("content_guidance","") ,visual_direction=item.get("visual_direction","") ,production_method="manual",required=False,status="approved" if item.get("node_id") else "planned",preview_node_id=item.get("node_id"),final_node_id=item.get("node_id")))
    create_project_snapshot(project_id,f"restore_v{version}",db,auth);db.commit();return {"ok":True,"restored_version":version}

@router.post("/projects/{project_id}/copy")
def copy_project(project_id:int,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    source=db.query(CreativeProject).filter_by(id=project_id,tenant_id=auth.tenant_id).first()
    if not source:raise HTTPException(404,"项目不存在")
    new=CreativeProject(tenant_id=auth.tenant_id,product_id=source.product_id,name=f"{source.name} · 副本",brief=source.brief,platform=source.platform,output_width=source.output_width,output_height=source.output_height);db.add(new);db.flush()
    for m in db.query(StoryboardModule).filter_by(project_id=project_id,tenant_id=auth.tenant_id).order_by(StoryboardModule.sort_order):
        db.add(StoryboardModule(tenant_id=auth.tenant_id,project_id=new.id,sort_order=m.sort_order,module_type=m.module_type,title=m.title,objective=m.objective,content_guidance=m.content_guidance,visual_direction=m.visual_direction,production_method=m.production_method,required=m.required,status="planned"))
    db.commit();db.refresh(new);return new

@router.post("/batches/preview")
async def preview_batch(file:UploadFile=File(...)):
    raw=await file.read();rows=list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))));required=["name"]
    issues=[];seen=set()
    normalized=[]
    for index,row in enumerate(rows,2):
        name=(row.get("name") or row.get("商品名称") or "").strip();sku=(row.get("sku") or row.get("SKU") or "").strip();row_issues=[]
        if not name:row_issues.append("缺少商品名称")
        if sku and sku in seen:row_issues.append("SKU重复")
        if sku:seen.add(sku)
        try: float(row.get("price") or row.get("价格") or 0)
        except ValueError:row_issues.append("价格格式错误")
        normalized.append({"row":index,"sku":sku,"name":name,"issues":row_issues,"raw":row});issues.extend({"row":index,"message":x} for x in row_issues)
    return {"total":len(rows),"valid":sum(not r["issues"] for r in normalized),"invalid":sum(bool(r["issues"]) for r in normalized),"columns":list(rows[0].keys()) if rows else [],"issues":issues,"rows":normalized[:100]}

@router.post("/batches/import")
async def import_batch(file:UploadFile=File(...),name:str=Form("批量SKU生产"),template_id:Optional[int]=Form(None),platform:str=Form("天猫"),enqueue:bool=Form(True),db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    raw=await file.read();text=raw.decode("utf-8-sig");rows=list(csv.DictReader(io.StringIO(text)))
    if not rows:raise HTTPException(400,"CSV没有数据")
    batch=SkuBatch(id=uuid.uuid4().hex,tenant_id=auth.tenant_id,name=name,template_id=template_id,platform=platform,status="queued" if enqueue else "created",total=len(rows),created_by=auth.user_id);db.add(batch);db.flush()
    for index,data in enumerate(rows,1):
        try:
            product=Product(tenant_id=auth.tenant_id,name=(data.get("name") or data.get("商品名称") or data.get("sku") or f"SKU-{index}").strip(),category=(data.get("category") or data.get("品类") or "").strip(),brand_name=(data.get("brand_name") or data.get("品牌") or "").strip(),description=(data.get("description") or data.get("卖点") or "").strip(),target_users=(data.get("target_users") or data.get("目标用户") or "").strip(),ingredients=(data.get("ingredients") or data.get("成分") or "").strip(),usage_method=(data.get("usage_method") or data.get("使用方法") or "").strip(),specifications=(data.get("specifications") or data.get("规格") or "").strip(),price=float(data.get("price") or data.get("价格") or 0),image_urls=[x.strip() for x in (data.get("image_urls") or data.get("商品图片") or "").split("|") if x.strip()]);db.add(product);db.flush()
            if template_id:
                project=apply_template(template_id,DetailPageTemplateApply(product_id=product.id,project_name=f"{product.name} · 批量详情页"),db,auth)
            else:
                project=CreativeProject(tenant_id=auth.tenant_id,product_id=product.id,name=f"{product.name} · 批量详情页",brief="批量SKU生产",platform=platform);db.add(project);db.flush()
            task=None
            if enqueue:
                task=ProductionQueueTask(id=uuid.uuid4().hex,tenant_id=auth.tenant_id,actor_id=auth.user_id,actor_role=auth.role,actor_email=auth.email,tenant_name=auth.tenant_name,task_type="generate_detail_page",payload={"project_id":project.id,"batch_id":batch.id},status="pending",total=1);db.add(task)
            db.add(SkuBatchItem(tenant_id=auth.tenant_id,batch_id=batch.id,row_number=index,sku=(data.get("sku") or data.get("SKU") or ""),product_id=product.id,project_id=project.id,queue_task_id=task.id if task else None,status="queued" if task else "created",raw=data))
        except Exception as exc:
            db.add(SkuBatchItem(tenant_id=auth.tenant_id,batch_id=batch.id,row_number=index,sku=(data.get("sku") or ""),status="failed",error_message=str(exc),raw=data));batch.failed+=1
    db.commit()
    if enqueue:notify_queue()
    return {"id":batch.id,"total":batch.total,"failed":batch.failed,"status":batch.status}

@router.get("/batches")
def batches(db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    rows=db.query(SkuBatch).filter_by(tenant_id=auth.tenant_id).order_by(SkuBatch.created_at.desc()).all();return [{"id":r.id,"name":r.name,"status":r.status,"total":r.total,"completed":r.completed,"failed":r.failed,"created_at":r.created_at} for r in rows]

@router.get("/batches/{batch_id}")
def batch_detail(batch_id:str,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    batch=db.query(SkuBatch).filter_by(id=batch_id,tenant_id=auth.tenant_id).first();items=db.query(SkuBatchItem).filter_by(batch_id=batch_id,tenant_id=auth.tenant_id).order_by(SkuBatchItem.row_number).all()
    if not batch:raise HTTPException(404,"批次不存在")
    return {"id":batch.id,"name":batch.name,"status":batch.status,"total":batch.total,"completed":batch.completed,"failed":batch.failed,"items":[{"id":i.id,"row_number":i.row_number,"sku":i.sku,"product_id":i.product_id,"project_id":i.project_id,"queue_task_id":i.queue_task_id,"status":i.status,"error_message":i.error_message} for i in items]}

@router.post("/batches/{batch_id}/items/{item_id}/retry")
def retry_batch_item(batch_id:str,item_id:int,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    item=db.query(SkuBatchItem).filter_by(id=item_id,batch_id=batch_id,tenant_id=auth.tenant_id).first()
    if not item or not item.project_id:raise HTTPException(404,"批次商品不存在")
    task=ProductionQueueTask(id=uuid.uuid4().hex,tenant_id=auth.tenant_id,actor_id=auth.user_id,actor_role=auth.role,actor_email=auth.email,tenant_name=auth.tenant_name,task_type="generate_detail_page",payload={"project_id":item.project_id,"batch_id":batch_id},status="pending");db.add(task);item.queue_task_id=task.id;item.status="queued";item.error_message="";db.commit();notify_queue();return {"task_id":task.id}

@router.get("/queue")
def queue(db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    rows=db.query(ProductionQueueTask).filter_by(tenant_id=auth.tenant_id).order_by(ProductionQueueTask.created_at.desc()).limit(100).all();return [{"id":r.id,"task_type":r.task_type,"status":r.status,"progress":r.progress,"total":r.total,"attempt_count":r.attempt_count,"error_message":r.error_message,"payload":r.payload,"created_at":r.created_at} for r in rows]

@router.post("/queue/{task_id}/cancel")
def cancel_queue(task_id:str,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    row=db.query(ProductionQueueTask).filter_by(id=task_id,tenant_id=auth.tenant_id).first()
    if not row:raise HTTPException(404,"任务不存在")
    row.cancel_requested=True
    if row.status=="pending":row.status="cancelled";row.finished_at=datetime.utcnow()
    db.commit();return {"status":row.status}

@router.get("/dashboard")
def production_dashboard(db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    tasks=db.query(ProductionQueueTask).filter_by(tenant_id=auth.tenant_id).all();reviews=db.query(ProjectReview).filter_by(tenant_id=auth.tenant_id).all();projects=db.query(CreativeProject).filter_by(tenant_id=auth.tenant_id).all();batches=db.query(SkuBatch).filter_by(tenant_id=auth.tenant_id).all()
    durations=[(t.finished_at-t.started_at).total_seconds() for t in tasks if t.started_at and t.finished_at and t.status=="completed"]
    finalized=[p for p in projects if p.review_status=="finalized"]
    first_drafts=[];final_times=[]
    for project in projects:
        first=db.query(CreativeGeneration).filter_by(project_id=project.id,tenant_id=auth.tenant_id,status="completed").order_by(CreativeGeneration.created_at).first()
        if first:first_drafts.append((first.created_at-project.created_at).total_seconds())
        final_review=db.query(ProjectReview).filter_by(project_id=project.id,tenant_id=auth.tenant_id,to_status="finalized").order_by(ProjectReview.created_at.desc()).first()
        if final_review:final_times.append((final_review.created_at-project.created_at).total_seconds())
    return {"queue":{"pending":sum(t.status=="pending" for t in tasks),"running":sum(t.status=="running" for t in tasks),"completed":sum(t.status=="completed" for t in tasks),"failed":sum(t.status=="failed" for t in tasks)},"throughput":{"products":db.query(Product).filter_by(tenant_id=auth.tenant_id).count(),"projects":len(projects),"batches":len(batches),"finalized":len(finalized)},"efficiency":{"average_production_seconds":round(sum(durations)/len(durations)) if durations else 0,"average_time_to_first_reviewable_seconds":round(sum(first_drafts)/len(first_drafts)) if first_drafts else 0,"average_time_to_final_seconds":round(sum(final_times)/len(final_times)) if final_times else 0,"average_review_rounds":round(sum(p.review_round for p in finalized)/len(finalized),1) if finalized else 0,"first_pass_rate":round(sum(p.review_round<=1 for p in finalized)/len(finalized)*100,1) if finalized else 0},"recent_batches":[{"id":b.id,"name":b.name,"status":b.status,"total":b.total,"completed":b.completed,"failed":b.failed} for b in sorted(batches,key=lambda x:x.created_at,reverse=True)[:10]]}
