"""Calibration-free visibility checks shared by mouth inference adapters."""
import math

def mouth_region(landmarks,width,height):
    if not landmarks or len(landmarks)<5:return None,'missing_landmarks'
    a,b=landmarks[3],landmarks[4]
    dx,dy=b[0]-a[0],b[1]-a[1]
    span=math.sqrt(dx*dx+dy*dy)
    if span<12:return None,'mouth_too_small'
    cx,cy=(a[0]+b[0])/2,(a[1]+b[1])/2
    x1=min(a[0],b[0])-.20*span
    x2=max(a[0],b[0])+.20*span
    y1=min(a[1],b[1])-.35*span
    y2=max(a[1],b[1])+.55*span
    if x1<0 or y1<0 or x2>width or y2>height:return None,'mouth_out_of_frame'
    return (int(x1),int(y1),max(1,int(x2-x1)),max(1,int(y2-y1))),'visible'

def face_sampling(box,unclipped,width,height,size):
    x,y,w,h=unclipped if unclipped is not None else box
    if w<1 or h<1 or w>width*3 or h>height*3:return None
    left=max(0,int(math.floor(x)));top=max(0,int(math.floor(y)))
    right=min(width,int(math.ceil(x+w)));bottom=min(height,int(math.ceil(y+h)))
    if right<=left or bottom<=top:return None
    sx,sy=size/w,size/h
    return ((left,top,right-left,bottom-top),int(round((left-x)*sx)),int(round((top-y)*sy)),sx,sy)
