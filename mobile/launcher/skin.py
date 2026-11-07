"""皮肤系统：自定义皮肤应用（修改版本 jar 默认贴图）+ 模板 + 预览渲染。

离线账号无法走官方皮肤服务器，这里采用两种方式：
1. 简单模式（默认）：把皮肤写入版本 jar 的 steve.png / alex.png，
   每次启动前自动补丁，单机自己可见，无需任何模组。
2. 联机可见：Fabric/Forge 版本安装 CustomSkinLoader 模组（模组页或皮肤页一键安装）。
"""
import hashlib
import io
import os
import struct
import zipfile

from PIL import Image

STEVE_PATH = "assets/minecraft/textures/entity/steve.png"
ALEX_PATH = "assets/minecraft/textures/entity/alex.png"
# 1.19.3+ 默认皮肤改放此处（wide/slim 两组共 18 张，按 UUID 哈希随机选一张）
PLAYER_DIR = "assets/minecraft/textures/entity/player/"
MARKER_NAME = ".zycssgxx_skin_v2"
_LEGACY_MARKER = ".zycssgxx_skin"
PALETTE = [
    (0, 0, 0, 255), (60, 60, 60, 255), (128, 128, 128, 255), (220, 220, 220, 255),
    (255, 255, 255, 255), (244, 180, 27, 255), (249, 128, 29, 255), (229, 31, 28, 255),
    (179, 20, 20, 255), (146, 62, 176, 255), (78, 44, 240, 255), (0, 124, 190, 255),
    (46, 189, 240, 255), (60, 180, 75, 255), (128, 199, 31, 255), (190, 190, 90, 255),
    (139, 87, 42, 255), (99, 61, 28, 255), (245, 220, 190, 255), (230, 195, 160, 255),
    (255, 190, 190, 255), (240, 140, 160, 255), (120, 85, 60, 255), (35, 35, 45, 255),
]

# 64x64 标准布局主要区域（左, 上, 右, 下）
REGIONS = [
    ("头", (8, 8, 16, 16)), ("身体", (20, 20, 28, 32)),
    ("右臂", (44, 20, 48, 32)), ("右腿", (4, 20, 8, 32)),
    ("左臂", (36, 52, 40, 64)), ("左腿", (20, 52, 24, 64)),
]
FRONT_PARTS = [(8, 8, 16, 16), (44, 20, 48, 32), (20, 20, 28, 32),
               (36, 52, 40, 64), (4, 20, 8, 32), (20, 52, 24, 64)]


def skins_dir(app_dir):
    d = os.path.join(app_dir, "skins")
    os.makedirs(d, exist_ok=True)
    return d


def account_skin_path(app_dir, name):
    return os.path.join(skins_dir(app_dir), name + ".png")


def validate_skin(path):
    """读取皮肤文件，转为标准 64x64 RGBA；不合法返回 None"""
    try:
        img = Image.open(path).convert("RGBA")
    except Exception:
        return None
    if img.size not in ((64, 64), (64, 32)):
        return None
    if img.size == (64, 32):
        full = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        full.paste(img, (0, 0))
        img = full
    return img


def render_front(img, zoom=8):
    """渲染皮肤正面预览（头+双臂+身体+双腿），返回放大后的 PIL 图像"""
    img = img.convert("RGBA")
    out = Image.new("RGBA", (16, 28), (0, 0, 0, 0))
    # 头 (8x8) 顶部居中
    out.paste(img.crop((8, 8, 16, 16)), (4, 0))
    # 双臂+身体 (4+8+4=16 宽, 12 高)
    out.paste(img.crop((44, 20, 48, 32)), (0, 8))
    out.paste(img.crop((20, 20, 28, 32)), (4, 8))
    out.paste(img.crop((36, 52, 40, 64)), (12, 8))
    # 双腿 (4+4=8 宽, 12 高)
    out.paste(img.crop((4, 20, 8, 32)), (4, 20))
    out.paste(img.crop((20, 52, 24, 64)), (8, 20))
    return out.resize((16 * zoom, 28 * zoom), Image.NEAREST)


