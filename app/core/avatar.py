"""用户头像存取：校验上传图片、裁成方形并保存到数据目录。"""
from __future__ import annotations

import base64
import io
import re
import time
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

NAME = "avatar.png"
SIZE = 256
MAX_BYTES = 8 * 1024 * 1024
MAX_EDGE = 8000
_DATA_URL = re.compile(r"^data:image/(?:png|jpe?g|webp);base64,", re.IGNORECASE)


def path_for(data_dir: Path) -> Path:
    return Path(data_dir) / NAME


def save(data_dir: Path, data_url: str) -> int:
    """保存 data URL 图片，返回新的版本号；格式或大小不合法时抛 ValueError。"""
    if not isinstance(data_url, str) or not _DATA_URL.match(data_url):
        raise ValueError("仅支持 PNG、JPG 或 WebP 图片")
    try:
        raw = base64.b64decode(data_url.split(",", 1)[1], validate=True)
    except (ValueError, IndexError) as e:
        raise ValueError("图片数据不完整") from e
    if len(raw) > MAX_BYTES:
        raise ValueError("图片不能超过 8MB")
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            if img.width > MAX_EDGE or img.height > MAX_EDGE:
                raise ValueError("图片尺寸过大")
            square = ImageOps.fit(
                ImageOps.exif_transpose(img).convert("RGBA"),
                (SIZE, SIZE),
                method=Image.LANCZOS,
            )
            target = path_for(data_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            square.save(target, "PNG", optimize=True)
    except UnidentifiedImageError as e:
        raise ValueError("无法识别这张图片") from e
    except OSError as e:
        raise ValueError("头像保存失败") from e
    return int(time.time())


def data_url(data_dir: Path) -> str:
    """读取头像为 data URL；没有自定义头像时返回空串。"""
    target = path_for(data_dir)
    if not target.is_file():
        return ""
    try:
        raw = target.read_bytes()
    except OSError:
        return ""
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def clear(data_dir: Path) -> None:
    try:
        path_for(data_dir).unlink(missing_ok=True)
    except OSError:
        pass
