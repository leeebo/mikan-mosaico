"""Mikan standalone camera: pretrained models, no personal calibration flow."""
import sys
ROOT='/flash/memoji-camera'
if ROOT not in sys.path:sys.path.insert(0,ROOT)
import time,gc,json,os
import sensor,image,display,esp32
try:
    import uvc
except ImportError:
    uvc=None
from machine import Pin
from face_landmarks import FaceDetector
from eye_model import EyeTracker
from lip_model import LipTracker
from kitten_rig import KittenRig
from product_labels import ProductLabels
import locator_debug

DARK=(15,34,39)
CREAM=(247,235,204)
TEAL=(94,225,195)
button_pending=False
button_pending_at=0
pending_stats=[]
try:log_bytes=os.stat(ROOT+'/telemetry.ndjson')[6]
except OSError:log_bytes=0

def button_irq(pin):
    global button_pending,button_pending_at
    if not button_pending:
        button_pending_at=time.ticks_ms()
        button_pending=True

def emit(event,**kw):
    global log_bytes
    kw['event']=event;kw['ms']=time.ticks_ms()
    line=json.dumps(kw)
    if event=='stats':
        pending_stats.append(line)
        if len(pending_stats)>60:del pending_stats[0]
        return
    print(line)
    # Stream buffered lines instead of allocating two more ~60KB strings.
    payload_bytes=sum(len(item)+1 for item in pending_stats)+len(line)+1
    try:
        if log_bytes+payload_bytes>65536:
            try:os.remove(ROOT+'/telemetry.prev.ndjson')
            except OSError:pass
            os.rename(ROOT+'/telemetry.ndjson',ROOT+'/telemetry.prev.ndjson')
            log_bytes=0
        with open(ROOT+'/telemetry.ndjson','a') as f:
            for item in pending_stats:f.write(item);f.write('\n')
            f.write(line);f.write('\n')
        log_bytes+=payload_bytes
        del pending_stats[:]
    except OSError:pass

def heap():
    regions=esp32.idf_heap_info(esp32.HEAP_DATA)
    return {'python_free':gc.mem_free(),'idf_free':sum(r[1] for r in regions),
            'largest_idf_block':max(r[2] for r in regions)}

def load_raw(name,w,h,fmt):
    obj=image.Image(w,h,fmt)
    with open(ROOT+'/'+name,'rb') as f:n=f.readinto(obj.bytearray())
    if n!=len(obj.bytearray()):raise ValueError('Short asset: '+name)
    return obj