def classic_template():
    """生成经典 Steve 风格模板（肤色头+蓝衣蓝裤）"""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    skin = (245, 220, 190, 255)
    hair = (60, 42, 30, 255)
    shirt = (0, 124, 190, 255)
    pants = (58, 63, 116, 255)
    shoes = (80, 80, 80, 255)

    def fill(box, color):
        for y in range(box[1], box[3]):
            for x in range(box[0], box[2]):
                img.putpixel((x, y), color)

    for hb in [(8, 8, 16, 16)]:  # 头（正面基底，四侧也填上避免透明）
        for box in [(8, 8, 16, 16), (0, 8, 8, 16), (16, 8, 24, 16),
                    (8, 0, 16, 8), (8, 16, 16, 24)]:
            fill(box, skin)
        fill((8, 8, 16, 10), hair)   # 刘海
        fill((8, 0, 16, 3), hair)    # 顶
    for box in [(20, 20, 28, 32), (36, 52, 44, 64)]:   # 身体+左臂
        fill(box, shirt)
    fill((44, 20, 48, 29), shirt)                        # 右臂袖
    fill((44, 29, 48, 32), skin)                         # 右手
    fill((36, 61, 40, 64), skin)                         # 左手
    for box in [(4, 20, 8, 30), (20, 52, 24, 62)]:       # 双腿
        fill(box, pants)
    fill((4, 30, 8, 32), shoes)
    fill((20, 62, 24, 64), shoes)
    return img


def _patch_marker_hash(skin_bytes, jar):
    st = os.stat(jar)
    key = hashlib.md5(skin_bytes).hexdigest()[:8]
    return "%s|%d|%d" % (key, st.st_size, int(st.st_mtime))


def apply_skin(skin_path, mc_dir, version_id):
    """把皮肤补丁进版本 jar，返回 True=已处理（本次或以前），False=无 jar"""
    jar = os.path.join(mc_dir, "versions", version_id, version_id + ".jar")
    if not os.path.isfile(jar):
        return False
    with open(skin_path, "rb") as f:
        skin_bytes = f.read()
    img = validate_skin(skin_path)
    if img is None:
        return False
    buf = io.BytesIO()
    img.save(buf, "PNG")
    png = buf.getvalue()

    marker = os.path.join(mc_dir, "versions", version_id, MARKER_NAME)
    want = _patch_marker_hash(png, jar)
    if os.path.isfile(marker):
        try:
            with open(marker, encoding="utf-8") as f:
                if f.read().strip() == want:
                    return True
        except OSError:
            pass

    tmp = jar + ".skintmp"
    hit = False
    with zipfile.ZipFile(jar) as zin, \
            zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if (item.filename in (STEVE_PATH, ALEX_PATH)
                    or (item.filename.startswith(PLAYER_DIR)
                        and item.filename.endswith(".png"))):
                data = png
                hit = True
            zout.writestr(item, data)
        if not hit:  # 极老版本没有这些路径，补一份无副作用
            zout.writestr(STEVE_PATH, png)
    os.replace(tmp, jar)
    # 用替换后的 jar 状态生成标记（jar 的 mtime/size 已变化）
    want = _patch_marker_hash(png, jar)
    with open(marker, "w", encoding="utf-8") as f:
        f.write(want)
    return True


def clear_skin_patches(mc_dir):
    """清除全部补丁标记（皮肤被移除后，下次启动恢复原版贴图需要重新打补丁判断），
    并把已被替换的 steve/alex 从 jar 还原需要重装版本，这里只清标记防止残留干扰"""
    vdir = os.path.join(mc_dir, "versions")
    if not os.path.isdir(vdir):
        return
    for name in os.listdir(vdir):
        for marker in (MARKER_NAME, _LEGACY_MARKER):
            p = os.path.join(vdir, name, marker)
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except OSError:
                pass


def flood_fill(img, x, y, color, alpha_threshold=10):
    """油漆桶：BFS 填充与起点颜色相近的连通区域（64x64）"""
    if not (0 <= x < 64 and 0 <= y < 64):
        return
    px = img.load()
    target = px[x, y]
    tc = bytes(target)
    nc = bytes(color)
    if tc == nc:
        return
    stack = [(x, y)]
    while stack:
        cx, cy = stack.pop()
        if not (0 <= cx < 64 and 0 <= cy < 64):
            continue
        cur = px[cx, cy]
        if bytes(cur) != tc:
            continue
        px[cx, cy] = color
        stack.extend(((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)))
    _ = alpha_threshold
