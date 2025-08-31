import io
import zipfile
from datetime import datetime
from typing import List, Tuple

import streamlit as st
from PIL import Image, ImageOps, ImageCms, ImageEnhance

# -------------------------------
# Helpers
# -------------------------------

def read_uploaded_images(uploaded_files) -> List[Tuple[str, Image.Image]]:
    images = []
    if not uploaded_files:
        return images

    for uf in uploaded_files:
        name = getattr(uf, "name", "upload")
        if name.lower().endswith(".zip"):
            data = uf.read()
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    fname = info.filename
                    if not fname.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff")):
                        continue
                    with zf.open(info) as f:
                        try:
                            im = Image.open(io.BytesIO(f.read()))
                            im = ImageOps.exif_transpose(im)
                            images.append((fname, im))
                        except Exception:
                            continue
        else:
            try:
                im = Image.open(uf)
                im = ImageOps.exif_transpose(im)
                images.append((name, im))
            except Exception:
                continue
    return images


def ensure_rgb_and_srgb(img: Image.Image, convert_to_srgb: bool = True) -> Image.Image:
    # Always output RGB to avoid surprises when saving JPEG/WebP
    if convert_to_srgb:
        try:
            if "icc_profile" in img.info:
                src_profile = ImageCms.ImageCmsProfile(io.BytesIO(img.info.get("icc_profile")))
                dst_profile = ImageCms.createProfile("sRGB")
                img = ImageCms.profileToProfile(img, src_profile, dst_profile, outputMode="RGB")
            else:
                img = img.convert("RGB")
        except Exception:
            img = img.convert("RGB")
    else:
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
    return img


def resize_to_long_edge(img: Image.Image, target_long: int) -> Image.Image:
    w, h = img.size
    long_side = max(w, h)
    if target_long <= 0 or long_side <= target_long:
        return img
    scale = target_long / float(long_side)
    new_w = int(round(w * scale))
    new_h = int(round(h * scale))
    return img.resize((new_w, new_h), Image.LANCZOS)


