"""Project the aligned v47 artwork onto one approximate depth surface offline."""
import argparse
import json
import math
from pathlib import Path
import zlib

import numpy as np
from PIL import Image, ImageDraw, features
from scipy.ndimage import map_coordinates
from scipy.interpolate import RBFInterpolator
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'evidence' / 'visual-v47'
OUT = ROOT / 'assets' / 'kitten-rig'
SIZE = 104
SUPERSAMPLE = 2
YAW = (-32, -16, 0, 16, 32)
PITCH = (-24, 0, 24)


def depth(x, y):
    dome = .43 * np.exp(-1.8 * (x / .84)**2 - 1.35 * ((y + .09) / .74)**2)
    muzzle = .075 * np.exp(-(x / .28)**2 - ((y + .27) / .19)**2)
    return dome + muzzle - .14


def sources(side=False):
    size = 512
    directory = ROOT / 'evidence' / 'visual-v48' if side else ART
    op,cl = ('side-master.png','side-closed.png') if side else ('front-master.png','closed-master.png')
    base = np.asarray(Image.open(directory / op).convert('RGB').resize((size,size)))
    closed = np.asarray(Image.open(directory / cl).convert('RGB').resize((size,size)))
    y, x = np.mgrid[0:size, 0:size] / (size - 1)
    alpha = np.clip((base.max(axis=2).astype(float) - 8.) / 25., 0., 1.) * 255.
    base = np.dstack((base, alpha)).astype(np.uint8)
    lids = []
    bounds = ((.165,.257,.415,.602),(.310,.559,.411,.611)) if side else (
        (.225,.452,.405,.600),(.544,.772,.405,.600))
    for left,right,top,bottom in bounds:
        edge = .022
        mask = np.minimum.reduce(((x-left)/edge,(right-x)/edge,(y-top)/edge,(bottom-y)/edge))
        mask = np.clip(mask, 0., 1.)
        mask = mask*mask*(3-2*mask)
        lids.append(np.dstack((closed, mask*255.)).astype(np.uint8))
    return base, lids


def projection(yaw,pitch,surface=depth,size=SIZE):
    a, b = math.radians(yaw), math.radians(pitch)
    cy, sy, cp, sp = math.cos(a), math.sin(a), math.cos(b), math.sin(b)
    matrix = np.array(((cy, 0., sy), (sp*sy, cp, -sp*cy)))
    inverse = np.linalg.inv(matrix[:, :2])
    z_axis = inverse @ matrix[:, 2]
    grid = (np.arange(size * SUPERSAMPLE) + .5) * (2 / (size * SUPERSAMPLE)) - 1.
    x, y = np.meshgrid(grid, -grid)
    fx = inverse[0,0]*x + inverse[0,1]*y
    fy = inverse[1,0]*x + inverse[1,1]*y
    u, v = fx, fy
    for _ in range(14):
        z = surface(u,v)
        u, v = fx-z*z_axis[0], fy-z*z_axis[1]
    return np.stack(((1-v)*.5, (1+u)*.5))


def warp(image, coords, size=SIZE):
    src = image.astype(float)
    src[:,:,:3] *= src[:,:,3:4] / 255.
    dst = np.stack([map_coordinates(src[:,:,i], coords*(image.shape[0]-1),
                                    order=1, mode='constant', cval=0., prefilter=False)
                    for i in range(4)], axis=-1)
    dst[:,:,:3] *= 255./np.maximum(1.,dst[:,:,3:4])
    return Image.fromarray(np.uint8(np.clip(dst,0,255)), 'RGBA').resize((size,size), Image.Resampling.LANCZOS)