lcd=det=eyes=mouth=button=None
try:
    jpeg_warmup=None
    if uvc is not None:
        try:
            # On S31, prime the image allocator before the camera and ESP-DL
            # reserve their arenas. Hold the decoded storage through setup.
            warm=image.Image(ROOT+'/uvc-warmup.jpg').to_rgb565(copy=True)
            jpeg_warmup=bytearray(warm.bytearray())
            del warm
            gc.collect()
        except (OSError,MemoryError):
            pass
    # Source and preview sizes remain independent. The lip regressor uses the
    # color QVGA source while the VGA experiment is retained in backups/v26.
    sensor.reset();sensor.set_pixformat(sensor.RGB565)
    sensor.set_framesize(sensor.QVGA);sensor.set_hmirror(True)
    lcd=display.ESP32Display()
    W,H=sensor.width(),sensor.height()
    lcd_width,lcd_height=lcd.width(),lcd.height()
    center_size=min(320,lcd_width,lcd_height)
    center_scale=center_size/128
    center_x,center_y=(lcd_width-center_size)//2,(lcd_height-center_size)//2
    showing_center=False
    centered=True
    PW,PH=240,320
    camera_buffer=bytearray(W*H*2)
    # At equal source/preview sizes, compose after inference directly into the
    # owned snapshot buffer. Each following snapshot fully replaces its pixels.
    # Debug/audit paths retain a pristine source and lazily allocate a canvas.
    preview_canvas=None
    character=KittenRig(ROOT)
    labels=ProductLabels(ROOT)
    validation=None;validation_previous_debug=0;validation_stop_at=None
    # Arm development tests only at startup, while the app is stopped during
    # file transfer. A physical press starts the already-visible prompt.
    try:
        os.stat(ROOT+'/eye-validation.flag');os.remove(ROOT+'/eye-validation.flag')
        from eye_validation import EyeValidation
        validation=EyeValidation(ROOT,emit)
    except OSError:pass
    if validation is None:
        try:
            os.stat(ROOT+'/eye-roi-audit.flag');os.remove(ROOT+'/eye-roi-audit.flag')
            from eye_roi_audit import EyeRoiAudit
            validation=EyeRoiAudit(ROOT,emit)
        except OSError:pass
    if validation is None:
        try:
            os.stat(ROOT+'/eye-sync-audit.flag');os.remove(ROOT+'/eye-sync-audit.flag')
            from eye_sync_audit import EyeSyncAudit
            validation=EyeSyncAudit(ROOT,emit)
        except OSError:pass
    validation_label=image.Image(240,40,sensor.RGB565) if validation is not None else None
    gc.collect()
    det=FaceDetector(ROOT,score=.65)
    mouth=LipTracker(ROOT)
    eyes=EyeTracker(ROOT,safe_resize=True)
    webcam_mode=uvc.get_mode() if jpeg_warmup is not None else None
    webcam_camera=webcam_center=None
    if webcam_mode:
        uw,uh=webcam_mode['width'],webcam_mode['height']
        webcam_scale=min(uw/lcd_width,uh/lcd_height)
        webcam_bytes=uw*uh*2
        if webcam_bytes<=min(len(camera_buffer),center_size*center_size*2):
            webcam_camera=image.Image(uw,uh,sensor.RGB565,buffer=camera_buffer)
            webcam_camera.clear()
            # Let ESP-DL reserve its contiguous memory first. Reserve UVC's
            # native storage before allocating the LCD canvas.
            try:
                if not uvc.set_frame(webcam_camera):
                    webcam_camera=None
            except (OSError,ValueError):
                webcam_camera=None
    if webcam_camera is not None:
        try:
            center_buffer=bytearray(center_size*center_size*2)
            center_canvas=image.Image(center_size,center_size,sensor.RGB565,buffer=center_buffer)
            webcam_center=image.Image(uw,uh,sensor.RGB565,buffer=center_buffer)
        except MemoryError:
            uvc.reset()
            webcam_camera=None
            center_buffer=None
    del jpeg_warmup
    gc.collect()
    if webcam_camera is None:
        center_canvas=image.Image(center_size,center_size,sensor.RGB565)
    stat_webcam_submitted=stat_webcam_errors=stat_webcam_us=0
    button=Pin(7,Pin.IN,Pin.PULL_UP)
    button.irq(handler=button_irq,trigger=Pin.IRQ_FALLING)
    debug=1 if validation is not None else 0
    last_button=time.ticks_add(time.ticks_ms(),-601)
    box=landmarks=unclipped_box=None;last_seen=0;last_detect=0;face_coverage=0.
    frame_no=0;values=[0.,0.,0.]
    stats_t=time.ticks_ms();stat_count=stat_faces=stat_max=0
    stat_parts=[0,0,0,0,0];stat_eyes={};stat_mouth_known=0;stat_mouth={};stat_mouth_updates=0
    stat_eye_updates=0;last_eye_update=None;stat_eye_interval_max=0
    fps=0.
    display_submissions=0
    gc.collect()
    emit('ready',build='rig-v59',mode='RUN',camera=[W,H],preview=[PW,PH],source_format='RGB565',
         character='Mikan',rendering='shared_pitch_projection_and_lip_tangent',
         rig_bones=len(character.skin['bones']),skin_bytes=character.skin['pack_bytes'],
         lcd=[lcd_width,lcd_height],display_mode="center",heap=heap(),
         webcam=webcam_mode if webcam_camera is not None else None,
         models=['yunet','omz-eye-w16a16','pfld-lips-mixed-minmax'])
    while True:
        tick=time.ticks_ms()
        img=sensor.snapshot(camera_buffer)
        t_capture=time.ticks_ms()
        if validation is not None and hasattr(validation,'bind_frame'):
            validation.bind_frame(frame_no,tick,t_capture)
        # A fixed three-frame cadence can exceed the 600ms face validity
        # window as model cost changes. Refresh by elapsed time, before using
        # expired landmarks; failed detections still expire normally.
        if debug or box is None or time.ticks_diff(tick,last_detect)>=(300 if eyes.near else 450):
            last_detect=tick
            hits=det.detect(img)
            if hits:
                hit=hits[0];x,y,w,h=hit[:4]
                x,y=max(0,int(x)),max(0,int(y))
                w,h=min(W-x,int(w)),min(H-y,int(h))
                if w>=45*W/PW and h>=50*H/PH:
                    box=(x,y,w,h);landmarks=hit[6];last_seen=tick
                    face_coverage=det.coverage
                    unclipped_box=det.unclipped_box
            elif time.ticks_diff(tick,last_seen)>600:box=None
        valid=box is not None and time.ticks_diff(tick,last_seen)<600
        clipped=valid and face_coverage<.93
        t_detect=time.ticks_ms()
        if valid:
            mouth.update(img,box,landmarks,unclipped_box)
            stat_mouth_updates+=1
            eyes.update(None,img,None,landmarks)
            eye_tick=time.ticks_ms()
            if last_eye_update is not None:
                stat_eye_interval_max=max(stat_eye_interval_max,time.ticks_diff(eye_tick,last_eye_update))
            last_eye_update=eye_tick;stat_eye_updates+=1
            values[0],values[1],values[2]=eyes.values[0],eyes.values[1],mouth.value
        else:
            eyes._unknown('face_missing');last_eye_update=None
            mouth.unknown('missing_face');values=[0.,0.,mouth.value]
        t_expression=time.ticks_ms()
        if button_pending:
            pressed_at=button_pending_at;button_pending=False
            if time.ticks_diff(pressed_at,last_button)>600:
                last_button=pressed_at
                if validation is not None:
                    if validation.started is None:
                        if hasattr(validation,'start_from_button'):validation.start_from_button(pressed_at)
                        else:validation.start()
                else:
                    if debug:
                        debug=0
                    else:
                        centered=not centered
                    emit('display_info',enabled=debug,display_mode='center' if centered else 'overlay')
        if frame_no%10==0:
            try:
                with open(ROOT+'/view-mode.txt') as f:requested=int(f.read())
                os.remove(ROOT+'/view-mode.txt')
                if validation is None and requested in (0,1,2,3):
                    debug=requested if requested in (1,2) else 0
                    if not debug:
                        centered=requested==3
                    emit('display_info',enabled=debug,display_mode='center' if centered else 'overlay')
            except OSError:pass
            except ValueError:pass
        # Developer snapshots must see raw camera pixels, before any overlay.
        if frame_no%10==0:
            locator_debug.save_if_requested(ROOT,img,det,eyes,mouth,landmarks,box,time.ticks_diff(tick,last_seen))
        display_box=character.follow_box(box if valid else None,tick)
        center_frame=centered and not debug and validation is None
        if center_frame:
            preview_canvas=None
            canvas=center_canvas
            canvas.clear()
            character.draw(canvas,(22,22,84,87),values if valid else (0.,0.,0.),
                           landmarks if valid else None,pixel_scale=center_scale)
        else:
            if debug or validation is not None or (W,H)!=(PW,PH):
                if preview_canvas is None:preview_canvas=image.Image(PW,PH,sensor.RGB565)
                canvas=preview_canvas
                canvas.draw_image(img,x_scale=PW/W,y_scale=PH/H,hint=image.AREA)
            else:
                canvas=img
                preview_canvas=None
            if not debug:
                if valid:
                    preview_box=tuple(v*PW/W for v in display_box)
                    character.draw(canvas,preview_box,values,landmarks)
                else:
                    character.draw(canvas,(PW//2-38,PH//2-43,76,86),(0.,0.,0.))
                wanted_label=1 if not valid else (3 if clipped and any(eyes.known) else (0 if all(eyes.known) and mouth.known else 2))
                labels.draw(canvas,wanted_label)
        if debug:
            locator_debug.draw(canvas,ROOT,box if valid else None,landmarks if valid else None,eyes,mouth,time.ticks_diff(tick,last_seen),debug==2,source_width=W)
            canvas.draw_rectangle(0,64,240,22,color=DARK,fill=True)
            canvas.draw_string(4,66,'F%d T%d'%(frame_no,t_capture),color=TEAL,scale=2)
        if validation is not None:
            if not validation.step(canvas,validation_label,img,eyes,mouth,valid,frame_no,tick):
                post_run_ms=getattr(validation,'post_run_ms',65000)
                validation=None;debug=validation_previous_debug;gc.collect()
                # A developer test ends after an additional normal-mode minute,
                # allowing its foreground runner to return with all evidence.
                validation_stop_at=time.ticks_add(time.ticks_ms(),post_run_ms) if post_run_ms is not None else None
        t_render=time.ticks_ms()
        if center_frame:
            if not showing_center:
                lcd.clear()
            lcd.write(canvas,x=center_x,y=center_y,fit=False)
        else:
            lcd.write(canvas)
        showing_center=center_frame
        t_display=time.ticks_ms()
        if validation is not None and hasattr(validation,'after_display'):
            validation.after_display(frame_no,t_render,t_display)
        display_submissions+=1
        if webcam_camera is not None and uvc.is_streaming():
            started=time.ticks_us()
            # The other mode's buffer is idle after LCD submission. UVC
            # copies the encoded frame before returning.
            webcam=webcam_camera if center_frame else webcam_center
            scale=webcam_scale if center_frame else webcam_scale*min(lcd_width/canvas.width(),lcd_height/canvas.height())
            webcam.clear()
            webcam.draw_image(canvas,int((uw-canvas.width()*scale)*.5),
                              int((uh-canvas.height()*scale)*.5),
                              x_scale=scale,y_scale=scale,hint=image.AREA)
            try:
                stat_webcam_submitted+=int(uvc.write(webcam.to_jpeg(quality=45,copy=True)))
            except (OSError,ValueError,MemoryError):
                # A UVC allocation or encoding failure must not stop the LCD.
                stat_webcam_errors+=1
            stat_webcam_us+=time.ticks_diff(time.ticks_us(),started)
        end=time.ticks_ms()
        parts=(time.ticks_diff(t_capture,tick),time.ticks_diff(t_detect,t_capture),
               time.ticks_diff(t_expression,t_detect),time.ticks_diff(t_render,t_expression),time.ticks_diff(t_display,t_render))
        for i in range(5):stat_parts[i]+=parts[i]
        stat_max=max(stat_max,time.ticks_diff(end,tick));stat_count+=1
        stat_faces+=int(valid);stat_mouth_known+=int(valid and mouth.known)
        stat_mouth[mouth.status]=stat_mouth.get(mouth.status,0)+1
        status=eyes.status if valid else 'face_missing'
        stat_eyes[status]=stat_eyes.get(status,0)+1
        frame_no+=1
        if time.ticks_diff(end,stats_t)>=2000:
            elapsed=time.ticks_diff(end,stats_t);fps=stat_count*1000/elapsed
            gc.collect()
            emit('stats',mode='RUN',frames=stat_count,elapsed_ms=elapsed,fps=round(fps,2),
                 face_frames=stat_faces,eye_status_counts=stat_eyes,mouth_known_frames=stat_mouth_known,
                 mouth_status_counts=stat_mouth,mouth_updates=stat_mouth_updates,mouth_roi=mouth.roi,debug=debug,
                 frame_max_ms=stat_max,parts_ms=[round(v/stat_count,2) for v in stat_parts],
                 face=box if valid else None,face_coverage=face_coverage if valid else 0.,
                 values=[round(v,3) for v in values],
                 eye_raw=eyes.raw,eye_views=eyes.views,eye_rois=eyes.rois,near=eyes.near,
                 eye_updates=stat_eye_updates,eye_interval_max_ms=stat_eye_interval_max,
                 eye_known=eyes.known,
                 mouth_raw=mouth.raw,eye_us=eyes.elapsed_us,validation=validation is not None,
                 mouth_us=mouth.elapsed_us,source_hash_repeats=None,display_submissions=display_submissions,
                 webcam_submitted=stat_webcam_submitted,webcam_errors=stat_webcam_errors,
                 webcam_ms=round(stat_webcam_us/(1000*stat_count),2),
                 display_mode='center' if center_frame else ('debug' if debug else 'overlay'),
                 character_view=character.view,character_yaw=round(character.yaw,2),
                 character_pitch=round(character.pitch,2),heap=heap())
            stats_t=end;stat_count=stat_faces=stat_max=stat_mouth_known=0
            stat_parts=[0,0,0,0,0];stat_eyes={};stat_mouth={};stat_mouth_updates=0
            stat_eye_updates=stat_eye_interval_max=0
            stat_webcam_submitted=stat_webcam_errors=stat_webcam_us=0
        if validation_stop_at is not None and time.ticks_diff(end,validation_stop_at)>=0:
            emit('eye_validation_run_complete');break
except KeyboardInterrupt:
    emit('interrupted');raise
except Exception as exc:
    emit('error',detail=repr(exc));sys.print_exception(exc);raise
finally:
    if uvc is not None:uvc.reset()
    if button:button.irq(handler=None)
    if mouth:mouth.deinit()
    if eyes:eyes.deinit()
    if det:det.deinit()
    if lcd:lcd.deinit()
    sensor.shutdown();gc.collect();emit('stopped',heap=heap())
