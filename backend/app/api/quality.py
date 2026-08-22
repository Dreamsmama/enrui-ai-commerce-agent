"""Quality rules, human corrections, regression samples and review workbench."""
from __future__ import annotations
from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy.orm import Session
from app.auth import AuthContext,current_auth
from app.database import get_db
from app.models import ApprovalIssue,CanvasNode,CreativeProject,Product,QualityFeedback,QualityRuleSet,QualityRuleVersion,RegressionSample,StoryboardModule

router=APIRouter(prefix="/quality",tags=["quality"])

DEFAULTS={
 "general":{"thresholds":{"hero":85,"product_showcase":82,"texture":75,"ingredient":75,"scenario":72,"information":80},"rules":["商品结构与数量准确","Logo与包装文字准确","单屏只表达一个核心卖点"]},
 "气垫":{"rules":["镜面包装不变形","粉膏色泽与网面结构真实"]},"口红":{"rules":["膏体形状与色号准确","试色不得与标准色明显偏离"]},"精华":{"rules":["瓶身透明度、滴管和液体颜色准确"]},"套装":{"rules":["商品数量、相对位置和包装组合准确"]}}

def _rules(category:str)->dict:
    base=DEFAULTS["general"];specific=next((value for key,value in DEFAULTS.items() if key!="general" and key in (category or "")),{})
    return {"thresholds":{**base["thresholds"],**specific.get("thresholds",{})},"rules":[*base["rules"],*specific.get("rules",[])]}

@router.get("/rules/{category}")
def get_rules(category:str,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    row=db.query(QualityRuleSet).filter_by(tenant_id=auth.tenant_id,category=category).first();return {"category":category,**(_rules(category) if not row else {"thresholds":row.thresholds,"rules":row.rules}),"version":row.version if row else 1}

@router.put("/rules/{category}")
def save_rules(category:str,payload:dict,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    row=db.query(QualityRuleSet).filter_by(tenant_id=auth.tenant_id,category=category).first()
    if not row:row=QualityRuleSet(tenant_id=auth.tenant_id,category=category);db.add(row)
    else:row.version+=1
    row.thresholds=dict(payload.get("thresholds") or {});row.rules=list(payload.get("rules") or []);db.flush();db.add(QualityRuleVersion(tenant_id=auth.tenant_id,rule_set_id=row.id,version=row.version,snapshot={"thresholds":row.thresholds,"rules":row.rules},created_by=auth.user_id));db.commit();db.refresh(row);return row

@router.get("/rules/{category}/versions")
def rule_versions(category:str,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    row=db.query(QualityRuleSet).filter_by(tenant_id=auth.tenant_id,category=category).first()
    if not row:return []
    return db.query(QualityRuleVersion).filter_by(rule_set_id=row.id,tenant_id=auth.tenant_id).order_by(QualityRuleVersion.version.desc()).all()

@router.post("/rules/{category}/versions/{version}/rollback")
def rollback_rules(category:str,version:int,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    row=db.query(QualityRuleSet).filter_by(tenant_id=auth.tenant_id,category=category).first();saved=db.query(QualityRuleVersion).filter_by(rule_set_id=row.id if row else 0,version=version,tenant_id=auth.tenant_id).first()
    if not row or not saved:raise HTTPException(404,"规则版本不存在")
    row.version+=1;row.thresholds=saved.snapshot.get("thresholds",{});row.rules=saved.snapshot.get("rules",[]);db.flush();db.add(QualityRuleVersion(tenant_id=auth.tenant_id,rule_set_id=row.id,version=row.version,snapshot=saved.snapshot,created_by=auth.user_id));db.commit();return row

@router.post("/projects/{project_id}/nodes/{node_id}/feedback")
def quality_feedback(project_id:int,node_id:str,payload:dict,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    node=db.query(CanvasNode).filter_by(id=node_id,project_id=project_id,tenant_id=auth.tenant_id).first()
    if not node:raise HTTPException(404,"图片版本不存在")
    kind=str(payload.get("feedback_type") or "false_positive")
    if kind not in {"false_positive","false_negative","wrong_field","wrong_score"}:raise HTTPException(400,"质检纠错类型无效")
    row=QualityFeedback(tenant_id=auth.tenant_id,project_id=project_id,node_id=node_id,feedback_type=kind,field=str(payload.get("field") or ""),note=str(payload.get("note") or ""),actor_id=auth.user_id);db.add(row);node.data={**node.data,"quality_feedback_count":int(node.data.get("quality_feedback_count",0))+1};db.commit();db.refresh(row);return row

@router.get("/regression-samples")
def samples(category:str="",db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    query=db.query(RegressionSample).filter_by(tenant_id=auth.tenant_id)
    if category:query=query.filter_by(category=category)
    return query.order_by(RegressionSample.created_at.desc()).all()

@router.post("/regression-samples")
def create_sample(payload:dict,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    row=RegressionSample(tenant_id=auth.tenant_id,category=str(payload.get("category") or "general"),case_type=str(payload.get("case_type") or "hero"),name=str(payload.get("name") or "未命名基准样本"),input_urls=list(payload.get("input_urls") or []),accepted_url=str(payload.get("accepted_url") or ""),failure_urls=list(payload.get("failure_urls") or []));db.add(row);db.commit();db.refresh(row);return row

@router.put("/regression-samples/{sample_id}")
def update_sample(sample_id:int,payload:dict,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    row=db.query(RegressionSample).filter_by(id=sample_id,tenant_id=auth.tenant_id).first()
    if not row:raise HTTPException(404,"回归样本不存在")
    for key in ["category","case_type","name","input_urls","accepted_url","failure_urls","enabled"]:
        if key in payload:setattr(row,key,payload[key])
    db.commit();db.refresh(row);return row

@router.delete("/regression-samples/{sample_id}")
def delete_sample(sample_id:int,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    row=db.query(RegressionSample).filter_by(id=sample_id,tenant_id=auth.tenant_id).first()
    if not row:raise HTTPException(404,"回归样本不存在")
    db.delete(row);db.commit();return {"ok":True}

@router.get("/projects/{project_id}/merged-comments")
def merged_comments(project_id:int,db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    rows=db.query(ApprovalIssue).filter_by(project_id=project_id,tenant_id=auth.tenant_id,status="open").all();groups={}
    for row in rows:
        key=(row.module_id,row.issue_type,row.action);group=groups.setdefault(key,{"module_id":row.module_id,"issue_type":row.issue_type,"action":row.action,"severity":row.severity,"issue_ids":[],"notes":[],"regions":[]});group["issue_ids"].append(row.id)
        if row.note and row.note not in group["notes"]:group["notes"].append(row.note)
        if row.region:group["regions"].append(row.region)
        if row.severity=="high":group["severity"]="high"
    return {"original_count":len(rows),"merged_count":len(groups),"items":list(groups.values())}

@router.get("/review-todos")
def review_todos(db:Session=Depends(get_db),auth:AuthContext=Depends(current_auth)):
    projects=db.query(CreativeProject).filter(CreativeProject.tenant_id==auth.tenant_id,CreativeProject.review_status.in_(["submitted","operational_approved","changes_requested"])).all();items=[]
    for project in projects:
        open_count=db.query(ApprovalIssue).filter_by(project_id=project.id,tenant_id=auth.tenant_id,status="open").count();items.append({"project_id":project.id,"name":project.name,"status":project.review_status,"open_issues":open_count,"action":"审核" if project.review_status=="submitted" else "定稿" if project.review_status=="operational_approved" else "修改"})
    return {"count":len(items),"items":items}
