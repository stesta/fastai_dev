#AUTOGENERATED! DO NOT EDIT! File to edit: dev/08_vision_augment.ipynb (unless otherwise specified).

__all__ = ['RandTransform', 'PILFlip', 'PILDihedral', 'clip_remove_empty', 'CropPad', 'RandomCrop', 'Resize',
           'RandomResizedCrop', 'AffineCoordTfm', 'affine_mat', 'mask_tensor', 'flip_mat', 'Flip', 'dihedral_mat',
           'Dihedral', 'rotate_mat', 'Rotate', 'zoom_mat', 'Zoom', 'find_coeffs', 'apply_perspective', 'Warp', 'logit',
           'LightingTfm', 'Brightness', 'setup_aug_tfms', 'aug_transforms']

from ..imports import *
from ..test import *
from ..core import *
from ..data.pipeline import *
from ..data.source import *
from ..data.core import *
from .core import *
from ..data.external import *
from ..notebook.showdoc import show_doc

from torch import stack, zeros_like as t0, ones_like as t1
from torch.distributions.bernoulli import Bernoulli

@docs
class RandTransform(Transform):
    "A transform that randomize its state at each `__call__`, only applied on the training set"
    filt=0
    def __init__(self, encodes=None, decodes=None, randomize=None, p=1.):
        self.p = p
        if randomize is not None: self.randomize=randomize
        super().__init__(encodes, decodes)

    def randomize(self, b): self.do = random.random() < self.p

    def __call__(self, b, filt=None, **kwargs):
        self.randomize(b) #Randomize before calling
        if not getattr(self, 'do', True): return b
        return super().__call__(b, filt=filt, **kwargs)

    _docs = dict(randomize="Randomize the state for input `b`")

def _minus_axis(x, axis):
    x[...,axis] = -x[...,axis]
    return x

class PILFlip(RandTransform):
    "Randomly flip with probability `p`"
    def __init__(self, p=0.5): self.p = p
    def encodes(self, x:PILImage):    return x.transpose(PIL.Image.FLIP_LEFT_RIGHT)
    def encodes(self, x:TensorPoint): return _minus_axis(x, 0)
    def encodes(self, x:TensorBBox):
        bb,lbl = x
        bb = _minus_axis(bb.view(-1,2), 0)
        return (bb.view(-1,4),lbl)

class PILDihedral(RandTransform):
    "Applies any of the eight dihedral transformations with probability `p`"
    def __init__(self, p=0.5, draw=None): self.p,self.draw = p,draw
    def randomize(self, b):
        super().randomize(b)
        if self.draw is None: self.idx = random.randint(0,7)
        else: self.idx = self.draw() if isinstance(self.draw, Callable) else self.draw

    def encodes(self, x:PILImage): return x if self.idx==0 else x.transpose(self.idx-1)
    def encodes(self, x:TensorPoint):
        if self.idx in [1, 3, 4, 7]: x = _minus_axis(x, 0)
        if self.idx in [2, 4, 5, 7]: x = _minus_axis(x, 1)
        if self.idx in [3, 5, 6, 7]: x = x.flip(1)
        return x

    def encodes(self,  x:TensorBBox):
        pnts = self._get_func(self.encodes, TensorPoint)(x[0].view(-1,2)).view(-1,2,2)
        tl,br = pnts.min(dim=1)[0],pnts.max(dim=1)[0]
        return [torch.cat([tl, br], dim=1), x[1]]

def clip_remove_empty(bbox, label):
    "Clip bounding boxes with image border and label background the empty ones."
    bbox = torch.clamp(bbox, -1, 1)
    empty = ((bbox[...,2] - bbox[...,0])*(bbox[...,3] - bbox[...,1]) < 0.)
    if isinstance(label, torch.Tensor): label[empty] = 0
    else: label = [0 if m else l for l,m in zip(label,empty)]
    return [bbox, label]

from torchvision.transforms.functional import pad as tvpad

mk_class('pad_mode', **{o:o for o in ['zeros', 'border', 'reflection']},
         doc="All possible padding mode as attributes to get tab-completion and typo-proofing")

