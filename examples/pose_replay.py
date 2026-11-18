import display,image,json,sensor,sys,time,uvc
ROOT='/flash/memoji-camera'
if ROOT not in sys.path:sys.path.insert(0,ROOT)
from kitten_rig import KittenRig

screen=display.ESP32Display()
rig=KittenRig(ROOT)
canvas=image.Image(320,320,sensor.RGB565)
webcam=image.Image(320,240,sensor.RGB565)
webcam.clear()
uvc.set_frame(webcam)
try:
    import hashlib
    for yaw in (-12.,12.):
        marks=((60,25),(140,25),(100+80*yaw/90,56.2),(75,80),(125,80))
        variants=set()
        for values in ((0.,0.,0.),(1.,0.,0.),(0.,1.,0.),(0.,0.,.7)):
            canvas.clear()
            rig.yaw=yaw
            rig.draw(canvas,(22,22,84,87),values,marks,pixel_scale=2.5)
            variants.add(hashlib.sha256(canvas.bytearray()).digest())
        assert len(variants)==4
    print('V59_EXPRESSIONS_PASS')
    rig.yaw=0.
    canvas.clear()
    screen.clear()
    print('REPLAY_ARMED',json.dumps(uvc.get_mode()))
    start=time.ticks_ms()
    while not uvc.is_streaming():
        if time.ticks_diff(time.ticks_ms(),start)>12000:
            raise RuntimeError('No UVC client')
        time.sleep_ms(40)
    # Known yaw and neutral pitch through the production landmark-to-pose
    # path. Hold at the ends so the oscillator settles before reversing.
    path=[0]*5+list(range(0,37,2))+[36]*4+list(range(36,-37,-2))+[-36]*4+list(range(-36,1,2))+[0]*5
    yaw_columns=set()
    for idx,target in enumerate(path,1):
        started=time.ticks_ms()
        points=[(60,25),(140,25),(100+80*target/90,25+80*.39),(75,80),(125,80)]
        canvas.clear()
        rig.draw(canvas,(22,22,84,87),(0.,0.,.7),points,pixel_scale=2.5)
        for bit in range(8):
            if idx&(1<<bit):
                canvas.draw_rectangle(16+bit*20,302,12,12,color=(255,255,255),fill=True)
        screen.write(canvas,x=80,y=80,fit=False)
        webcam.clear()
        webcam.draw_image(canvas,80,40,x_scale=.5,y_scale=.5,hint=image.AREA)
        submitted=False
        try:
            submitted=uvc.write(webcam.to_jpeg(quality=45,copy=True))
        except (OSError,MemoryError,ValueError):
            pass
        yaw_columns.add(rig.shell_col)
        print('REPLAY',json.dumps([idx,target,round(rig.yaw,3),rig.shell_col,submitted,rig.pose_index,rig.pose_mirrored]))
        delay=220-time.ticks_diff(time.ticks_ms(),started)
        if delay>0:time.sleep_ms(delay)
    assert yaw_columns=={0,1,2,3,4},yaw_columns
    print('REPLAY_PASS',len(path))
    time.sleep_ms(700)
finally:
    uvc.reset()
    screen.deinit()
