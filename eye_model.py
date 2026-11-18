"""On-device Open Model Zoo eye classifier, converted to ESP-DL W16A16.

Original model: open-closed-eye-0001, Apache-2.0. See models/eyes/source.json.
The runtime requires no desktop service. Verified output order is [closed, open].
The OMZ model page reverses these labels; its gaze demo and sample images agree
on index 0 = closed. See evidence/eye-output-semantics.json.
"""
import time, math, struct
import sensor, image, espdl
from face_landmarks import value as tensor_value


# ESP-VISION 2026.11.14 RGB565 codes whose native grayscale conversion yields
# each luma value from 0 to 255. Check the mapping before using the palette.
_LUMA_PALETTE = (
    0x0001, 0x0002, 0x0800, 0x0801, 0x1000, 0x1001, 0x1002, 0x1800, 0x1801, 0x2000, 0x2001, 0x2002,
    0x2800, 0x2801, 0x3000, 0x3001, 0x3800, 0x3801, 0x3802, 0x4000, 0x4001, 0x4800, 0x4801, 0x4802,
    0x5000, 0x5001, 0x5800, 0x5801, 0x5802, 0x6000, 0x6001, 0x6800, 0x6801, 0x6802, 0x7000, 0x7001,
    0x7800, 0x7801, 0x7820, 0x8000, 0x8001, 0x8800, 0x8801, 0x9000, 0x9001, 0x9002, 0x9800, 0x9801,
    0xa000, 0xa001, 0xa002, 0xa800, 0xa801, 0xb000, 0xb001, 0xb002, 0xb800, 0xb802, 0xc000, 0xc001,
    0xc002, 0xc800, 0xc801, 0xd000, 0xd001, 0xd800, 0xd801, 0xd802, 0xe000, 0xe001, 0xe800, 0xe801,
    0xe802, 0xf000, 0xf001, 0xf800, 0xf801, 0xf802, 0xf821, 0xf822, 0xf840, 0xf841, 0xf860, 0xf861,
    0xf862, 0xf880, 0xf882, 0xf8a0, 0xf8a1, 0xf8c0, 0xf8c1, 0xf8c2, 0xf8e0, 0xf8e2, 0xf900, 0xf901,
    0xf920, 0xf921, 0xf922, 0xf940, 0xf941, 0xf960, 0xf961, 0xf980, 0xf981, 0xf982, 0xf9a0, 0xf9a1,
    0xf9c0, 0xf9c1, 0xf9e0, 0xf9e1, 0xf9e2, 0xfa00, 0xfa01, 0xfa02, 0xfa20, 0xfa21, 0xfa40, 0xfa41,
    0xfa60, 0xfa61, 0xfa62, 0xfa80, 0xfa81, 0xfaa0, 0xfaa1, 0xfac0, 0xfac1, 0xfac2, 0xfae0, 0xfae1,
    0xfb00, 0xfb01, 0xfb20, 0xfb21, 0xfb22, 0xfb40, 0xfb41, 0xfb60, 0xfb61, 0xfb80, 0xfb81, 0xfb82,
    0xfba0, 0xfba1, 0xfbc0, 0xfbc1, 0xfbe0, 0xfbe1, 0xfbe2, 0xfc00, 0xfc01, 0xfc02, 0xfc20, 0xfc21,
    0xfc40, 0xfc41, 0xfc60, 0xfc61, 0xfc62, 0xfc80, 0xfc81, 0xfca0, 0xfca1, 0xfcc0, 0xfcc1, 0xfcc2,
    0xfce0, 0xfce1, 0xfd00, 0xfd01, 0xfd20, 0xfd21, 0xfd22, 0xfd40, 0xfd41, 0xfd60, 0xfd61, 0xfd62,
    0xfd81, 0xfd82, 0xfda0, 0xfda1, 0xfdc0, 0xfdc1, 0xfdc2, 0xfde1, 0xfde2, 0xfe00, 0xfe01, 0xfe02,
    0xfe20, 0xfe21, 0xfe40, 0xfe41, 0xfe60, 0xfe61, 0xfe62, 0xfe80, 0xfe81, 0xfea0, 0xfea1, 0xfea2,
    0xfec1, 0xfec2, 0xfee0, 0xfee1, 0xff00, 0xff01, 0xff02, 0xff21, 0xff22, 0xff40, 0xff41, 0xff60,
    0xff61, 0xff62, 0xff80, 0xff82, 0xffa0, 0xffa1, 0xffc0, 0xffc1, 0xffc2, 0xffe0, 0xffe2, 0xffe3,
    0xffe4, 0xffe5, 0xffe6, 0xffe7, 0xffe8, 0xffe9, 0xffea, 0xffeb, 0xffec, 0xffed, 0xffee, 0xffef,
    0xfff0, 0xfff1, 0xfff2, 0xfff3, 0xfff4, 0xfff5, 0xfff6, 0xfff7, 0xfff8, 0xfff9, 0xfffa, 0xfffb,
    0xfffc, 0xfffd, 0xfffe, 0xffff,
)