class CropPad(Transform):
    "Center crop or pad an image to `size`"
    order = 5
    _pad_modes = {'zeros': 'constant', 'border': 'edge', 'reflection': 'reflect'}
    def __init__(self, size, pad_mode=pad_mode.zeros):
        if isinstance(size,int): size=(size,size)
        self.size,self.pad_mode = (size[1],size[0]),self._pad_modes[pad_mode]

    def randomize(self, b, filt):
        self.orig_size = (b[0] if isinstance(b, tuple) else b).size
        self.tl = ((self.orig_size[0]-self.size[0])//2, (self.orig_size[1]-self.size[1])//2)

    def __call__(self, b, filt=None, **kwargs):
        self.randomize(b, filt) #Randomize before calling
        return super().__call__(b, filt=filt, **kwargs)

    def _crop_pad(self, x, mode=Image.BILINEAR):
        if self.tl[0] > 0 or self.tl[1] > 0:
            cw,ch = int(max(self.tl[0],0)),int(max(self.tl[1],0))
            fw, fh = int(min(cw+self.size[0], self.orig_size[0])),int(min(ch+self.size[1], self.orig_size[1]))
            x = x.crop((cw, ch, fw, fh))
        if self.tl[0] < 0 or self.tl[1] < 0:
            pw,ph = int(max(-self.tl[0],0)),int(max(-self.tl[1],0))
            fw, fh = int(max(self.size[0]-self.orig_size[0]-pw,0)),int(max(self.size[1]-self.orig_size[1]-ph,0))
            x = tvpad(x, (pw, ph, fw, fh), padding_mode=self.pad_mode)
        if getattr(self, 'final_sz', False): x = x.resize(self.final_sz, mode)
        return x

    def encodes(self, x:PILImage): return self._crop_pad(x, getattr(self, 'mode', Image.BILINEAR))
    def encodes(self, x:Mask):     return self._crop_pad(x, getattr(self, 'mode_mask', Image.NEAREST))

    def encodes(self, x:TensorPoint):
        old_sz,new_sz,tl = map(lambda o: tensor(o).float(), (self.orig_size,self.size,self.tl))
        return (x + 1) * old_sz/new_sz - tl * 2/new_sz - 1

    def encodes(self, x:TensorBBox):
        bbox,label = x
        bbox = self._get_func(self.encodes, TensorPoint)(bbox.view(-1,2)).view(-1,4)
        return clip_remove_empty(bbox, label)

class RandomCrop(CropPad):
    "Ramdomly crop an image to `size`"
    def __init__(self, size): super().__init__(size)

    def randomize(self, b, filt):
        w,h = (b[0] if isinstance(b, tuple) else b).size
        self.orig_size = (w,h)
        if filt: self.tl = ((w-self.size[0])//2, (h-self.size[1])//2)
        else: self.tl = (random.randint(0,w-self.size[0]), random.randint(0,h-self.size[1]))

mk_class('resize_method', **{o:o for o in ['squish', 'crop', 'pad']},
         doc="All possible resize method as attributes to get tab-completion and typo-proofing")

class Resize(CropPad):
    order=10
    "Resize image to `size` using `method`"
    def __init__(self, size, method=resize_method.squish, pad_mode=pad_mode.reflection,
                 resamples=(Image.BILINEAR, Image.NEAREST)):
        super().__init__(size, pad_mode=pad_mode)
        self.final_sz,self.raw_sz,self.method = self.size,size,method
        self.mode,self.mode_mask = resamples

    def randomize(self, b, filt):
        w,h = (b[0] if isinstance(b, tuple) else b).size
        self.orig_size = (w,h)
        if self.method==resize_method.squish: self.tl,self.size = (0,0),(w,h)
        elif self.method==resize_method.pad:
            m = w/self.final_sz[0] if w/self.final_sz[0] > h/self.final_sz[1] else h/self.final_sz[1]
            self.size = (m*self.final_sz[0],m*self.final_sz[1])
            self.tl = ((w-self.size[0])//2, (h-self.size[1])//2)
        else:
            m = w/self.final_sz[0] if w/self.final_sz[0] < h/self.final_sz[1] else h/self.final_sz[1]
            self.size = (m*self.final_sz[0],m*self.final_sz[1])
            if filt: self.tl = ((w-self.size[0])//2, (h-self.size[1])//2)
            else: self.tl = (random.randint(0,w-self.size[0]), random.randint(0,h-self.size[1]))

class RandomResizedCrop(CropPad):
    "Picks a random scaled crop of an image and resize it to `size`"
    def __init__(self, size, scale=(0.08, 1.0), ratio=(3/4, 4/3), resamples=(Image.BILINEAR, Image.NEAREST)):
        super().__init__(size)
        self.final_sz,self.scale,self.ratio = self.size,scale,ratio
        self.mode,self.mode_mask = resamples

    def randomize(self, b, filt):
        w,h = (b[0] if isinstance(b, tuple) else b).size
        self.orig_size = w,h
        for attempt in range(10):
            if filt: break
            area = random.uniform(*self.scale) * w * h
            ratio = math.exp(random.uniform(math.log(self.ratio[0]), math.log(self.ratio[1])))
            nw = int(round(math.sqrt(area * ratio)))
            nh = int(round(math.sqrt(area / ratio)))
            if nw <= w and nh <= h:
                self.size = (nw,nh)
                self.tl = random.randint(0,w-nw), random.randint(0,h - nh)
                return
        if w/h < self.ratio[0]:   self.size = (w, int(w/self.ratio[0]))
        elif w/h > self.ratio[1]: self.size = (int(h*self.ratio[1]), h)
        else:                     self.size = (w, h)
        self.tl = ((w-self.size[0])//2, (h-self.size[1])//2)

class AffineCoordTfm(RandTransform):
    "Combine and apply affine and coord transforms"
    order = 30
    def __init__(self, aff_fs=None, coord_fs=None, size=None, mode='bilinear', pad_mode='reflection'):
        self.aff_fs,self.coord_fs,self.mode,self.pad_mode = L(aff_fs),L(coord_fs),mode,pad_mode
        self.size = None if size is None else (size,size) if isinstance(size, int) else tuple(size)

    def randomize(self, b):
        if isinstance(b, tuple): b = b[0]
        self.do,self.mat = True,self._get_affine_mat(b)[:,:2]
        for t in self.coord_fs: t.randomize(b)

    def compose(self, tfm):
        "Compose `self` with another `AffineCoordTfm` to only do the interpolation step once"
        self.aff_fs   += tfm.aff_fs
        self.coord_fs += tfm.coord_fs

    def _get_affine_mat(self, x):
        aff_m = torch.eye(3, dtype=x.dtype, device=x.device)
        aff_m = aff_m.unsqueeze(0).expand(x.size(0), 3, 3)
        ms = [f(x) for f in self.aff_fs]
        ms = [m for m in ms if m is not None]
        for m in ms: aff_m = aff_m @ m
        return aff_m

    def encodes(self, x:TensorImage):
        if self.mat is None and len(self.coord_tfms)==0: return x
        bs = x.size(0)
        size = tuple(x.shape[-2:]) if self.size is None else size
        size = (bs,x.size(1)) + size
        coords = F.affine_grid(self.mat, size)
        coords = compose_tfms(coords, self.coord_fs)
        return F.grid_sample(x, coords, mode=self.mode, padding_mode=self.pad_mode)

    def encodes(self, x:TensorMask):
        old_mode = self.mode
        res = self._get_func(self.encodes, TensorImage)(x.float()[:,None]).long()[:,0]
        self.mode = old_mode
        return res

    def encodes(self, x:TensorPoint):
        x = compose_tfms(x, self.coord_fs, reverse=True, invert=True)
        return (x - self.mat[:,:,2].unsqueeze(1)) @ torch.inverse(self.mat[:,:,:2].transpose(1,2))

    def encodes(self, x:TensorBBox):
        bbox,label = x
        bs,n = bbox.shape[:2]
        pnts = stack([bbox[...,:2], stack([bbox[...,0],bbox[...,3]],dim=2),
                      stack([bbox[...,2],bbox[...,1]],dim=2), bbox[...,2:]], dim=2)
        pnts = self._get_func(self.encodes, TensorPoint)(pnts.view(bs, 4*n, 2))
        pnts = pnts.view(bs, n, 4, 2)
        tl,dr = pnts.min(dim=2)[0],pnts.max(dim=2)[0]
        return clip_remove_empty(torch.cat([tl, dr], dim=2), label)

def affine_mat(*ms):
    "Restructure length-6 vector `ms` into an affine matrix with 0,0,1 in the last line"
    return stack([stack([ms[0], ms[1], ms[2]], dim=1),
                  stack([ms[3], ms[4], ms[5]], dim=1),
                  stack([t0(ms[0]), t0(ms[0]), t1(ms[0])], dim=1)], dim=1)

def mask_tensor(x, p=0.5, neutral=0.):
    "Mask elements of `x` with `neutral` with probability `1-p`"
    if p==1.: return x
    if neutral != 0: x.add_(-neutral)
    mask = x.new_empty(*x.size()).bernoulli_(p)
    x.mul_(mask)
    return x.add_(neutral) if neutral != 0 else x

def flip_mat(x, p=0.5):
    "Return a random flip matrix"
    mask = mask_tensor(-x.new_ones(x.size(0)), p=p, neutral=1.)
    return affine_mat(mask,     t0(mask), t0(mask),
                      t0(mask), t1(mask), t0(mask))

def Flip(p=0.5, size=None, mode='bilinear', pad_mode='reflection'):
    "Randomly flip a batch of images with a probability `p`"
    return AffineCoordTfm(aff_fs=partial(flip_mat, p=p), size=size, mode=mode, pad_mode=pad_mode)

def _draw_mask(x, def_draw, draw=None, p=0.5, neutral=0.):
    if draw is None: draw=def_draw
    if isinstance(draw, Callable):
        res = x.new_empty(x.size(0))
        for i in range_of(res): res[i] = draw()
    elif is_listy(draw):
        test_eq(len(draw), x.size(0))
        res = tensor(draw, dtype=x.dtype, device=x.device)
    else: res = x.new_zeros(x.size(0)) + draw
    return mask_tensor(res, p=p, neutral=neutral)

def dihedral_mat(x, p=0.5, draw=None):
    "Return a random dihedral matrix"
    def _def_draw(): return random.randint(0,7)
    idx = _draw_mask(x, _def_draw, draw=draw, p=p).long()
    xs = tensor([1,-1,1,-1,-1,1,1,-1])[idx]
    ys = tensor([1,1,-1,1,-1,-1,1,-1])[idx]
    m0 = tensor([1,1,1,0,1,0,0,0])[idx]
    m1 = tensor([0,0,0,1,0,1,1,1])[idx]
    return affine_mat(xs*m0,  xs*m1,  t0(xs),
                      ys*m1,  ys*m0,  t0(xs)).float()
    mask = mask_tensor(-x.new_ones(x.size(0)), p=p, neutral=1.)

def Dihedral(p=0.5, draw=None, size=None, mode='bilinear', pad_mode='reflection'):
    "Apply a random dihedral transformation to a batch of images with a probability `p`"
    return AffineCoordTfm(aff_fs=partial(dihedral_mat, p=p, draw=draw), size=size, mode=mode, pad_mode=pad_mode)

def rotate_mat(x, max_deg=10, p=0.5, draw=None):
    "Return a random rotation matrix with `max_deg` and `p`"
    def _def_draw(): return random.uniform(-max_deg,max_deg)
    thetas = _draw_mask(x, _def_draw, draw=draw, p=p) * math.pi/180
    return affine_mat(thetas.cos(), thetas.sin(), t0(thetas),
                     -thetas.sin(), thetas.cos(), t0(thetas))

def Rotate(max_deg=10, p=0.5, draw=None, size=None, mode='bilinear', pad_mode='reflection'):
    "Apply a random rotation of at most `max_deg` with probability `p` to a batch of images"
    return AffineCoordTfm(partial(rotate_mat, max_deg=max_deg, p=p, draw=draw),
                          size=size, mode=mode, pad_mode=pad_mode)

def zoom_mat(x, max_zoom=1.1, p=0.5, draw=None, draw_x=None, draw_y=None):
    "Return a random zoom matrix with `max_zoom` and `p`"
    def _def_draw():     return random.uniform(1., max_zoom)
    def _def_draw_ctr(): return random.uniform(0.,1.)
    s = 1/_draw_mask(x, _def_draw, draw=draw, p=p, neutral=1.)
    col_pct = _draw_mask(x, _def_draw_ctr, draw=draw_x, p=1.)
    row_pct = _draw_mask(x, _def_draw_ctr, draw=draw_y, p=1.)
    col_c = (1-s) * (2*col_pct - 1)
    row_c = (1-s) * (2*row_pct - 1)
    return affine_mat(s,     t0(s), col_c,
                      t0(s), s,     row_c)

def Zoom(max_zoom=1.1, p=0.5, draw=None, draw_x=None, draw_y=None, size=None, mode='bilinear', pad_mode='reflection'):
    "Apply a random zoom of at most `max_zoom` with probability `p` to a batch of images"
    return AffineCoordTfm(partial(zoom_mat, max_zoom=max_zoom, p=p, draw=draw, draw_x=draw_x, draw_y=draw_y),
                          size=size, mode=mode, pad_mode=pad_mode)

def find_coeffs(p1, p2):
    "Find coefficients for warp tfm from `p1` to `p2`"
    m = []
    p = p1[:,0,0]
    #The equations we'll need to solve.
    for i in range(p1.shape[1]):
        m.append(stack([p2[:,i,0], p2[:,i,1], t1(p), t0(p), t0(p), t0(p), -p1[:,i,0]*p2[:,i,0], -p1[:,i,0]*p2[:,i,1]]))
        m.append(stack([t0(p), t0(p), t0(p), p2[:,i,0], p2[:,i,1], t1(p), -p1[:,i,1]*p2[:,i,0], -p1[:,i,1]*p2[:,i,1]]))
    #The 8 scalars we seek are solution of AX = B
    A = stack(m).permute(2, 0, 1)
    B = p1.view(p1.shape[0], 8, 1)
    return torch.solve(B,A)[0]

def apply_perspective(coords, coeffs):
    "Apply perspective tranfom on `coords` with `coeffs`"
    sz = coords.shape
    coords = coords.view(sz[0], -1, 2)
    coeffs = torch.cat([coeffs, t1(coeffs[:,:1])], dim=1).view(coeffs.shape[0], 3,3)
    coords = coords @ coeffs[...,:2].transpose(1,2) + coeffs[...,2].unsqueeze(1)
    coords.div_(coords[...,2].unsqueeze(-1))
    return coords[...,:2].view(*sz)

class _WarpCoord():
    def __init__(self, magnitude=0.2, p=0.5, draw_x=None, draw_y=None):
        self.coeffs,self.magnitude,self.p,self.draw_x,self.draw_y = None,magnitude,p,draw_x,draw_y

    def _def_draw(self): return random.uniform(-self.magnitude, self.magnitude)
    def randomize(self, x):
        x_t = _draw_mask(x, self._def_draw, self.draw_x, p=self.p)
        y_t = _draw_mask(x, self._def_draw, self.draw_y, p=self.p)
        orig_pts = torch.tensor([[-1,-1], [-1,1], [1,-1], [1,1]], dtype=x.dtype, device=x.device)
        self.orig_pts = orig_pts.unsqueeze(0).expand(x.size(0),4,2)
        targ_pts = stack([stack([-1-y_t, -1-x_t]), stack([-1+y_t, 1+x_t]),
                          stack([ 1+y_t, -1+x_t]), stack([ 1-y_t, 1-x_t])])
        self.targ_pts = targ_pts.permute(2,0,1)

    def __call__(self, x, invert=False):
        coeffs = find_coeffs(self.targ_pts, self.orig_pts) if invert else find_coeffs(self.orig_pts, self.targ_pts)
        return apply_perspective(x, coeffs)

def Warp(magnitude=0.2, p=0.5, draw_x=None, draw_y=None,size=None, mode='bilinear', pad_mode='reflection'):
    "Apply perspective warping with `magnitude` and `p` on a batch of matrices"
    return AffineCoordTfm(coord_fs=_WarpCoord(magnitude=magnitude, p=p, draw_x=draw_x, draw_y=draw_y),
                          size=size, mode=mode, pad_mode=pad_mode)

def logit(x):
    "Logit of `x`, clamped to avoid inf."
    x = x.clamp(1e-7, 1-1e-7)
    return -(1/x-1).log()

class LightingTfm(RandTransform):
    "Apply `fs` to the logits"
    order = 40
    def __init__(self, fs): self.fs=L(fs)
    def randomize(self, b):
        self.do = True
        if isinstance(b, tuple): b = b[0]
        for t in self.fs: t.randomize(b)

    def compose(self, tfm):
        "Compose `self` with another `LightingTransform`"
        self.fs += tfm.fs

    def encodes(self,x:TensorImage): return torch.sigmoid(compose_tfms(logit(x), self.fs))
    def encodes(self,x:TensorMask):  return x

class _BrightnessLogit():
    def __init__(self, max_lighting=0.2, p=0.75, draw=None):
        self.max_lighting,self.p,self.draw = max_lighting,p,draw

    def _def_draw(self): return random.uniform(0.5*(1-self.max_lighting), 0.5*(1+self.max_lighting))

    def randomize(self, x):
        self.change = _draw_mask(x, self._def_draw, draw=self.draw, p=self.p, neutral=0.5)

    def __call__(self, x): return x.add_(logit(self.change[:,None,None,None]))

def Brightness(max_lighting=0.2, p=0.75, draw=None):
    "Apply change in brightness of `max_lighting` to batch of images with probability `p`."
    return LightingTfm(_BrightnessLogit(max_lighting, p, draw))

class _ContrastLogit():
    def __init__(self, max_lighting=0.2, p=0.75, draw=None):
        self.max_lighting,self.p,self.draw = max_lighting,p,draw

    def _def_draw(self):
        return math.exp(random.uniform(math.log(1-self.max_lighting), -math.log(1-self.max_lighting)))

    def randomize(self, x):
        self.change = _draw_mask(x, self._def_draw, draw=self.draw, p=self.p, neutral=1.)

    def __call__(self, x): return x.mul_(self.change[:,None,None,None])

def _compose_same_tfms(tfms):
    tfms = L(tfms)
    if len(tfms) == 0: return None
    res = tfms[0]
    for tfm in tfms[1:]: res.compose(tfm)
    return res

def setup_aug_tfms(tfms):
    "Go through `tfms` and combines together affine/coord or lighting transforms"
    aff_tfms = [tfm for tfm in tfms if isinstance(tfm, AffineCoordTfm)]
    lig_tfms = [tfm for tfm in tfms if isinstance(tfm, LightingTfm)]
    others = [tfm for tfm in tfms if tfm not in aff_tfms+lig_tfms]
    aff_tfm,lig_tfm =  _compose_same_tfms(aff_tfms),_compose_same_tfms(lig_tfms)
    res = [aff_tfm] if aff_tfm is not None else []
    if lig_tfm is not None: res.append(lig_tfm)
    return res + others

def aug_transforms(do_flip=True, flip_vert=False, max_rotate=10., max_zoom=1.1, max_lighting=0.2,
                   max_warp=0.2, p_affine=0.75, p_lighting=0.75, xtra_tfms=None,
                   size=None, mode='bilinear', pad_mode='reflection'):
    "Utility func to easily create a list of flip, rotate, zoom, warp, lighting transforms."
    res,tkw = [],dict(size=size, mode=mode, pad_mode=pad_mode)
    if do_flip:    res.append(Dihedral(p=0.5, **tkw) if flip_vert else Flip(p=0.5, **tkw))
    if max_warp:   res.append(Warp(magnitude=max_warp, p=p_affine, **tkw))
    if max_rotate: res.append(Rotate(max_deg=max_rotate, p=p_affine, **tkw))
    if max_zoom>1: res.append(Zoom(max_zoom=max_zoom, p=p_affine, **tkw))
    if max_lighting:
        res.append(Brightness(max_lighting=max_lighting, p=p_lighting))
        res.append(Contrast(max_lighting=max_lighting, p=p_lighting))
    return setup_aug_tfms(res + L(xtra_tfms))