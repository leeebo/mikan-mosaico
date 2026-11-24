"""Single-face YuNet decoder for the public ESP-DL raw-output API.

Model and decoding reference: OpenCV Zoo / OpenCV FaceDetectorYN, MIT/Apache-2.0.
This application returns the highest-confidence face for the single-person MVP.
"""
import image,sensor,espdl,math,struct,time

def value(tensor,index):
    _,shape,dtype,exponent,raw=tensor
    if dtype==3:
        n=raw[index]
        if n>=128:n-=256
    elif dtype==5:n=struct.unpack_from('<h',raw,index*2)[0]
    else:raise ValueError('Unsupported YuNet output dtype: '+str(dtype))
    return n*(2.**exponent)

def best_anchor(outputs,threshold):
    """Scan quantized scores without 1,050 per-anchor float conversions.

    Exponents are constant within each output. Only record-breaking integer
    products need float conversion. Preserve float32 ties: different int16
    products can round to the same float, and the first anchor must win.
    """
    best=None;best_score=threshold
    for stride in (8,16,32):
        cls=outputs['cls_'+str(stride)];obj=outputs['obj_'+str(stride)]
        cols=160//stride;count=cols*cols
        if cls[2] not in (3,5) or obj[2] not in (3,5):
            raise ValueError('Unsupported score dtype')
        cs=struct.unpack('<%d%s'%(count,'b' if cls[2]==3 else 'h'),cls[4])
        ob=struct.unpack('<%d%s'%(count,'b' if obj[2]==3 else 'h'),obj[4])
        cs_scale=2.**cls[3];ob_scale=2.**obj[3]
        peak=cs[0]*ob[0];index=0;score=(cs[0]*cs_scale)*(ob[0]*ob_scale)
        for i in range(1,count):
            product=cs[i]*ob[i]
            if product>peak:
                peak=product
                candidate=(cs[i]*cs_scale)*(ob[i]*ob_scale)
                if candidate>score:score=candidate;index=i
        if score>best_score:best_score=score;best=(stride,index,cols)
    return best,best_score

class FaceDetector:
    def __init__(self,root,score=.65,model_name='yunet-160-s31.espdl'):
        self.model=espdl.Model(root+'/'+model_name,mean=(0,0,0),std=(1,1,1),rgb_swap=True,letterbox=False)
        self.canvas=image.Image(160,160,sensor.RGB565)
        self.threshold=score*score
        self.elapsed_us=0
        self.coverage=0.
        self.unclipped_box=None

    def detect(self,img):
        started=time.ticks_us()
        w,h=img.width(),img.height()
        scale=min(160/w,160/h)
        px,py=int((160-w*scale)/2),int((160-h*scale)/2)
        self.canvas.draw_rectangle(0,0,160,160,color=(0,0,0),fill=True)
        self.canvas.draw_image(img,px,py,x_scale=scale,y_scale=scale,hint=image.BILINEAR)
        outputs=self.model.predict(self.canvas)
        best,best_score=best_anchor(outputs,self.threshold)
        self.elapsed_us=time.ticks_diff(time.ticks_us(),started)
        if best is None:
            self.coverage=0.
            self.unclipped_box=None
            return []
        stride,i,cols=best
        row,col=i//cols,i%cols
        bbox=outputs['bbox_'+str(stride)]
        kps=outputs['kps_'+str(stride)]
        cx=(col+value(bbox,i*4))*stride
        cy=(row+value(bbox,i*4+1))*stride
        bw=math.exp(min(10.,value(bbox,i*4+2)))*stride
        bh=math.exp(min(10.,value(bbox,i*4+3)))*stride
        self.unclipped_box=((cx-bw/2-px)/scale,(cy-bh/2-py)/scale,bw/scale,bh/scale)
        x1=max(0.,(cx-bw/2-px)/scale);y1=max(0.,(cy-bh/2-py)/scale)
        x2=min(w,(cx+bw/2-px)/scale);y2=min(h,(cy+bh/2-py)/scale)
        if x2<=x1 or y2<=y1:return []
        self.coverage=min(1.,(x2-x1)*(y2-y1)*scale*scale/(bw*bh))
        points=[((value(kps,i*10+n*2)+col)*stride-px)/scale for n in range(5)]
        points=[(points[n],((value(kps,i*10+n*2+1)+row)*stride-py)/scale) for n in range(5)]
        return [(x1,y1,x2-x1,y2-y1,math.sqrt(best_score),0,points)]

    def deinit(self):self.model.deinit()