class EyeNormalizer:
    """Apply the existing fixed-point eye normalization with a native palette."""

    def __init__(self):
        self.palette = None
        try:
            palette = image.Image(256, 1, sensor.RGB565)
            buffer = palette.bytearray()
            struct.pack_into('<256H', buffer, 0, *_LUMA_PALETTE)
            source = image.Image(32, 32, sensor.GRAYSCALE)
            output = image.Image(32, 32, sensor.GRAYSCALE)
            ramp = bytes(range(256)) * 4
            source.bytearray()[:] = ramp
            output.draw_image(source, color_palette=palette)
            if output.bytearray() == ramp:
                self.palette = palette
                self.buffer = buffer
                self.output = output
        except (MemoryError, ValueError, TypeError, OSError):
            # Firmware without the expected palette behavior uses exact Python.
            pass

    def apply(self, patch, mean, gain):
        if self.palette is None:
            lut = bytes(max(0, min(255, (((p - mean) * gain) >> 8) + 112))
                        for p in range(256))
            pixels = patch.bytearray()
            for i in range(len(pixels)):
                pixels[i] = lut[pixels[i]]
            return

        # Build only the unclipped part of the LUT. Output is grayscale again
        # so inference and diagnostic thumbnails get the same bytes as before.
        lo = max(0, mean - (112 * 256) // gain)
        hi = min(256, mean + (143 * 256 + gain - 1) // gain)
        values = ([_LUMA_PALETTE[0]] * lo
                  + [_LUMA_PALETTE[(((p - mean) * gain) >> 8) + 112]
                     for p in range(lo, hi)]
                  + [_LUMA_PALETTE[255]] * (256 - hi))
        struct.pack_into('<256H', self.buffer, 0, *values)
        self.output.draw_image(patch, color_palette=self.palette)
        patch.bytearray()[:] = self.output.bytearray()


class EyeNet:
    def __init__(self, root, safe_resize=False):
        # Use ESP-DL for both models. On S31/2026.11.14, a TFLite inference
        # reproducibly changes subsequent ESP-DL results until a hard reset.
        self.model = espdl.Model(root+'/eye_w16a16.espdl',
            mean=(127,127,127),std=(255,255,255),rgb_swap=True,letterbox=False)
        self.patch = image.Image(32,32,sensor.GRAYSCALE)
        self.rgb = image.Image(32,32,sensor.RGB565)
        self.elapsed_us = 0
        self.safe_resize=safe_resize
        self.capture_to=None
        self.normalizer=None

    def predict(self, img, roi, normalize=False):
        start = time.ticks_us()
        # Use BILINEAR in production; AREA is retained only for old replay probes.
        hint=image.BILINEAR if self.safe_resize else (image.AREA if roi[2]>32 and roi[3]>32 else image.BILINEAR)
        self.patch.draw_image(img,roi=roi,x_scale=32/roi[2],y_scale=32/roi[3],hint=hint)
        if normalize:
            # Fixed, per-frame photometric normalization, never personal fitting.
            # Native statistics and palette operations run on the MCU.
            stats=self.patch.get_statistics()
            mean=stats.mean()
            gain=min(640,10240//max(10,stats.stdev()))
            if self.normalizer is None:
                self.normalizer = EyeNormalizer()
            self.normalizer.apply(self.patch, mean, gain)
        self.rgb.draw_image(self.patch)
        if self.capture_to is not None:
            self.capture_to.bytearray()[:]=self.rgb.bytearray()
        output = list(self.model.predict(self.rgb).values())[0]
        closed_logit,open_logit = tensor_value(output,0),tensor_value(output,1)
        closed = 1/(1+math.exp(max(-60.,min(60.,open_logit-closed_logit))))
        self.elapsed_us = time.ticks_diff(time.ticks_us(),start)
        return closed

    def deinit(self):
        self.model.deinit()


class EyeTracker:
    """Use YuNet eye centers to classify fresh full-resolution eye crops."""
    def __init__(self,root,safe_resize=False):
        self.net=EyeNet(root,safe_resize)
        self.values=[0.,0.]
        self.raw=[.5,.5]
        self.quality=[0.,0.]
        self.closed=[False,False]
        self.animation_closed=[False,False]
        self.animation_votes=[bytearray(3),bytearray(3)]
        self.animation_cursor=[0,0]
        self.known=[False,False]
        self.last_known=[time.ticks_ms(),time.ticks_ms()]
        self.last_update=list(self.last_known)
        self.shift=None
        self.rois=[]
        self.status='initializing'
        self.elapsed_us=0
        self.patches=[image.Image(32,32,sensor.GRAYSCALE) for _ in range(2)]
        # Optional developer capture. Never allocated during normal operation.
        self.input_rgbs=None
        self.primary_raw=[.5,.5]
        self.near=False
        self.views=[[],[]]

    def _roi(self,img,cx,cy,distance,ratio):
        side=int(distance*ratio)
        # Reduce context symmetrically at an image edge. Do not shift the eye
        # center or invent missing pixels; the central eye must remain visible.
        side=min(side,int(2*min(cx,cy,img.width()-cx,img.height()-cy)))
        if side<18 or side<distance*.30:return None
        x,y=int(cx-side/2),int(cy-side/2)
        if x<0 or y<0 or x+side>img.width() or y+side>img.height():return None
        return (x,y,side,side)

    def _missing_eye(self,r,now):
        self.raw[r]=.5;self.known[r]=False;self.quality[r]=0.
        self._vote_animation(r,now,0)

    def _animate(self,r,now,target=None):
        # Fixed time constants remain meaningful when the inference cadence
        # changes. Unknown holds briefly, then fades; it is not a closed label.
        dt=max(1,min(1000,time.ticks_diff(now,self.last_update[r])))
        if target is not None:
            tau=128. if target else 90.
            self.values[r]+=(1-math.exp(-dt/tau))*(target-self.values[r])
        else:
            fade_ms=min(dt,max(0,time.ticks_diff(now,self.last_known[r])-300))
            if fade_ms:
                self.animation_closed[r]=False
                self.values[r]*=math.exp(-fade_ms/150.)
        self.last_update[r]=now

    def _vote_animation(self,r,now,vote):
        # Each frame consumes one slot. Ambiguous or missing samples cast
        # neither vote, and a tie keeps the last decided eye state.
        history=self.animation_votes[r]
        cursor=self.animation_cursor[r]
        history[cursor]=vote
        self.animation_cursor[r]=(cursor+1)%len(history)
        opened=closed=0
        for sample in history:
            opened+=sample==1
            closed+=sample==2
        if closed>=2:
            self.animation_closed[r]=True
        elif opened>=2:
            self.animation_closed[r]=False
        target=(1. if self.animation_closed[r] else 0.) if opened or closed else None
        self._animate(r,now,target)

    def _respond(self,r,now,p,open_at,close_at):
        self.known[r]=p<=open_at or p>=close_at
        vote=0
        if self.known[r]:
            self.closed[r]=p>=close_at
            self.last_known[r]=now
            vote=2 if self.closed[r] else 1
        self._vote_animation(r,now,vote)

    def _unknown(self,reason):
        self.status=reason
        self.known=[False,False]
        self.quality=[0.,0.]
        self.raw=[.5,.5]
        now=time.ticks_ms()
        for r in range(2):
            if reason=='face_missing':
                history=self.animation_votes[r]
                for i in range(len(history)):history[i]=0
                self.animation_closed[r]=False
                self.values[r]=0.
            self._vote_animation(r,now,0)
        return self.values,self.raw,self.quality

    def update(self,face,img,crop,landmarks=None):
        start=time.ticks_us()
        if not landmarks:return self._unknown('unknown_landmarks')
        centers=sorted(landmarks[:2],key=lambda p:p[0])
        dx,dy=centers[1][0]-centers[0][0],centers[1][1]-centers[0][1]
        distance=math.sqrt(dx*dx+dy*dy)
        self.near=distance*240/img.width()>=80
        side=int(distance*.60)
        if side<18:return self._unknown('unknown_resolution')
        self.rois=[self._roi(img,cx,cy,distance,.50 if self.near else .60) for cx,cy in centers]
        self.views=[[],[]]
        now=time.ticks_ms()
        for r in range(2):
            roi=self.rois[r]
            if roi is None:
                self._missing_eye(r,now)
                continue
            self.net.capture_to=self.input_rgbs[r] if self.input_rgbs is not None else None
            p=self.net.predict(img,roi,normalize=self.near)
            self.net.capture_to=None
            self.primary_raw[r]=p
            self.patches[r].draw_image(self.net.patch)
            self.views[r].append(p)
            if self.near and .15<p<.85:
                cx,cy=centers[r]
                wider=self._roi(img,cx,cy,distance,.60)
                if wider is not None and wider!=roi:
                    q=self.net.predict(img,wider,normalize=True)
                    self.views[r].append(q)
                    p=(p+q)*.5
            self.raw[r]=p
            self.quality[r]=abs(p-.5)*2
            open_at,close_at=(.30,.60) if self.near else (.35,.65)
            self._respond(r,now,p,open_at,close_at)
        self.status='tracked' if all(self.known) else ('partial_bounds' if None in self.rois else 'unknown_ambiguous')
        self.elapsed_us=time.ticks_diff(time.ticks_us(),start)
        return self.values,self.raw,self.quality

    def deinit(self):self.net.deinit()
