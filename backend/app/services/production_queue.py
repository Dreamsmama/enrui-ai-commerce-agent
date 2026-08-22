"""PostgreSQL-persistent queue coordinated by Redis wakeups and locks."""
from __future__ import annotations
from datetime import datetime
import threading
import time

from app.auth import AuthContext
from app.database import SessionLocal
from app.models import ProductionQueueTask, SkuBatch, SkuBatchItem, StoryboardModule
from app.schemas import CreativeGenerateRequest
from app.services.redis_client import notify_queue, task_lock, wait_for_queue

_thread: threading.Thread | None = None
_stop = threading.Event()

def _run_task(task_id: str) -> None:
    from app.api.creative import generate_plan, generate_variants
    db = SessionLocal()
    try:
        task = db.query(ProductionQueueTask).filter_by(id=task_id).first()
        if not task or task.cancel_requested: return
        task.status="running"; task.started_at=datetime.utcnow(); task.attempt_count += 1; db.commit()
        auth=AuthContext(task.actor_id,task.tenant_id,task.actor_role,task.actor_email,task.tenant_name)
        if task.task_type == "generate_detail_page":
            project_id=int(task.payload["project_id"])
            plan=generate_plan(project_id,db,auth)
            modules=db.query(StoryboardModule).filter_by(project_id=project_id,tenant_id=task.tenant_id).order_by(StoryboardModule.sort_order).all()
            task.total=len(modules); db.commit()
            generated=[]
            for index,module in enumerate(modules):
                db.refresh(task)
                if task.cancel_requested:
                    task.status="cancelled"; task.finished_at=datetime.utcnow(); db.commit(); return
                payload=CreativeGenerateRequest(prompt=f"{module.objective}。{module.content_guidance}。{module.visual_direction}",action=f"详情页·{module.title}",selected_node_ids=[],auto_select_materials=True,module_id=module.id,count=1)
                generate_variants(project_id,payload,db,auth); generated.append(module.id); task.progress=index+1; db.commit()
            task.result={"project_id":project_id,"generated_module_ids":generated}; task.status="completed"
        else:
            raise ValueError(f"未知任务类型：{task.task_type}")
        task.finished_at=datetime.utcnow(); db.commit()
        item=db.query(SkuBatchItem).filter(SkuBatchItem.queue_task_id==task.id).first()
        if item:
            item.status="completed"; batch=db.query(SkuBatch).filter_by(id=item.batch_id).first(); batch.completed += 1
            if batch.completed+batch.failed >= batch.total: batch.status="completed_with_errors" if batch.failed else "completed"
            db.commit()
    except Exception as exc:
        db.rollback(); task=db.query(ProductionQueueTask).filter_by(id=task_id).first()
        if task:
            task.error_message=str(getattr(exc,"detail",exc)); task.finished_at=datetime.utcnow()
            task.status="pending" if task.attempt_count < task.max_attempts and not task.cancel_requested else "failed"
            item=db.query(SkuBatchItem).filter(SkuBatchItem.queue_task_id==task.id).first()
            if item and task.status=="failed":
                item.status="failed"; item.error_message=task.error_message; batch=db.query(SkuBatch).filter_by(id=item.batch_id).first(); batch.failed += 1
            db.commit()
    finally: db.close()

def _loop() -> None:
    while not _stop.is_set():
        db=SessionLocal()
        try:
            task=db.query(ProductionQueueTask).filter(ProductionQueueTask.status=="pending",ProductionQueueTask.cancel_requested.is_(False)).order_by(ProductionQueueTask.priority.desc(),ProductionQueueTask.created_at).first()
            task_id=task.id if task else None
        finally: db.close()
        if task_id:
            lock=task_lock(task_id)
            if lock is None:_run_task(task_id)
            elif lock.acquire(blocking=False):
                try:_run_task(task_id)
                finally:
                    try:lock.release()
                    except Exception:pass
            else:wait_for_queue(1)
        elif not _stop.is_set():wait_for_queue(1)

def start_worker() -> None:
    global _thread
    db=SessionLocal()
    try:
        for task in db.query(ProductionQueueTask).filter(ProductionQueueTask.status=="running").all(): task.status="pending"; task.error_message="服务重启，任务已恢复排队"
        db.commit()
    finally: db.close()
    if _thread and _thread.is_alive(): return
    _stop.clear(); _thread=threading.Thread(target=_loop,name="production-queue",daemon=True); _thread.start(); notify_queue()

def stop_worker() -> None:
    _stop.set(); notify_queue()
