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


def lower_lip_edge(frame, x, y, dx, dy, tangent, upper, inner, outer):
    """Locate a sustained dark cavity followed by the brighter lower lip."""
    first = max(-12, round(upper * 40) + 1)
    start = max(first + 3, round(inner * 40) + 1)
    # PFLD can underpredict the outer lip too. Allow the search a small
    # overrun, using the inner/outer coordinates only to bound the work.
    stop = min(16, round(inner * 40) + 8, round(outer * 40) + 3)
    if start > stop:
        return None
    levels = []
    width, height = frame.width(), frame.height()
    for row in range(first, stop + 4):
        normal = row / 40
        level = 0
        for lane in (tangent - .035, tangent, tangent + .035):
            px = round(x + dx * lane - dy * normal)
            py = round(y + dy * lane + dx * normal)
            if not (0 <= px < width and 0 <= py < height):
                return None
            r, g, b = frame.get_pixel(px, py)
            level += r + 2 * g + b
        levels.append(level)
    edges = []
    for row in range(start, stop + 1):
        i = row - first
        dark = levels[i-3:i]
        bright = levels[i+1:i+4]
        strength = sum(bright) - sum(dark)
        if strength >= 27 * 35 and min(bright) - sorted(dark)[1] >= 12 * 11:
            edges.append((row, strength))
    if not edges:
        return None
    peak = max(strength for _, strength in edges)
    return next(row / 40 for row, strength in edges if strength >= .68 * peak)


def visible_mouth_gap(frame, points, crop, gap):
    """Estimate additional aperture only when three cavity profiles agree."""
    if gap < .075:
        return None
    x, y, side = crop
    ax, ay = points[0]
    bx, by = points[9]
    dx, dy = bx - ax, by - ay
    span2 = dx * dx + dy * dy
    if span2 * side * side < 24 ** 2:
        return None
    edges = []
    shifts = []
    for upper, lower, outer in ((14, 2, 4), (10, 8, 1), (18, 5, 7)):
        ux, uy = points[upper][0] - ax, points[upper][1] - ay
        lx, ly = points[lower][0] - ax, points[lower][1] - ay
        ox, oy = points[outer][0] - ax, points[outer][1] - ay
        tangent = ((ux + lx) * dx + (uy + ly) * dy) / (2 * span2)
        upper_n = (uy * dx - ux * dy) / span2
        inner_n = (ly * dx - lx * dy) / span2
        outer_n = (oy * dx - ox * dy) / span2
        edge = lower_lip_edge(frame, x + ax * side, y + ay * side,
                              dx * side, dy * side, tangent, upper_n, inner_n, outer_n)
        if edge is None:
            return None
        edges.append(edge)
        shifts.append(edge - inner_n)
    # A one-sided shadow or obstruction can create a strong edge, but its
    # three lower boundaries do not usually form one coherent lip line.
    if (max(edges) - min(edges) > .0625 or min(shifts) < .009
            or max(shifts) - min(shifts) > .09):
        return None
    return gap + min(.15, sum(shifts) / len(shifts))


def cavity_width(frame, x, y, dx, dy, tangent, normal):
    """Measure a dark band between brighter regions in the source image."""
    levels = []
    step = 1 / 50
    first = round(normal / step) - 13
    width, height = frame.width(), frame.height()
    for row in range(first, first + 27):
        offset = row * step
        level = 0
        for lane in (tangent - .032, tangent, tangent + .032):
            px = round(x + dx * lane - dy * offset)
            py = round(y + dy * lane + dx * offset)
            if not (0 <= px < width and 0 <= py < height):
                return 0.
            r, g, b = frame.get_pixel(px, py)
            level += r + 2 * g + b
        levels.append(level)
    valley = min(range(5, 22), key=lambda i: levels[i])
    floor = levels[valley]
    contrast = min(max(levels[:valley - 1]), max(levels[valley + 2:])) - floor
    if contrast < 12 * 40:
        return 0.
    cutoff = floor + .55 * contrast
    lo = hi = valley
    while lo > 0 and levels[lo - 1] < cutoff:
        lo -= 1
    while hi < 26 and levels[hi + 1] < cutoff:
        hi += 1
    if lo == 0 or hi == 26:
        return 0.
    top = (cutoff - levels[lo]) / (levels[lo - 1] - levels[lo])
    bottom = (cutoff - levels[hi]) / (levels[hi + 1] - levels[hi])
    return (hi - lo + top + bottom) * step


def continuous_mouth_gap(frame, points, crop, gap):
    """Use visible cavity evidence to recover compressed mid openings."""
    if not .034 < gap < .156:
        return gap
    x, y, side = crop
    ax, ay = points[0]
    bx, by = points[9]
    dx, dy = bx - ax, by - ay
    span2 = dx * dx + dy * dy
    if dx <= 0. or span2 * side * side < 26 ** 2:
        return gap
    widths = []
    for upper, lower in ((14, 2), (10, 8), (18, 5)):
        u = (points[upper][0] + points[lower][0]) * .5 - ax
        v = (points[upper][1] + points[lower][1]) * .5 - ay
        tangent = (u * dx + v * dy) / span2
        normal = (v * dx - u * dy) / span2
        widths.append(cavity_width(frame, x + ax * side, y + ay * side,
                                   dx * side, dy * side, tangent, normal))
    narrow, middle, wide = sorted(widths)
    if middle < .060 or narrow < .035 or min(middle - narrow, wide - middle) > .055:
        return gap
    confidence = min(1., (middle - .060) / .042)
    extension = confidence * max(0., 1.25 * middle - gap)
    # Let the evidence contribute progressively near the closed lip seam.
    # Cap the correction so a single changing shadow cannot produce a full jaw.
    return gap + min(.05, 4. * (gap - .034), .156 - gap, extension)