# Correspondences in source UV: ear tips and bases, crown and cheek contours,
# corners of both eye openings, nose, closed smile and chin. Intermediate
# views align these features before mixing colors to avoid duplicate edges.
FRONT_GUIDES = np.array([
    [.179,.094],[.825,.094],[.366,.225],[.598,.226],
    [.116,.39],[.878,.39],[.124,.605],[.875,.605],
    [.23,.756],[.784,.755],[.50,.851],
    [.257,.516],[.425,.555],[.341,.432],[.340,.578],
    [.566,.552],[.738,.519],[.658,.435],[.657,.580],
    [.500,.607],[.501,.675],[.420,.651],[.576,.654],
])
SIDE_GUIDES = np.array([
    [.249,.149],[.743,.079],[.392,.220],[.518,.225],
    [.207,.343],[.840,.385],[.145,.603],[.893,.604],
    [.236,.759],[.804,.755],[.480,.860],
    [.193,.513],[.242,.550],[.215,.443],[.213,.577],
    [.338,.551],[.526,.526],[.431,.440],[.427,.587],
    [.231,.607],[.253,.675],[.194,.654],[.317,.655],
])
BORDER = np.array(((0,0),(1,0),(0,1),(1,1),(.5,0),(.5,1),(0,.5),(1,.5)))


def register(landmarks,target):
    grid=np.mgrid[0:512,0:512].reshape(2,-1).T/(512-1)
    uv=RBFInterpolator(np.vstack((target,BORDER)),np.vstack((landmarks,BORDER)),
                       kernel='thin_plate_spline',smoothing=.00025)(grid[:,::-1])
    return uv[:,::-1].T.reshape(2,512,512)


def sample(source,coordinates):
    a=source.astype(float)
    a[:,:,:3]*=a[:,:,3:4]/255.
    return np.stack([map_coordinates(a[:,:,i],coordinates*(source.shape[0]-1),
                                     order=1,mode='constant',cval=0.,prefilter=False)
                     for i in range(4)],axis=-1)


def intermediate(front,side,refine_contour=False):
    guides=(FRONT_GUIDES+SIDE_GUIDES)*.5
    frontal,profile=register(FRONT_GUIDES,guides),register(SIDE_GUIDES,guides)
    if refine_contour:
        v,u=np.mgrid[0:512,0:512]/511.

        def feather(value):
            value=np.clip(value,0.,1.)
            return value*value*(3.-2.*value)

        # The far eye and temple use one registered image. Blending a
        # second silhouette through the eye creates a stray contour.
        far=feather((.44-u)/.13)*feather((.67-v)/.12)
        # Keep the near ear and cheek on one registered rim through their
        # entire junction. The vertical fades start away from the notch;
        # the horizontal fade falls inside the opaque fur.
        near=feather((u-.72)/.11)*feather((v-.16)/.125)*feather((.84-v)/.13)
    output=[]
    for a,b in zip(front,side):
        first,second=sample(a,frontal),sample(b,profile)
        if refine_contour:
            profile_weight=(.5*(1.-far)*(1.-near)+near)[:,:,None]
            p=first*(1.-profile_weight)+second*profile_weight
            coverage=first[:,:,3]*(1.-near)+second[:,:,3]*near
        else:
            p=(first+second)*.5
            coverage=first[:,:,3]
        p[:,:,:3]*=255./np.maximum(1.,p[:,:,3:4])
        p[:,:,3]=coverage
        output.append(np.uint8(np.clip(p,0,255)))
    return output


def full_views(refine_contour=False):
    plate, lids=sources()
    front=[plate]+lids
    plate,lids=sources(side=True)
    side=[plate]+lids
    mid=intermediate(front,side,refine_contour)

    def reflected(layers):
        mirrored=[]
        for src in (layers[0],layers[2],layers[1]):
            im=src[:,::-1].copy()
            # Restore a modest left-to-right light bias after mirroring.
            ramp=np.linspace(1.06,.96,im.shape[1])
            im[:,:,:3]=np.minimum(255,im[:,:,:3].astype(float)*ramp[None,:,None]).astype(np.uint8)
            mirrored.append(im)
        return mirrored

    return [side,mid,front,reflected(mid),reflected(side)]


