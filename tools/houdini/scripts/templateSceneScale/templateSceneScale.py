from pxr import Usd, UsdGeom, Gf

node = hou.pwd()
stage = node.editableStage()

# Parameters
asset_path = "/Root/ASSET"
scene_path = "/Root/SCENE"
body_path = "/Root/BODY"

ref_height = 2.5
margin = 0.1
min_margin = 0.1
body_margin = 0.2

# Check Prims
prims = {p: stage.GetPrimAtPath(p) for p in (asset_path, scene_path, body_path)}
missing = [p for p, prim in prims.items() if not prim]
if missing:
    raise hou.NodeError(f"Prim(s) not found: {', '.join(missing)}")
    
asset = prims[asset_path]
scene = prims[scene_path]
body = prims[body_path]
    
cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(),
        [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])

rng = cache.ComputeWorldBound(asset).ComputeAlignedRange()
bmin, bmax = rng.GetMin(), rng.GetMax()

height = bmax[1] - bmin[1]
width = bmax[0] - bmin[0]


### Small fix for very small asset
if bmax[1]<0.2:
    scaleFactor = min_margin
else:
    scaleFactor = bmax[1] / ((1 - margin) * ref_height)

if bmax[0]<0.2:
    UsdGeom.Imageable(body).MakeInvisible()
else:
    bodyMoveFactor = bmax[0] + width * body_margin
    
    ### Move Body 
    bodyXf = UsdGeom.Xformable(body)
    bodyXf.ClearXformOpOrder()
    bodyXf.AddTranslateOp().Set(Gf.Vec3d(bmax[0] + bodyMoveFactor, 0, 0))

### Scale Cyclo & Camera
sceneXf = UsdGeom.Xformable(scene)
sceneXf.ClearXformOpOrder()
sceneXf.AddScaleOp().Set(Gf.Vec3d(scaleFactor, scaleFactor, scaleFactor))