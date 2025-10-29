import streamlit as st
import requests
import pandas as pd
import re
import os
import zipfile
import concurrent.futures

# ============== Helpers ==============
def _header():
    st.markdown("""
    <div style="display:flex; align-items:center; gap:18px; margin: 10px 0 12px 0;">
        <img src="assets/icon_extrator.svg" width="250" style="flex-shrink:0;">
        <span style="font-size: 34px; font-weight: 800; letter-spacing: .5px; display:flex; align-items:center;">
            EXTRAIR IMAGENS CSV
        </span>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="panel fade-in">Configuração de Acesso</div>', unsafe_allow_html=True)

def _shopify_request(url, token, params=None):
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }
    r = requests.get(url, headers=headers, params=params, timeout=60)
    if r.status_code != 200:
        try:
            st.error(f"Erro {r.status_code}: {r.json()}")
        except Exception:
            st.error(f"Erro {r.status_code}: {r.text[:300]}")
        st.stop()
    return r

def _get_collection_id(shop_name, api_version, collection_input, token):
    # Accept ID, handle or full URL
    if collection_input.isdigit():
        return collection_input

    if collection_input.startswith("http"):
        m = re.search(r"/collections/([^/?#]+)", collection_input)
        if m:
            handle = m.group(1)
        else:
            st.error("URL de coleção inválida."); st.stop()
    else:
        handle = collection_input

    url = f"https://{shop_name}.myshopify.com/admin/api/{api_version}/custom_collections.json"
    r = _shopify_request(url, token, params={"handle": handle})
    items = r.json().get("custom_collections", [])
    if not items:
        st.error("Coleção não encontrada pelo handle informado."); st.stop()
    return str(items[0]["id"])

def _get_products_in_collection(shop_name, api_version, collection_id, token, turbo=False):
    produtos = []
    page_info = None
    while True:
        url = f"https://{shop_name}.myshopify.com/admin/api/{api_version}/products.json"
        params = {"collection_id": collection_id, "limit": 250}
        if page_info:
            params["page_info"] = page_info
        r = _shopify_request(url, token, params=params)
        produtos.extend(r.json().get("products", []))
        link = r.headers.get("link", "")
        if link and 'rel="next"' in link:
            try:
                page_info = link.split("page_info=")[-1].split(">")[0]
            except Exception:
                break
        else:
            break
    return produtos

def _baixar_imagem(url, caminho):
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 200:
            os.makedirs(os.path.dirname(caminho), exist_ok=True)
            with open(caminho, "wb") as f:
                f.write(r.content)
    except Exception:
        pass

# ============== Public API ==============
def render(ping_b64: str):
    _header()

    colA, colB = st.columns(2)
    with colA:
        shop_name = st.text_input("Nome da Loja (ex: a608d7-cf)", help="Endereço myshopify.com sem o sufixo.")
    with colB:
        api_version = st.text_input("API Version", value="2023-10", help="Versão Admin API (ex: 2023-10).")

    access_token = st.text_input("Access Token (shpat_...)", type="password")
    collection_input = st.text_input("Coleção (ID, handle ou URL)", help="ex: dunk ou https://sualoja.myshopify.com/collections/dunk")

    st.markdown('<div class="panel fade-in">Opções</div>', unsafe_allow_html=True)
    modo = st.radio("Selecione a ação:", ("🔗 Gerar apenas CSV com links", "📦 Baixar imagens e gerar ZIP por produto"), index=0, horizontal=True)
    turbo = st.toggle("Turbo (download paralelo)", value=True)

    if st.button("▶️ Iniciar Exportação", use_container_width=True):
        if not (shop_name and api_version and access_token and collection_input):
            st.warning("Preencha todos os campos."); st.stop()

        if collection_input.isdigit():
            collection_id = collection_input
        else:
            collection_id = _get_collection_id(shop_name, api_version, collection_input, access_token)

        produtos = _get_products_in_collection(shop_name, api_version, collection_id, access_token)

        if not produtos:
            st.warning("Nenhum produto encontrado nesta coleção."); st.stop()

        dados = []
        tarefas = []

        for p in produtos:
            title = p.get("title", "")
            imagens = [img["src"] for img in p.get("images", [])]
            item = {"Título": title}
            for i, img in enumerate(imagens):
                item[f"Imagem {i+1}"] = img
                if "📦" in modo:
                    pasta = os.path.join("imagens_baixadas", re.sub(r'[\\/*?:\"<>|]', "_", title))
                    tarefas.append((img, os.path.join(pasta, f"{i+1}.jpg")))
            dados.append(item)

        if "📦" in modo and tarefas:
            st.info(f"Baixando {len(tarefas)} imagens...")
            if turbo:
                with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
                    list(ex.map(lambda x: _baixar_imagem(*x), tarefas))
            else:
                for t in tarefas:
                    _baixar_imagem(*t)

            zip_name = f"imagens_colecao_{collection_id}.zip"
            with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk("imagens_baixadas"):
                    for file in files:
                        path = os.path.join(root, file)
                        zipf.write(path, os.path.relpath(path, "imagens_baixadas"))

            with open(zip_name, "rb") as f:
                st.download_button("📥 Baixar ZIP", f, file_name=zip_name, use_container_width=True)

        csv_name = f"imagens_colecao_{collection_id}.csv"
        pd.DataFrame(dados).to_csv(csv_name, index=False, encoding="utf-8-sig")
        with open(csv_name, "rb") as f:
            st.download_button("📥 Baixar CSV", f, file_name=csv_name, use_container_width=True)

        st.success("🎉 Exportação concluída!")
