"""Deterministic image post-processing: regional masks, hard locks and similarity."""
from __future__ import annotations

import uuid
from io import BytesIO
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter
from app.config import get_settings
from app.services.storage import get_storage


def local_path(url:str)->Path|None:
    return get_storage().local_path(url)


def _save(image:Image.Image,project_id:int,prefix:str)->str:
    name=f"{prefix}-{uuid.uuid4().hex}.png";output=BytesIO();image.save(output,"PNG")
    return get_storage().save_bytes(output.getvalue(),name,f"creative/{project_id}")


def regional_composite(original_url:str,edited_url:str,region:dict,project_id:int,feather:int=18)->str:
    original_path,edited_path=local_path(original_url),local_path(edited_url)
    if not original_path or not edited_path:raise ValueError("局部合成要求原图和修改图均已保存到本地存储")
    original=Image.open(original_path).convert("RGB");edited=Image.open(edited_path).convert("RGB").resize(original.size,Image.Resampling.LANCZOS)
    regions=list(region.get("regions") or [region]);mask=Image.new("L",original.size,0)
    for item in regions:
        x=int(float(item.get("x",0))*original.width);y=int(float(item.get("y",0))*original.height);w=max(1,int(float(item.get("width",1))*original.width));h=max(1,int(float(item.get("height",1))*original.height));mask.paste(255,(x,y,min(original.width,x+w),min(original.height,y+h)))
    mask=mask.filter(ImageFilter.GaussianBlur(feather))
    return _save(Image.composite(edited,original,mask),project_id,"regional-edit")


def product_foreground_mask(source:Image.Image,tolerance:float=42)->Image.Image:
    rgb=np.asarray(source.convert("RGB"),dtype=np.float32);h,w,_=rgb.shape
    border=np.concatenate([rgb[0],rgb[-1],rgb[:,0],rgb[:,-1]],axis=0);background=np.median(border,axis=0)
    distance=np.sqrt(((rgb-background)**2).sum(axis=2));alpha=np.clip((distance-tolerance)*8,0,255).astype(np.uint8)
    return Image.fromarray(alpha,"L").filter(ImageFilter.MedianFilter(5)).filter(ImageFilter.GaussianBlur(1.5))


def hard_lock_product(source_url:str,generated_url:str,project_id:int,protection:dict|None=None)->str:
    source_path,generated_path=local_path(source_url),local_path(generated_url)
    if not source_path or not generated_path:raise ValueError("商品硬锁定需要本地商品基准图")
    generated=Image.open(generated_path).convert("RGB");source=Image.open(source_path).convert("RGB")
    protection=protection or {};position=protection.get("position") or {};scale=float(position.get("scale",.72));fitted=source.copy();fitted.thumbnail((int(generated.width*scale),int(generated.height*scale)),Image.Resampling.LANCZOS)
    mask_path=local_path(str(protection.get("mask_url") or ""));mask=Image.open(mask_path).convert("L").resize(fitted.size,Image.Resampling.LANCZOS) if mask_path else product_foreground_mask(fitted)
    if protection.get("preserve_shadow") or protection.get("preserve_reflection"):
        radius=21 if protection.get("preserve_shadow") else 11;expanded=mask.filter(ImageFilter.MaxFilter(radius));offset=round(fitted.height*(.04 if protection.get("preserve_shadow") else .08));shifted=Image.new("L",mask.size,0);shifted.paste(expanded,(0,offset));mask=Image.fromarray(np.maximum(np.asarray(mask),np.asarray(shifted)).astype(np.uint8),"L")
    rotation=float(position.get("rotation",0))
    if rotation:fitted=fitted.rotate(rotation,expand=True,resample=Image.Resampling.BICUBIC);mask=mask.rotate(rotation,expand=True,resample=Image.Resampling.BICUBIC)
    x=round(float(position.get("x",.5))*generated.width-fitted.width/2);y=round(float(position.get("y",.5))*generated.height-fitted.height/2)
    generated.paste(fitted,(x,y),mask)
    return _save(generated,project_id,"product-locked")


def restore_protected_regions(source_url:str,generated_url:str,regions:list[dict],project_id:int)->str:
    source_path,generated_path=local_path(source_url),local_path(generated_url)
    if not source_path or not generated_path:raise ValueError("保护区恢复需要本地图片")
    source=Image.open(source_path).convert("RGB");generated=Image.open(generated_path).convert("RGB");source=source.resize(generated.size,Image.Resampling.LANCZOS);mask=Image.new("L",generated.size,0)
    for region in regions:
        x=int(float(region.get("x",0))*generated.width);y=int(float(region.get("y",0))*generated.height);w=int(float(region.get("width",0))*generated.width);h=int(float(region.get("height",0))*generated.height);mask.paste(255,(x,y,x+w,y+h))
    mask=mask.filter(ImageFilter.GaussianBlur(2));return _save(Image.composite(source,generated,mask),project_id,"protected-text")


def perceptual_hash(url:str,size:int=16)->int|None:
    path=local_path(url)
    if not path:return None
    image=Image.open(path).convert("L").resize((size,size),Image.Resampling.LANCZOS);pixels=np.asarray(image);return int(''.join('1' if value>=pixels.mean() else '0' for value in pixels.flat),2)


def hamming_distance(value:int)->int:
    """Count set bits on every supported Python version (including 3.9)."""
    return bin(value).count("1")


def similarity(left_url:str,right_url:str)->float|None:
    left,right=perceptual_hash(left_url),perceptual_hash(right_url)
    if left is None or right is None:return None
    return round(1-hamming_distance(left^right)/256,4)


def duplicate_report(urls:list[str],threshold:float=.92)->dict:
    pairs=[]
    for i in range(len(urls)):
        for j in range(i+1,len(urls)):
            score=similarity(urls[i],urls[j])
            if score is not None:pairs.append({"left":i,"right":j,"similarity":score,"duplicate":score>=threshold})
    duplicates=[pair for pair in pairs if pair["duplicate"]]
    return {"threshold":threshold,"pairs":pairs,"duplicates":duplicates,"passed":not duplicates}


def contact_sheet(urls:list[str],project_id:int,columns:int=4,thumb_width:int=320)->str:
    images=[]
    for url in urls:
        path=local_path(url)
        if path:
            image=Image.open(path).convert("RGB");height=max(1,round(image.height*thumb_width/image.width));images.append(image.resize((thumb_width,height),Image.Resampling.LANCZOS))
    if not images:raise ValueError("没有可用于整套一致性检查的本地图片")
    cell_height=max(image.height for image in images);rows=(len(images)+columns-1)//columns;sheet=Image.new("RGB",(columns*thumb_width,rows*cell_height),"white")
    for index,image in enumerate(images):sheet.paste(image,((index%columns)*thumb_width,(index//columns)*cell_height))
    return _save(sheet,project_id,"suite-contact-sheet")
