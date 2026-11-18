"""Show the actual on-board localization and model input crops."""
import time,os,json,image,sensor
_labels=[None,None]
_label_ids=[None,None]

def text_row(canvas,root,index,y):
    slot=y//32
    if _labels[slot] is None:_labels[slot]=image.Image(240,32,sensor.RGB565)
    if _label_ids[slot]!=index:
        with open(root+'/roi-labels.rgb565','rb') as f:
            f.seek(index*240*32*2);f.readinto(_labels[slot].bytearray())
        _label_ids[slot]=index
    canvas.draw_image(_labels[slot],0,y)

def draw(canvas,root,box,points,eyes,mouth,age_ms,show_inputs=False,source_width=240):
    scale=canvas.width()/source_width
    if box:box=tuple(int(v*scale) for v in box)
    if points:points=[(p[0]*scale,p[1]*scale) for p in points]
    if box:canvas.draw_rectangle(*box,color=(255,220,40),thickness=1)
    if points:
        for i,(x,y) in enumerate(points):
            canvas.draw_cross(int(x),int(y),color=(255,70,60) if i<2 else (60,220,255),size=4,thickness=1)
    for roi in eyes.rois:
        if roi:canvas.draw_rectangle(*(int(v*scale) for v in roi),color=(255,70,60),thickness=1)
    # Also draw the requested mouth context when it extends beyond the frame.
    # A missing valid ROI must not make the locator box disappear.
    if points:
        a,b=points[3],points[4];span=((a[0]-b[0])**2+(a[1]-b[1])**2)**.5
        x0=max(0,int(min(a[0],b[0])-.2*span));x1=min(canvas.width()-1,int(max(a[0],b[0])+.2*span))
        y0=max(0,int(min(a[1],b[1])-.35*span));y1=min(canvas.height()-1,int(max(a[1],b[1])+.55*span))
        if x1>x0 and y1>y0:canvas.draw_rectangle(x0,y0,x1-x0,y1-y0,color=(60,220,255),thickness=2)
    states=[(1 if eyes.closed[i] else 0) if eyes.known[i] and box else 2 for i in range(2)]
    text_row(canvas,root,states[0]*3+states[1],0)
    state=13 if not box else (12 if mouth.status=='mouth_out_of_frame' else (9+int(mouth.raw>=.65) if mouth.known else 11))
    if box and hasattr(mouth,'label_state'):
        state=12 if mouth.status=='mouth_out_of_frame' else (9,10,11,14)[mouth.label_state]
        for p in mouth.points:
            canvas.draw_circle(int(p[0]*scale),int(p[1]*scale),1,color=(94,225,195),fill=True)
    text_row(canvas,root,state,32)
    if show_inputs:
        canvas.draw_rectangle(0,66,240,67,color=(15,34,39),fill=True)
        for i,p in enumerate(eyes.patches):canvas.draw_image(p,4+i*55,68,x_scale=48/p.width(),y_scale=48/p.height())
        canvas.draw_image(mouth.gray,150,68,x_scale=.64,y_scale=.64)

def save_if_requested(root,img,det,eyes,mouth,landmarks,box,age_ms):
    try:os.stat(root+'/roi-snapshot.flag')
    except OSError:return
    os.remove(root+'/roi-snapshot.flag')
    # Exact pixel buffers, no host-side reconstruction of model preprocessing.
    for name,im in [('roi-camera',img),('roi-face-input',det.canvas),('roi-mouth-input',mouth.gray)]+[
            ('roi-eye-'+str(i),p) for i,p in enumerate(eyes.patches)]:
        with open(root+'/'+name+'.raw','wb') as f:f.write(im.bytearray())
    with open(root+'/roi-snapshot.json','w') as f:
        json.dump({'ms':time.ticks_ms(),'box':box,'unclipped_box':det.unclipped_box,
            'points':landmarks,'eye_rois':eyes.rois,'mouth_roi':mouth.roi,
            'age_ms':age_ms,'eye_raw':eyes.raw,'mouth_raw':mouth.raw,'mouth_status':mouth.status,
            'camera':[img.width(),img.height()],'camera_bytes':len(img.bytearray())},f)