def lift_nose(layers, nose_u, amount):
    """Lift the nose and lower bridge while holding the lip and eye edges."""
    if not amount:
        return layers
    size = layers[0].shape[0]
    v, u = np.mgrid[0:size, 0:size] / (size - 1)
    edge = np.clip((.105 - np.abs(u - nose_u)) / .061, 0., 1.)
    edge = edge * edge * (3. - 2. * edge)
    old_v = np.interp(v, (.51, .587 - amount, .623 - amount, .658),
                      (.51, .587, .623, .658))
    moved = (v > .51) & (v < .658) & (edge > 0.)
    v[moved] += (old_v[moved] - v[moved]) * edge[moved]
    coordinates = np.stack((v[moved], u[moved]))
    result = []
    for layer in layers:
        adjusted = layer.copy()
        pixels = sample(layer, coordinates)
        pixels[:, :3] *= 255. / np.maximum(1., pixels[:, 3:4])
        adjusted[moved] = np.uint8(np.clip(pixels, 0., 255.))
        result.append(adjusted)
    return result


def pitch_surface(nose_x, rise=0.):
    def surface(x,y):
        nose=.095*np.exp(-((x-nose_x)/.18)**2-((y+.22-rise)/.18)**2)
        return depth(x,y)*1.17+nose
    return surface

def smile():
    img = Image.new('RGBA',(128,128))
    draw = ImageDraw.Draw(img)
    polygon=[(3,24),(23,14),(45,16),(64,26),(83,17),(106,15),(124,25),
             (116,53),(103,83),(86,106),(64,116),(43,108),(24,83),(11,54)]
    draw.polygon(polygon,fill=(106,47,39,255))
    draw.polygon([(12,27),(32,20),(64,32),(95,22),(116,28),(109,56),(94,84),
                  (79,105),(51,105),(33,87),(20,57)],fill=(58,23,23,255))
    draw.ellipse((31,70,97,107),fill=(220,101,109,255))
    draw.ellipse((43,74,79,91),fill=(240,135,137,255))
    return img.resize((32,32),Image.Resampling.LANCZOS)


