"""One hierarchical 3D node rig with an indexed, alpha-textured skin.

Live node transforms with a pose-baked shell and native sprite compositing.
The shell and expression textures share a single rig and character.
"""
import image,sensor,json,time,math

IDENTITY=(1.,0.,0.,0.,1.,0.,0.,0.,1.)
def point(m,p):
    x,y,z=p
    return (m[0]*x+m[1]*y+m[2]*z,m[3]*x+m[4]*y+m[5]*z,m[6]*x+m[7]*y+m[8]*z)
def multiply(a,b):
    rows = []
    for offset in (0, 3, 6):
        x, y, z = a[offset:offset + 3]
        rows.extend((x*b[0] + y*b[3] + z*b[6],
                     x*b[1] + y*b[4] + z*b[7],
                     x*b[2] + y*b[5] + z*b[8]))
    return tuple(rows)


def settle(value,target,dt,deadband,fast_distance):
    """Hold small motion; follow large motion with a shorter time constant."""
    delta=target-value
    if abs(delta)<=deadband:
        return value
    excess=delta-deadband if delta>0 else delta+deadband
    tau=95. if abs(delta)>=fast_distance else 250.
    return value+(1-math.exp(-dt/tau))*excess

class KittenRig:
    def __init__(self,root):
        with open(root+'/kitten-rig.json') as f:self.skin=json.load(f)
        self.pack_path=root+'/kitten-rig.pack'
        self.yaw_atlas=self.skin.get('yaw_atlas')
        self.pose_index=-1
        self.pose_layers=[]
        self.textures=[]
        with open(self.pack_path,'rb') as f:
            stream=f
            if self.skin.get('pack_codec')=='zlib':
                import deflate
                stream=deflate.DeflateIO(f)
            for item in self.skin['textures']:
                index=image.Image(item['w'],item['h'],sensor.GRAYSCALE)
                reference=item.get('palette_ref')
                if reference is None:
                    palette=image.Image(256,1,sensor.RGB565)
                    alpha=image.Image(256,1,sensor.GRAYSCALE)
                    images=(index,palette,alpha)
                else:
                    _,palette,alpha=self.textures[reference]
                    images=(index,)
                if stream is f:
                    f.seek(item['offset'])
                for obj in images:
                    buf=obj.bytearray()
                    if stream.readinto(buf)!=len(buf):raise ValueError('Short rig texture')
                self.textures.append((index,palette,alpha))
            if self.yaw_atlas:
                for (left,top,w,h),offset in zip(self.yaw_atlas['bounds'],self.yaw_atlas['palette_offsets']):
                    index=image.Image(w,h,sensor.GRAYSCALE)
                    palette=image.Image(256,1,sensor.RGB565)
                    opacity=image.Image(256,1,sensor.GRAYSCALE)
                    f.seek(offset)
                    for obj in (palette,opacity):
                        pixels=obj.bytearray()
                        if f.readinto(pixels)!=len(pixels):raise ValueError('Short yaw palette')
                    self.pose_layers.append((index,palette,opacity,left,top))
        self.yaw=self.pitch=0.;self.view=None;self.last_update=time.ticks_ms()
        self.followed_box=None;self.box_update=self.last_update
        self.seen_pose=None
        self.neutral_pitch_row=self.skin.get('neutral_pitch_row',1)
        self.texture_size=self.skin.get('texture_size',104)
        self.shell_col=2;self.shell_row=self.neutral_pitch_row
        self.lip_slopes=self.skin.get('art_mouth_slopes')
        self.pitch_scale=1.;self.pitch_shift=0.
        self.world=[];self.last_controls=(0.,0.,0.);self.render_us=0

    def pose(self,landmarks):
        now=time.ticks_ms();dt=max(1,min(500,time.ticks_diff(now,self.last_update)))
        self.last_update=now
        target_yaw,target_pitch=0.,self.pitch
        pose_valid=False
        if landmarks and len(landmarks)>=3:
            a,b=sorted(landmarks[:2],key=lambda p:p[0]);nose=landmarks[2]
            dx,dy=b[0]-a[0],b[1]-a[1];length2=dx*dx+dy*dy
            if length2>144:
                self.seen_pose=now
                pose_valid=True
                ex,ey=(a[0]+b[0])*.5,(a[1]+b[1])*.5
                nx,ny=nose[0]-ex,nose[1]-ey
                offset=(nx*dx+ny*dy)/length2
                limit=self.skin['yaw_limit_deg']
                target_yaw=max(-limit,min(limit,offset*90.))
                # Measure the nose's distance from the eye line in eye-span
                # units. Mouth corners change with the expression itself.
                nose_axis=(ny*dx-nx*dy)/length2
                target_pitch=max(-24.,min(24.,(nose_axis-.39)*105.))
        if self.seen_pose is not None and time.ticks_diff(now,self.seen_pose)<350 and not pose_valid:
            return
        if not pose_valid:
            # After loss, deliberately relax to neutral rather than freezing
            # at the edge of the deadband.
            blend=1-math.exp(-dt/190.)
            self.yaw*=1-blend
            self.pitch*=1-blend
            return
        self.yaw=settle(self.yaw,target_yaw,dt,2.4,12.)
        self.pitch=settle(self.pitch,target_pitch,dt,1.25 if self.lip_slopes else 3.,12.)

    def follow_box(self,box,now):
        if box is None:
            self.followed_box=None
            return None
        dt=max(1,min(500,time.ticks_diff(now,self.box_update)))
        self.box_update=now
        x,y,w,h=box
        target=(x+w*.5,y+h*.5,w,h)
        if self.followed_box is None:
            self.followed_box=target
        else:
            band=max(2.2,min(4.,w*.018))
            self.followed_box=tuple(settle(old,new,dt,band,band*4)
                                    for old,new in zip(self.followed_box,target))
        cx,cy,w,h=self.followed_box
        return (cx-w*.5,cy-h*.5,w,h)

    def draw_shell(self,canvas,cx,cy,scale):
        # Hysteresis keeps a pose near a sample boundary from hopping back
        # and forth. Each draw has exactly one silhouette.
        col,row=self.shell_col,self.shell_row
        while col<4 and self.yaw>(col-1.5)*16+2:
            col+=1
        while col>0 and self.yaw<(col-2.5)*16-2:
            col-=1
        if self.lip_slopes:
            # Use the neutral pitch artwork and continuously project its
            # vertical axis. The offset and scale approximate the depth
            # difference between the brow, muzzle and chin.
            row=self.neutral_pitch_row
            radians=self.pitch*math.pi/180.
            sine=math.sin(radians)
            self.pitch_scale=math.cos(radians)+.26*sine
            self.pitch_shift=scale*.60*sine
        else:
            while row<2 and self.pitch>(row-.5)*24+1.7:
                row+=1
            while row>0 and self.pitch<(row-1.5)*24-1.7:
                row-=1
        self.shell_col,self.shell_row=col,row
        if self.yaw_atlas:
            step=self.yaw_atlas['step']
            offsets=self.yaw_atlas['offsets']
            index=min(len(offsets)-2,int(abs(self.yaw)/step+.5))
            if index!=self.pose_index:
                import deflate,io
                with open(self.pack_path,'rb') as f:
                    f.seek(offsets[index])
                    packed=f.read(offsets[index+1]-offsets[index])
                # Inflate one buffered slot. Reading individual compressed
                # bytes through FatFS is too slow during head movement.
                with deflate.DeflateIO(io.BytesIO(packed)) as stream:
                    for tex,_,_,_,_ in self.pose_layers:
                        pixels=tex.bytearray()
                        if stream.readinto(pixels)!=len(pixels):raise ValueError('Short yaw sample')
                self.pose_index=index
            self.pose_mirrored=self.yaw>0 and index>0
            self.draw_pose_layer(canvas,0,cx,cy,scale,255)
            return
        index,left,top=self.skin['head_views'][row][col]
        tex,palette,opacity=self.textures[index]
        factor=2*scale/self.texture_size
        y=cy+self.pitch_shift+(-scale+top*factor)*self.pitch_scale
        canvas.draw_image(tex,int(cx-scale+left*factor),int(y),
                          x_scale=factor,y_scale=factor*self.pitch_scale,
                          color_palette=palette,alpha_palette=opacity)

    def draw_pose_layer(self,canvas,index,cx,cy,scale,alpha):
        tex,palette,opacity,left,top=self.pose_layers[index]
        hint=0
        if self.pose_mirrored:
            left=self.texture_size-left-tex.width()
            hint=image.HMIRROR
        factor=2*scale/self.texture_size
        y=cy+self.pitch_shift+(-scale+top*factor)*self.pitch_scale
        canvas.draw_image(tex,int(cx-scale+left*factor),int(y),
                          x_scale=factor,y_scale=factor*self.pitch_scale,hint=hint,
                          color_palette=palette,alpha_palette=opacity,alpha=alpha)

    def draw_art_lids(self,canvas,cx,cy,scale):
        if self.yaw_atlas:
            for side,closure in enumerate(self.last_controls[:2]):
                if closure>.04:
                    index=2-side if self.pose_mirrored else 1+side
                    self.draw_pose_layer(canvas,index,cx,cy,scale,min(255,int(closure*291)))
            return
        factor=2*scale/self.texture_size
        lids=self.skin['lid_views'][self.shell_row][self.shell_col]
        for closure,(index,left,top) in zip(self.last_controls,lids):
            if closure<=.04:
                continue
            tex,palette,opacity=self.textures[index]
            y=cy+self.pitch_shift+(-scale+top*factor)*self.pitch_scale
            canvas.draw_image(tex,int(cx-scale+left*factor),int(y),
                              x_scale=factor,y_scale=factor*self.pitch_scale,alpha=min(255,int(closure*291)),
                              color_palette=palette,alpha_palette=opacity)

    def draw_lip_sprite(self,canvas,tex,palette,alpha,x,y,w,h,slope):
        # Make the lip slope independent of the animated mouth height. Draw
        # non-overlapping vertical strips using the existing indexed texture.
        sw,sh=tex.width(),tex.height()
        width=max(1,int(w))
        left=0
        for i in range(0,sw,4):
            span=min(4,sw-i)
            right=(i+span)*width//sw
            if right>left:
                dy=round((left+right-width)*.5*slope)
                canvas.draw_image(tex,x+left,y+dy,roi=(i,0,span,sh),
                                  x_scale=(right-left+.001)/span,y_scale=h/sh,
                                  color_palette=palette,alpha_palette=alpha)
            left=right

    def bones(self,values,yaw=None,pitch=None):
        self.last_controls=tuple(max(0.,min(1.,v)) for v in values)
        yaw=(self.yaw if yaw is None else yaw)*math.pi/180.
        cy,sy=math.cos(yaw),math.sin(yaw)
        pitch=(self.pitch if pitch is None else pitch)*math.pi/180.
        cp,sp=math.cos(pitch),math.sin(pitch)
        root=(cy,0.,sy,sp*sy,cp,-sp*cy,-cp*sy,sp,cp*cy)
        world=[]
        for bone in self.skin['bones']:
            parent=bone['parent'];motion=bone.get('motion','');local=IDENTITY
            if motion=='jaw_hinge':
                angle=self.last_controls[2]*self.skin['jaw_angle_deg']*math.pi/180.
                c=math.cos(angle);s=math.sin(angle);local=(1.,0.,0.,0.,c,-s,0.,s,c)
            if parent<0:position=tuple(bone['position']);matrix=root
            else:
                pm,pp=world[parent];p=point(pm,bone['position'])
                position=(p[0]+pp[0],p[1]+pp[1],p[2]+pp[2])
                matrix=pm if local is IDENTITY else multiply(pm,local)
            world.append((matrix,position))
        self.world=world

    def draw(self,canvas,box,values,landmarks=None,pixel_scale=1.):
        started=time.ticks_us();self.pose(landmarks)
        bx,by,bw,bh=(coord*pixel_scale for coord in box)
        size=min(250*pixel_scale,max(bw*1.55,bh*1.30));scale=size*.5
        cx=bx+bw*.5;cy=by+bh*.5-size*.04
        if self.yaw_atlas or 'head_views' in self.skin:
            self.draw_shell(canvas,cx,cy,scale)
        art_lids=self.yaw_atlas is not None or 'lid_views' in self.skin
        if art_lids:
            self.bones(values,self.yaw if self.yaw_atlas else (self.shell_col-2)*16,
                       (self.shell_row-self.neutral_pitch_row)*24)
            self.draw_art_lids(canvas,cx,cy,scale)
        else:
            self.bones(values)
        calls=[];op=self.last_controls[2]
        for part in self.skin['attachments']:
            bone_id=part['bone'];bone=self.skin['bones'][bone_id];visible=part.get('visible','')
            closed=self.last_controls[0 if bone.get('motion')=='left_lid' else 1]
            height_scale=1.
            if visible=='eye_open':
                if closed>=.92:continue
                height_scale=max(.12,1-closed)
            elif visible=='eye_closed':
                if closed<.92:continue
            elif visible=='mouth_open':
                if op<=.04:continue
                height_scale=max(.06,op)
            elif visible=='mouth_closed':
                if op>.04:continue
            m,p=self.world[bone_id];q=point(m,part['offset'])
            x,y,z=q[0]+p[0],q[1]+p[1],q[2]+p[2]
            if visible=='eye_open':
                y-=.020*closed
            elif visible=='mouth_open' and art_lids:
                # Keep the top of the aperture close to the baked upper lip.
                y-=.055*op
            elif visible in ('mouth_open','mouth_closed') and self.pitch>0.:
                y+=.0046*self.pitch
            w,h=part['size'];h*=height_scale
            if visible in ('eye_open','eye_closed') and x*self.yaw>0.:
                w*=1.-.16*abs(self.yaw)/32
            if 'volume_depth_ratio' in part:
                # Ellipsoid silhouette width remains round as the head turns.
                r=part['volume_depth_ratio'];width=w*math.sqrt(m[0]*m[0]+r*r*m[2]*m[2])
            else:width=w*max(.25,abs(m[0]))+h*abs(m[1])
            height=h*abs(m[4])+w*abs(m[3])
            slope=0.
            if visible=='mouth_open' and 'art_mouth_views' in self.skin:
                # Attach the upper edge of the aperture to the baked lip line.
                # Scale the cavity downward about this point as the jaw opens.
                mouth_views=self.skin['art_mouth_views'][self.shell_row]
                if self.yaw_atlas:
                    direction=1 if self.pose_mirrored else -1
                    view=2+direction*self.pose_index*self.yaw_atlas['step']/16
                    low=min(3,int(view))
                    portion=view-low
                    x,y,foreshorten=(a+(b-a)*portion for a,b in zip(mouth_views[low],mouth_views[low+1]))
                    slope=(self.lip_slopes[low]+(self.lip_slopes[low+1]-self.lip_slopes[low])*portion)*self.pitch_scale
                else:
                    x,y,foreshorten=mouth_views[self.shell_col]
                    if self.lip_slopes:
                        slope=self.lip_slopes[self.shell_col]*self.pitch_scale
                width=w*foreshorten
                height=h
                y-=(.5-.20)*height
            y*=self.pitch_scale
            height*=self.pitch_scale
            sw=max(1.,width*scale);sh=max(1.,height*scale)
            # Keep the mouth in front of the overlapping whisker attachments.
            surface_bias=.15 if visible in ('mouth_open','mouth_closed') else 0.
            calls.append((z+surface_bias,part['texture'],int(cx+x*scale-sw*.5),
                          int(cy+self.pitch_shift-y*scale-sh*.5),sw,sh,slope))
        # Approximate occlusion by attachment depth; no per-pixel depth buffer.
        calls.sort(key=lambda item:item[0])
        for z,index,x,y,w,h,slope in calls:
            tex,palette,alpha=self.textures[index]
            if slope and w>=8:
                self.draw_lip_sprite(canvas,tex,palette,alpha,x,y,w,h,slope)
            else:
                canvas.draw_image(tex,x,y,x_scale=w/tex.width(),y_scale=h/tex.height(),
                                  color_palette=palette,alpha_palette=alpha)
        self.render_us=time.ticks_diff(time.ticks_us(),started)
