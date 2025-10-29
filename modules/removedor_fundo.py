import streamlit as st
from PIL import Image
import io, os, shutil, zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from rembg import remove, new_session
    _HAS_REMBG = True
except Exception:
    _HAS_REMBG = False

def _play_ping(ping_b64: str):
    st.markdown(f'<audio autoplay src="data:audio/wav;base64,{ping_b64}"></audio>', unsafe_allow_html=True)

def _remove_bg_bytes(img_bytes: bytes, session=None) -> bytes:
    return remove(img_bytes, session=session)

def render(ping_b64: str):
    st.markdown("""
    <div style="display:flex; align-items:center; gap:18px; margin: 10px 0 12px 0;">
        <img src="assets/icon_removedor.svg" width="250" style="flex-shrink:0;">
        <span style="font-size: 34px; font-weight: 800; letter-spacing: .5px; display:flex; align-items:center;">
            REMOVEDOR DE FUNDO
        </span>
    </div>
    """, unsafe_allow_html=True)

    if not _HAS_REMBG:
        st.error("Biblioteca 'rembg' não encontrada. Instale com: pip install rembg onnxruntime")
        st.stop()

    st.markdown('<div class="panel fade-in">Configurações</div>', unsafe_allow_html=True)
    model = st.selectbox("Modelo", ("u2net_human_seg", "u2net", "isnet-general-use"), index=0)
    st.caption("Dica: 'u2net_human_seg' costuma dar melhor recorte para pessoas.")

    files = st.file_uploader("Envie imagens ou ZIP", type=["jpg","jpeg","png","webp","zip"], accept_multiple_files=True)
    if not files: st.stop()

    INP, OUT = "rm_in", "rm_out"
    shutil.rmtree(INP, ignore_errors=True); shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(INP, exist_ok=True); os.makedirs(OUT, exist_ok=True)

    from zipfile import ZipFile, BadZipFile
    for f in files:
        if f.name.lower().endswith(".zip"):
            try:
                with ZipFile(io.BytesIO(f.read())) as z: z.extractall(INP)
            except BadZipFile: st.error(f"ZIP inválido: {f.name}")
        else:
            open(os.path.join(INP, f.name), "wb").write(f.read())

    paths = [p for p in Path(INP).rglob("*") if p.suffix.lower() in (".jpg",".jpeg",".png",".webp") ]
    if not paths:
        st.warning("Nenhuma imagem encontrada."); st.stop()

    session = new_session(model)

    prog = st.progress(0.0); info = st.empty()
    previews = []

    def worker(p: Path):
        rel = p.relative_to(INP)
        raw = open(p, "rb").read()
        out_bytes = _remove_bg_bytes(raw, session=session)
        outp = (Path(OUT)/rel).with_suffix(".png")
        os.makedirs(outp.parent, exist_ok=True)
        open(outp, "wb").write(out_bytes)
        return raw, out_bytes, rel.as_posix()

    with ThreadPoolExecutor(max_workers=4) as ex:
        fut=[ex.submit(worker,p) for p in paths]; tot=len(fut)
        for i,f in enumerate(as_completed(fut),1):
            try: previews.append(f.result())
            except Exception as e: st.error(f"Erro ao processar: {e}")
            prog.progress(i/tot); info.info(f"Processado {i}/{tot}")

    st.write("---"); st.subheader("Pré-visualização (Antes / Depois)")
    alpha = st.slider("Comparação", 0, 100, 50, 1)
    blend = alpha/100.0

    cols = st.columns(2)
    for orig_b, out_b, name in previews[:3]:
        with cols[0]:
            st.image(orig_b, caption=f"ANTES — {name}", use_column_width=True)
        with cols[1]:
            try:
                img_o = Image.open(io.BytesIO(orig_b)).convert("RGBA")
                img_r = Image.open(io.BytesIO(out_b)).convert("RGBA")
                w = min(img_o.width, img_r.width); h = min(img_o.height, img_r.height)
                img_o = img_o.resize((w,h)); img_r = img_r.resize((w,h))
                blended = Image.blend(img_o, img_r, blend)
                bio = io.BytesIO(); blended.save(bio, format="PNG"); bio.seek(0)
                st.image(bio, caption=f"DEPOIS — {name}", use_column_width=True)
            except Exception:
                st.image(out_b, caption=f"DEPOIS — {name}", use_column_width=True)

    zbytes = io.BytesIO()
    with zipfile.ZipFile(zbytes, "w", zipfile.ZIP_DEFLATED) as z:
        for root,_,files in os.walk(OUT):
            for fn in files:
                fp=os.path.join(root,fn); arc=os.path.relpath(fp,OUT); z.write(fp,arc)
    zbytes.seek(0)
    st.success("Remoção de fundo concluída!")
    _play_ping(ping_b64)
    st.download_button("Baixar PNGs sem fundo", data=zbytes, file_name="sem_fundo.zip", mime="application/zip")