def build(volume=False, raised_nose=False, refine_contour=False, hd=False):
    size=208 if hd else SIZE
    pitches=(0,) if hd else PITCH
    raw = bytearray()
    textures = []
    method = Image.Quantize.LIBIMAGEQUANT if features.check_feature('libimagequant') else Image.Quantize.FASTOCTREE

    def quantize(image, colors):
        q = image.quantize(colors=colors,method=method,dither=Image.Dither.NONE)
        palette = np.zeros((256,4),dtype=np.uint8)
        indices = np.asarray(q).ravel()
        pixels = np.asarray(image).reshape(-1,4)
        # Refit each occupied index to its own source pixels to avoid
        # saturated representatives around transparent fur edges.
        for i in np.unique(indices):
            palette[i] = np.median(pixels[indices==i],axis=0)
        palette[:,3] = np.where(palette[:,3]>=248,255,np.where(palette[:,3]<=7,0,palette[:,3]))
        rgb = ((palette[:,0].astype('uint16')>>3)<<11)|((palette[:,1].astype('uint16')>>2)<<5)|(palette[:,2].astype('uint16')>>3)
        return q,rgb.astype('<u2').tobytes()+palette[:,3].tobytes()

    def group(tiles,colors,replacements=None):
        # Atlas only exists in the offline bake. Its index map is split back
        # into the compact per-view tiles, all sharing one on-device palette.
        stride=max(im.width for _,im,_,_ in tiles)
        height=max(im.height for _,im,_,_ in tiles)
        columns=min(5,len(tiles))
        atlas=Image.new('RGBA',(stride*columns,height*math.ceil(len(tiles)/columns)))
        for i,(_,im,_,_) in enumerate(tiles):
            atlas.paste(im,(i%columns*stride,i//columns*height))
        q,colors_data=quantize(atlas,colors)
        if replacements:
            # Keep the v54 palette and every unaffected pixel. Refit only
            # the corrected parts of the intermediate yaw tiles.
            words=np.frombuffer(colors_data[:512],dtype='<u2')
            alpha=np.frombuffer(colors_data[512:],dtype=np.uint8)
            palette=np.stack(((words>>11)*255./31,((words>>5)&63)*255./63,
                              (words&31)*255./31,alpha),axis=1)

            def premultiplied(rgba):
                adjusted=rgba.astype(float)
                adjusted[..., :3]*=adjusted[..., 3:4]/255.
                return adjusted

            lookup=cKDTree(premultiplied(palette))
            transparent=int(alpha.argmin())
        first=len(textures)
        result=[]
        for i,(name,im,left,top) in enumerate(tiles):
            x,y=i%columns*stride,i//columns*height
            offset=len(raw)
            indexes=q.crop((x,y,x+im.width,y+im.height))
            if replacements and i in replacements:
                updated=replacements[i]
                _,new_im,new_left,new_top=tile(name,updated)
                old_rgba=Image.new('RGBA',(size,size))
                old_rgba.paste(im,(left,top))
                old_indices=Image.new('L',(size,size),transparent)
                # P-to-L paste converts palette colors to luminance.
                # Preserve the raw index bytes across the crop change.
                old_indices.paste(Image.fromarray(np.asarray(indexes)),(left,top))
                bounds=(new_left,new_top,new_left+new_im.width,new_top+new_im.height)
                pixels=np.asarray(new_im)
                changed=np.any(pixels!=np.asarray(old_rgba.crop(bounds)),axis=-1)
                indices=np.array(old_indices.crop(bounds))
                indices[changed]=lookup.query(premultiplied(pixels[changed]))[1]
                indexes=Image.fromarray(indices)
                im,left,top=new_im,new_left,new_top
            raw.extend(indexes.tobytes())
            if i==0:
                raw.extend(colors_data)
            meta=dict(id=name,w=im.width,h=im.height,offset=offset,bytes=len(raw)-offset)
            if i:
                meta['palette_ref']=first
            result.append([len(textures),left,top])
            textures.append(meta)
        return result

    def tile(name,image):
        bounds=image.getchannel('A').point(lambda a:255 if a>10 else 0).getbbox()
        return name,image.crop(bounds),bounds[0],bounds[1]

    plate,lids=sources()
    artwork=full_views() if volume else None
    corrected=full_views(True) if refine_contour else None
    nose_rise=(0.,.013,.031,.013,0.) if raised_nose else (0.,)*5
    if artwork and raised_nose:
        centers=(SIDE_GUIDES[19,0],(SIDE_GUIDES[19,0]+FRONT_GUIDES[19,0])*.5,.5,
                 1-(SIDE_GUIDES[19,0]+FRONT_GUIDES[19,0])*.5,1-SIDE_GUIDES[19,0])
        artwork=[lift_nose(layers, u, rise) for layers,u,rise in zip(artwork,centers,nose_rise)]
        if corrected:
            corrected=[lift_nose(layers, u, rise) for layers,u,rise in zip(corrected,centers,nose_rise)]
    mouth_views=[]
    heads=[]
    eyes=[]
    corrected_heads={}
    corrected_eyes={}
    sheet=Image.new('RGB',(size*len(YAW),size*len(pitches)))
    for i,pitch in enumerate(pitches):
        mouth_row=[]
        for j,yaw in enumerate(YAW):
            if artwork:
                plate=artwork[j][0]
                lids=artwork[j][1:]
                mouth_uv=((.254,.674),(.377,.674),(.500,.675),(.623,.674),(.746,.674))[j]
                x,y=2*mouth_uv[0]-1,1-2*mouth_uv[1]
                surface=pitch_surface(x,2*nose_rise[j])
                coords=projection(0,pitch,surface,size)
                rad=math.radians(pitch)
                mouth_row.append([x,y*math.cos(rad)-float(surface(x,y))*math.sin(rad),
                                  (0.72,0.89,1.,.89,.72)[j]])
            else:
                coords=projection(yaw,pitch,size=size)
            frame=warp(plate,coords,size)
            sheet.paste(frame,(j*size,i*size),frame)
            if yaw==0 and pitch==0:
                frame.save(OUT/'head.png')
            if corrected and abs(yaw)==16:
                corrected_heads[len(heads)]=warp(corrected[j][0],coords,size)
                corrected_eyes.update({len(eyes)+side:warp(layer,coords,size)
                                       for side,layer in enumerate(corrected[j][1:])})
                revised=corrected_heads[len(heads)]
                sheet.paste((0,0,0),(j*size,i*size,(j+1)*size,(i+1)*size))
                sheet.paste(revised,(j*size,i*size),revised)
            heads.append(tile('shell_%+d_%+d'%(yaw,pitch),frame))
            eyes.extend(tile('lid_%d_%+d_%+d'%(side,yaw,pitch),warp(layer,coords,size))
                        for side,layer in enumerate(lids))
        if artwork:
            mouth_views.append(mouth_row)
    head_tiles=group(heads,256,corrected_heads)
    eye_tiles=group(eyes,256,corrected_eyes)
    head_views=[head_tiles[i:i+len(YAW)] for i in range(0,len(head_tiles),len(YAW))]
    pairs=[eye_tiles[i:i+2] for i in range(0,len(eye_tiles),2)]
    lid_views=[pairs[i:i+len(YAW)] for i in range(0,len(pairs),len(YAW))]

    art=smile()
    art.save(OUT/'mouth_open.png')
    mouth=group([('mouth_open',art,0,0)],128)[0][0]
    zero = [0,0,0]
    bones = [
        dict(id='head',parent=-1,position=zero,motion='head_yaw'),
        dict(id='jaw',parent=0,position=[0,-.30,.10],motion='jaw_hinge'),
        dict(id='eye_left',parent=0,position=zero,motion='left_lid'),
        dict(id='eye_right',parent=0,position=zero,motion='right_lid'),
        dict(id='muzzle',parent=0,position=zero),
        dict(id='nose',parent=4,position=zero),
    ]
    mouth_x,mouth_y=.001,-.322
    attachments = [dict(texture=mouth,bone=1,visible='mouth_open',
                        offset=[mouth_x,mouth_y+.30,float(depth(mouth_x,mouth_y))-.1],
                        size=[.365,.285])]
    sheet.save(OUT/'skin-sheet.png')
    packed = zlib.compress(raw,9)
    meta = dict(name='Mikan',schema=1,renderer='projected_art_with_expression_rig',bones=bones,textures=textures,
                attachments=attachments,head_views=head_views,lid_views=lid_views,
                pack_bytes=len(packed),decoded_bytes=len(raw),pack_codec='zlib',
                yaw_limit_deg=32,jaw_angle_deg=6,asset_pose_count=len(YAW)*len(pitches))
    if hd:
        meta.update(texture_size=size,neutral_pitch_row=0)
    if volume:
        meta['art_mouth_views']=mouth_views
        if raised_nose:
            # Screen-space lip tangent per authored yaw view, from the
            # short far side to the long near side of the closed lip line.
            meta['art_mouth_slopes']=[-.23,-.17,0.,.17,.23]
    (OUT/'kitten-rig.pack').write_bytes(packed)
    (OUT/'kitten-rig.json').write_text(json.dumps(meta,separators=(',',':'))+'\n')
    print(len(packed),len(raw),len(textures))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--volume',action='store_true')
    parser.add_argument('--lift-nose',action='store_true')
    parser.add_argument('--refine-contour',action='store_true')
    parser.add_argument('--hd',action='store_true')
    args=parser.parse_args()
    if args.lift_nose and not args.volume:
        parser.error('--lift-nose needs --volume')
    if args.refine_contour and not args.lift_nose:
        parser.error('--refine-contour needs --lift-nose')
    if args.hd and not args.refine_contour:
        parser.error('--hd needs --refine-contour')
    build(args.volume,args.lift_nose,args.refine_contour,args.hd)
