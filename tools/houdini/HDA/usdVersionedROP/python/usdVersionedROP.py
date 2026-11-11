import hou, os, re, getpass, datetime, json
from pxr import Sdf


META_KEYS = ("metersPerUnit", "upAxis", "startTimeCode", "endTimeCode",
             "timeCodesPerSecond", "framesPerSecond")
PUBLISH_SUFFIX = "_publish.usda"


class PublishError(Exception):
    pass


def notify(message):
    if hou.isUIAvailable():
        hou.ui.displayMessage(message, severity=hou.severityType.Message)
    else:
        print(message)


def get_version(folder, node):
    isLatest = node.evalParm("latest")
    chosenVersion = node.evalParm("versionInt")
    if isLatest:
        if not os.path.isdir(folder):
            return 1
        versions = []
        for v in os.listdir(folder):
            match = re.match(r"v(\d{4})$", v)
            if match:
                versions.append(int(match.group(1)))
        nextVersion = max(versions, default=0) + 1
        node.parm("versionInt").set(nextVersion)
        return nextVersion
    return chosenVersion


def version_name(v):
    return f"v{int(v):04d}"


def export_usd(node):
    outputDir, fileName = os.path.split(node.evalParm("lopOutput"))
    name, ext = os.path.splitext(fileName)
    clean = re.sub(r"_v\d+$", "", name)
    taskFolder = os.path.dirname(outputDir)

    version = version_name(get_version(taskFolder, node))
    usdPath = f"{taskFolder}/{version}/{clean}_{version}{ext}"

    rop = node.node("usd_rop")
    if rop is None:
        raise PublishError("usd_rop not found: refresh the HDA.")

    os.makedirs(os.path.dirname(usdPath), exist_ok=True)
    node.parm("usdPath").set(usdPath)
    node.parm("lopOutput").set(usdPath)
    rop.render()

    pinned = []
    if node.evalParm("pin"):
        pinned = pin_dependencies(usdPath)

    publishPath = None
    if node.evalParm("publish"):
        publishPath = f"{taskFolder}/{clean}{PUBLISH_SUFFIX}"
        write_publish(usdPath, publishPath)

    write_metadata(usdPath, version, node, publishPath is not None, pinned)

    message = f"USD File Exported:\n{usdPath}"
    if publishPath:
        message += f"\n\nUSD Publish updated:\n{publishPath}"
    print(message)


def write_publish(versionPath, publishPath):
    product = Sdf.Layer.FindOrOpen(versionPath)
    if not product:
        raise PublishError(f"Cannot open versioned file:\n{versionPath}")
    product.Reload()

    layer = Sdf.Layer.CreateAnonymous(".usda")
    layer.subLayerPaths.append(
        os.path.relpath(versionPath, os.path.dirname(publishPath)).replace("\\", "/")
    )

    for key in META_KEYS:
        if product.pseudoRoot.HasInfo(key):
            layer.pseudoRoot.SetInfo(key, product.pseudoRoot.GetInfo(key))
    if product.defaultPrim:
        layer.defaultPrim = product.defaultPrim

    if os.path.exists(publishPath):
        os.chmod(publishPath, 0o666)  # Allow rewrite if the file is already opened

    layer.Export(publishPath)

    openLayer = Sdf.Layer.Find(publishPath)
    if openLayer:
        openLayer.Reload()


def resolve(path, anchorFile):
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(anchorFile), path)
    return os.path.normpath(path).replace("\\", "/")


def version_behind_publish(publishFile):
    if not os.path.isfile(publishFile):
        raise PublishError(f"Child publish not found:\n\n{publishFile}\n\nPublish it first.")

    layer = Sdf.Layer.FindOrOpen(publishFile)
    if not layer:
        raise PublishError(f"Cannot open child publish:\n\n{publishFile}")
    layer.Reload()

    subs = list(layer.subLayerPaths)
    if not subs:
        raise PublishError(f"Child publish has no sublayer:\n\n{publishFile}")

    return resolve(subs[0], publishFile)


def pin_dependencies(versionFile):
    versionFile = os.path.abspath(versionFile).replace("\\", "/")
    layer = Sdf.Layer.FindOrOpen(versionFile)
    if not layer:
        raise PublishError(f"Cannot open version file:\n\n{versionFile}")
    layer.Reload()

    # Collect first, then edit
    changes = []
    for dep in sorted(layer.GetCompositionAssetDependencies()):
        absDep = resolve(dep, versionFile)
        if not absDep.endswith(PUBLISH_SUFFIX):
            continue

        childVersion = version_behind_publish(absDep)
        try:
            new = os.path.relpath(childVersion, os.path.dirname(versionFile))
        except ValueError:  # different drives on Windows
            raise PublishError(f"Cannot build a relative path across drives:\n\n{childVersion}")
        changes.append((dep, new.replace("\\", "/")))

    pinned = []
    for old, new in changes:
        print(f"Pinned: {old} -> {new}\n")
        if not layer.UpdateCompositionAssetDependency(old, new):
            raise PublishError(f"Could not update dependency:\n\n{old}")
        pinned.append({"from": old, "to": new})

    if changes:
        layer.Save()
        layer.Reload()

    return pinned


def write_metadata(usdPath, version, node, published, pinned):
    jsonPath = os.path.splitext(usdPath)[0] + ".json"

    data = {
        "user": getpass.getuser(),
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "hipFile": hou.hipFile.path().replace("\\", "/"),
        "file": os.path.basename(usdPath),
        "version": version,
        "published": bool(published),
        "pinDependencies": bool(node.evalParm("pin")),
    }

    if pinned:
        data["pinnedDependencies"] = pinned

    with open(jsonPath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

    return jsonPath