def apply_watermark(base: Image.Image,
                    watermark: Image.Image,
                    position: str = "bottom-right",
                    scale_pct: float = 10.0,
                    opacity_pct: float = 70.0,
                    margin_px: int = 24) -> Image.Image:
    if watermark is None:
        return base

    base = base.convert("RGBA")
    wm = watermark.convert("RGBA")

    # Scale watermark based on base width
    target_w = max(1, int(base.width * (scale_pct / 100.0)))
    scale = target_w / wm.width
    wm = wm.resize((target_w, max(1, int(wm.height * scale))), Image.LANCZOS)

    # Apply opacity
    if 0 <= opacity_pct < 100:
        alpha = wm.split()[-1]
        alpha = ImageEnhance.Brightness(alpha).enhance(opacity_pct / 100.0)
        wm.putalpha(alpha)

    # Compute position
    positions = {
        "top-left": (margin_px, margin_px),
        "top-right": (base.width - wm.width - margin_px, margin_px),
        "bottom-left": (margin_px, base.height - wm.height - margin_px),
        "bottom-right": (base.width - wm.width - margin_px, base.height - wm.height - margin_px),
        "center": ((base.width - wm.width) // 2, (base.height - wm.height) // 2),
    }
    xy = positions.get(position, positions["bottom-right"])

    out = base.copy()
    out.alpha_composite(wm, dest=xy)
    return out.convert("RGB")


def save_image_bytes(img: Image.Image,
                     fmt: str = "JPEG",
                     quality: int = 85,
                     progressive: bool = True,
                     optimize: bool = True,
                     keep_metadata: bool = False) -> bytes:
    """Encode an image to bytes, optionally keeping EXIF, without mutating the input."""
    fmt = fmt.upper()
    exif_bytes = img.info.get("exif", b"") if keep_metadata else b""
    work = img.copy()  # don’t mutate the original

    buf = io.BytesIO()
    if fmt == "JPEG":
        work = work.convert("RGB")
        work.save(
            buf,
            format="JPEG",
            quality=int(quality),
            optimize=optimize,
            progressive=progressive,
            exif=exif_bytes,
        )
    elif fmt == "WEBP":
        try:
            work.save(buf, format="WEBP", quality=int(quality), method=6, exif=exif_bytes)
        except TypeError:
            work.save(buf, format="WEBP", quality=int(quality))
    else:
        work.save(buf, format="PNG")
    return buf.getvalue()



def process_one(image: Image.Image,
                target_long: int,
                out_fmt: str,
                quality: int,
                progressive: bool,
                optimize: bool,
                convert_to_srgb: bool,
                keep_metadata: bool,
                wm_img: Image.Image | None,
                wm_position: str,
                wm_scale_pct: float,
                wm_opacity_pct: float,
                wm_margin_px: int) -> Image.Image:
    img = ensure_rgb_and_srgb(image, convert_to_srgb)
    img = resize_to_long_edge(img, target_long)
    if wm_img is not None:
        img = apply_watermark(img, wm_img, wm_position, wm_scale_pct, wm_opacity_pct, wm_margin_px)
    # Nothing else here, saving happens separately to bytes for preview size
    return img


def filename_with_suffix(name: str, suffix: str, ext: str) -> str:
    base = name.replace("\\", "/").split("/")[-1]
    if "." in base:
        base = base[:base.rfind(".")]
    return f"{base}{suffix}.{ext.lower()}"


# -------------------------------
# UI
# -------------------------------

st.set_page_config(page_title="Image Pipeline", layout="wide")
st.title("Image pipeline for web and Instagram")

with st.sidebar:
    st.header("Input")
    uploads = st.file_uploader(
        "Upload images or a ZIP",
        type=["jpg", "jpeg", "png", "webp", "tif", "tiff", "zip"],
        accept_multiple_files=True,
    )

    st.divider()
    st.header("Output settings")

    preset = st.selectbox(
        "Preset",
        [
            "Custom",
            "Web portfolio 2048 long edge",
            "Instagram post 1080 long edge",
            "Instagram portrait 1350 long edge",
            "Instagram story 1920 long edge",
        ],
        index=0,
    )

    default_long = 2048 if preset == "Web portfolio 2048 long edge" else \
                    1080 if preset == "Instagram post 1080 long edge" else \
                    1350 if preset == "Instagram portrait 1350 long edge" else \
                    1920 if preset == "Instagram story 1920 long edge" else 2048

    target_long = st.number_input("Target long edge, px", min_value=256, max_value=12000, value=default_long, step=64)

    out_fmt = st.selectbox("Format", ["JPEG", "WEBP"], index=0)
    quality = st.slider("Quality", min_value=40, max_value=100, value=85, step=1)
    progressive = st.checkbox("Progressive JPEG", value=True, help="Ignored for WebP")
    optimize = st.checkbox("Optimize", value=True)

    st.subheader("Color and metadata")
    convert_to_srgb = st.checkbox("Convert to sRGB", value=True)
    keep_metadata = st.checkbox("Keep metadata", value=False)

    st.subheader("Watermark (optional)")
    wm_file = st.file_uploader("PNG watermark", type=["png"], accept_multiple_files=False)
    wm_position = st.selectbox("Position", ["bottom-right", "bottom-left", "top-right", "top-left", "center"], index=0)
    wm_scale_pct = st.slider("Watermark width, percent of image width", 1, 40, 12)
    wm_opacity_pct = st.slider("Watermark opacity, percent", 0, 100, 70)
    wm_margin_px = st.slider("Margin, px", 0, 200, 24)

    st.subheader("Filenames")
    suffix = st.text_input("Output suffix", value="_web")

# Load inputs
images = read_uploaded_images(uploads)

wm_img = None
if wm_file is not None:
    try:
        wm_img = Image.open(wm_file)
    except Exception:
        wm_img = None

# Preview
st.subheader("Preview")
if not images:
    st.info("Upload at least one image or a ZIP to see a preview.")
else:
    sample_name, sample_img = images[0]
    processed_preview = process_one(sample_img, target_long, out_fmt, quality, progressive, optimize,
                                    convert_to_srgb, keep_metadata, wm_img, wm_position, wm_scale_pct,
                                    wm_opacity_pct, wm_margin_px)

    # Compute sizes
    try:
        original_bytes = io.BytesIO()
        sample_img.save(original_bytes, format="JPEG", quality=95)
        orig_size = len(original_bytes.getvalue())
    except Exception:
        orig_size = 0

    out_bytes = save_image_bytes(processed_preview, out_fmt, quality, progressive, optimize, keep_metadata)

    c1, c2 = st.columns(2)
    with c1:
        st.caption(f"Original: {sample_name}")
        st.image(sample_img, use_container_width=True)
        if orig_size:
            st.text(f"Approx original re-encoded size: {orig_size/1024:.1f} KB")
    with c2:
        st.caption(f"Preview output: {filename_with_suffix(sample_name, suffix, out_fmt.lower())}")
        st.image(processed_preview, use_container_width=True)
        st.text(f"Estimated output size: {len(out_bytes)/1024:.1f} KB")
        st.download_button(
            label="Download preview",
            data=out_bytes,
            file_name=filename_with_suffix(sample_name, suffix, out_fmt.lower()),
            mime="image/jpeg" if out_fmt.upper()=="JPEG" else "image/webp",
        )

st.divider()

# Batch processing
st.subheader("Process all and export")
if st.button("Process images"):
    if not images:
        st.warning("No images to process.")
    else:
        results: List[Tuple[str, bytes]] = []
        for name, img in images:
            out_img = process_one(img, target_long, out_fmt, quality, progressive, optimize,
                                  convert_to_srgb, keep_metadata, wm_img, wm_position, wm_scale_pct,
                                  wm_opacity_pct, wm_margin_px)
            out_bytes = save_image_bytes(out_img, out_fmt, quality, progressive, optimize, keep_metadata)
            out_name = filename_with_suffix(name, suffix, out_fmt.lower())
            results.append((out_name, out_bytes))

        if len(results) == 1:
            fname, data = results[0]
            st.download_button(
                label=f"Download {fname}",
                data=data,
                file_name=fname,
                mime="image/jpeg" if out_fmt.upper()=="JPEG" else "image/webp",
            )
        else:
            # ZIP them
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                for fname, data in results:
                    zf.writestr(fname, data)
            zip_bytes = zip_buf.getvalue()
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_name = f"exports_{ts}.zip"
            st.download_button(
                label=f"Download {zip_name}",
                data=zip_bytes,
                file_name=zip_name,
                mime="application/zip",
            )

st.caption("Tip: Instagram likes 1080 long edge for posts and 1350 for portrait. Use WebP for your own site when supported.")