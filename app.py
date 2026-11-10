import streamlit as st
import csv
import re
from datetime import datetime
from io import BytesIO, StringIO
import qrcode
from streamlit_gsheets import GSheetsConnection

st.set_page_config(
    page_title="Sugestões Supermercado",
    page_icon="🏪",
    layout="centered",
    menu_items={'Get Help': None, 'Report a bug': None, 'About': None}
)

st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header[data-testid="stHeader"] {background: transparent; height: 0;}
        div[data-testid="stToolbar"] {visibility: hidden; height: 0%; position: fixed;}
        .stDeployButton {display: none;}
        .stTextInput > div > div > input:focus, 
        .stTextArea > div > div > textarea:focus {
            border-color: #1f77b4 !important;
            box-shadow: 0 0 0 1px #1f77b4 !important;
        }
        div[data-testid="stForm"] {border-color: #1f77b4 !important;}
        .stButton > button {
            border-color: #1f77b4 !important;
            color: #1f77b4 !important;
        }
        .stButton > button:hover {
            border-color: #1f77b4 !important;
            color: #ffffff !important;
            background-color: #1f77b4 !important;
        }
    </style>
""", unsafe_allow_html=True)

def get_secret(chave, padrao=None):
    try:
        return st.secrets[chave]
    except Exception:
        return padrao

SENHA_CORRETA = get_secret("senha_lojista", "loja2024")
URL_APP_PADRAO = get_secret("url_app", "https://seu-app.streamlit.app")

# Conexão com o Google Sheets
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"Erro ao conectar com o Google Sheets. Verifique os Secrets. Detalhe: {e}")
    st.stop()

def salvar_sugestao(nome, telefone, sugestao):
    # Lê os dados atuais (se houver) e adiciona a nova linha
    df = conn.read(ttl=0)
    nova_linha = {
        "Nome": nome,
        "Telefone": telefone,
        "Sugestao": sugestao,
        "Data": datetime.now().strftime("%d/%m/%Y %H:%M")
    }
    # Converte a nova linha para DataFrame e concatena
    import pandas as pd
    df_novo = pd.DataFrame([nova_linha])
    df_final = pd.concat([df, df_novo], ignore_index=True)
    # Atualiza a planilha inteira
    conn.update(data=df_final)

def listar_sugestoes():
    df = conn.read(ttl=0)
    # Converte o DataFrame para uma lista de tuplas (para manter o formato de exibição)
    return [tuple(x) for x in df.values]

def deletar_sugestao(index):
    df = conn.read(ttl=0)
    df = df.drop(index=index).reset_index(drop=True)
    conn.update(data=df)

def validar_telefone(telefone):
    numeros = re.sub(r'\D', '', telefone)
    if len(numeros) in [10, 11]:
        return True, numeros
    return False, numeros

aba_cliente, aba_lojista = st.tabs(["🛒 Deixar Sugestão", "🔐 Área do Lojista"])

with aba_cliente:
    col_logo, col_texto = st.columns([1, 4])
    with col_logo:
        try:
            st.image("logo.png", width=90)
        except Exception:
            pass
    with col_texto:
        st.title("Sugestões Supermercado Bistecão")

    st.write("Conte o que está faltando na loja ou deixe uma sugestão. Leva menos de 1 minuto! ⏱️")

    with st.form(key="form_sugestao", clear_on_submit=True):
        nome = st.text_input("Seu nome (opcional)", placeholder="Ex: João Silva")
        telefone_input = st.text_input("Seu telefone/WhatsApp *", placeholder="Ex: (11) 99999-9999")
        sugestao = st.text_area("O que está faltando ou poderia melhorar? *", placeholder="Ex: Sinto falta de produtos sem lactose...", max_chars=500, height=150)
        enviado = st.form_submit_button("✅ Enviar Sugestão", use_container_width=True)

    if enviado:
        telefone_valido, telefone_limpo = validar_telefone(telefone_input)
        if not telefone_valido:
            st.error("⚠️ Telefone inválido! Digite um número com DDD (10 ou 11 dígitos). Ex: (11) 99999-9999")
        elif not sugestao.strip():
            st.warning("⚠️ Por favor, escreva sua sugestão antes de enviar.")
        else:
            salvar_sugestao(nome.strip(), telefone_limpo, sugestao.strip())
            st.success("🎉 Obrigado! Sua sugestão foi registrada com sucesso.")
            st.balloons()

with aba_lojista:
    senha = st.text_input("Senha do lojista:", type="password")
    
    if senha == SENHA_CORRETA:
        st.success("✅ Logado como lojista")
        
        sub_aba1, sub_aba2 = st.tabs(["📊 Ver Sugestões", "📱 Gerar QR Code"])
        
        with sub_aba1:
            st.title("📊 Sugestões Recebidas")
            sugestoes = listar_sugestoes()

            if not sugestoes:
                st.info("Ainda não há sugestões.")
            else:
                st.metric("Total de sugestões", len(sugestoes))
                
                # Exportação CSV
                csv_buffer = StringIO()
                writer = csv.writer(csv_buffer, delimiter=";")
                writer.writerow(["Nome", "Telefone", "Sugestao", "Data"])
                writer.writerows(sugestoes)
                st.download_button("⬇️ Baixar CSV", data=csv_buffer.getvalue().encode("utf-8-sig"), file_name="sugestoes.csv", mime="text/csv")

                st.divider()
                for i, s in enumerate(sugestoes):
                    with st.container(border=True):
                        col_a, col_b = st.columns([4, 1])
                        with col_a:
                            st.markdown(f"**{s[0] if s[0] else 'Anônimo'}** — _{s[3]}_")
                        with col_b:
                            if st.button("🗑️", key=f"del_{i}", help="Excluir"):
                                deletar_sugestao(i)
                                st.rerun()
                        st.write(f"📞 **Telefone:** {s[1]}")
                        st.info(f"💬 {s[2]}")
                        
        with sub_aba2:
            st.title("📱 QR Code para a Loja")
            url = st.text_input("URL do app:", value=URL_APP_PADRAO)
            if url:
                qr = qrcode.QRCode(version=None, box_size=10, border=4)
                qr.add_data(url)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                buffer = BytesIO()
                img.save(buffer, format="PNG")
                st.image(buffer.getvalue(), caption="Escaneie para testar", width=300)
                st.download_button("⬇️ Baixar QR Code (PNG)", data=buffer.getvalue(), file_name="qrcode_loja.png", mime="image/png")

    elif senha:
        st.error("❌ Senha incorreta")
