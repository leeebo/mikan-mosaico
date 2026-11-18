"""Fixed PFLD-lite lip geometry; on-board and without personal calibration."""
import image,sensor,espdl,time,math
from face_landmarks import value as tensor_value
from mouth_geometry import face_sampling

class LipTracker:
    def __init__(self,root,model_name='pfld-lips-mixed-minmax.espdl'):
        self.model=espdl.Model(root+'/'+model_name,mean=(0,0,0),
            std=(255,255,255),rgb_swap=True,letterbox=False)
        self.patch=image.Image(112,112,sensor.RGB565)
        self.gray=self.patch # Existing debug thumbnail accepts either format.
        self.raw=self.value=0.
        self.aperture_open=False
        self.aperture_streak=0
        self.known=False;self.status='initializing';self.roi=None
        self.elapsed_us=0;self.points=[]
        self.label_state=2
        self.last_known=self.last_update=time.ticks_ms()

    def unknown(self,reason='missing_face'):
        self.known=False;self.status=reason
        self.label_state=2
        now=time.ticks_ms();dt=max(1,min(500,time.ticks_diff(now,self.last_update)))
        self.aperture_streak=0
        if time.ticks_diff(now,self.last_known)>200:
            self.aperture_open=False
            self.value*=math.exp(-dt/150.)
        self.last_update=now
        return self.value

    def _aperture_target(self, ratio):
        # A definite opening acts on this sample. Smaller openings need a
        # second sample, above the separate closing threshold.
        if self.aperture_open:
            if ratio <= .043:
                self.aperture_open=False
                self.aperture_streak=0
            elif ratio < .048:
                self.aperture_streak+=1
                if self.aperture_streak>=2:
                    self.aperture_open=False
                    self.aperture_streak=0
            else:
                self.aperture_streak=0
        elif ratio >= .072:
            self.aperture_open=True
            self.aperture_streak=0
        elif ratio >= .052:
            self.aperture_streak+=1
            if self.aperture_streak>=2:
                self.aperture_open=True
                self.aperture_streak=0
        else:
            self.aperture_streak=0
        return min(1.,(ratio-.030)/.145) if self.aperture_open else 0.

    def _respond(self, ratio, now):
        target=self._aperture_target(ratio)
        self.label_state=0 if not target else (3 if target<.25 else 1)
        dt=max(1,min(500,time.ticks_diff(now,self.last_update)))
        if not target:
            self.value=0.
        else:
            self.value+=(1-math.exp(-dt/34.))*(target-self.value)
        return self.value

    def update(self,img,box,landmarks=None,unclipped=None):
        started=time.ticks_us()
        # A partially visible face is allowed. Both observed mouth corners must
        # still exist; predicted lips alone can hallucinate a mouth on a cheek.
        if not landmarks or any(p[0]<1 or p[1]<1 or p[0]>=img.width()-1 or p[1]>=img.height()-1 for p in landmarks[3:5]):
            self.elapsed_us=time.ticks_diff(time.ticks_us(),started)
            return self.unknown('mouth_out_of_frame')
        x,y,w,h=unclipped if unclipped is not None else box
        side=max(w,h)*1.05;cx,cy=x+w/2,y+h/2
        square=(cx-side/2,cy-side/2,side,side)
        sampling=face_sampling(box,square,img.width(),img.height(),112)
        if sampling is None:return self.unknown('invalid_face_input')
        roi,px,py,sx,sy=sampling
        self.patch.clear()
        self.patch.draw_image(img,px,py,roi=roi,x_scale=sx,y_scale=sy,hint=image.BILINEAR)
        out=list(self.model.predict(self.patch).values())[0]
        pts=[(tensor_value(out,i*2),tensor_value(out,i*2+1)) for i in range(20)]
        self.points=[(square[0]+p[0]*side,square[1]+p[1]*side) for p in pts]
        # PFLD-106 lip indices 52..71. Corners: 52/61, inner pairs:
        # 66->54, 62->60, 70->57, directed from upper to lower inner lip.
        left,right=pts[0],pts[9]
        dx,dy=right[0]-left[0],right[1]-left[1]
        width=math.sqrt(dx*dx+dy*dy)
        self.elapsed_us=time.ticks_diff(time.ticks_us(),started)
        if width<.08 or width>.65 or width*side<12:return self.unknown('invalid_lip_width')
        if any(p[0]<1 or p[1]<1 or p[0]>=img.width()-1 or p[1]>=img.height()-1 for p in self.points):
            return self.unknown('mouth_out_of_frame')
        observed=landmarks[3:5]
        span=math.sqrt((observed[1][0]-observed[0][0])**2+(observed[1][1]-observed[0][1])**2)
        cx=(self.points[0][0]+self.points[9][0])/2;cy=(self.points[0][1]+self.points[9][1])/2
        ox=(observed[0][0]+observed[1][0])/2;oy=(observed[0][1]+observed[1][1])/2
        if span<12 or (cx-ox)**2+(cy-oy)**2>(span*.5)**2:
            return self.unknown('unreliable_lip_alignment')
        gaps=[]
        for upper,lower in ((14,2),(10,8),(18,5)):
            a,b=pts[upper],pts[lower]
            gaps.append(((b[1]-a[1])*dx-(b[0]-a[0])*dy)/(width*width))
        ratio=sum(gaps)/3
        if ratio<-.12 or ratio>.85:return self.unknown('invalid_lip_geometry')
        self.raw=max(0.,ratio)
        self.roi=(int(min(p[0] for p in self.points)),int(min(p[1] for p in self.points)),
                  int(max(p[0] for p in self.points)-min(p[0] for p in self.points)),
                  int(max(p[1] for p in self.points)-min(p[1] for p in self.points)))
        now=time.ticks_ms()
        self._respond(self.raw,now)
        self.known=True;self.status='tracked_lips';self.last_known=self.last_update=now
        self.elapsed_us=time.ticks_diff(time.ticks_us(),started)
        return self.value

    def deinit(self):self.model.deinit()
