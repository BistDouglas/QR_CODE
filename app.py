import streamlit as st
import sqlite3
import csv
import re
from datetime import datetime
from io import BytesIO, StringIO
import qrcode

st.set_page_config(
    page_title="Sugestões Bistecão",
    page_icon="🏪",
    layout="centered",
    menu_items={'Get Help': None, 'Report a bug': None, 'About': None}
)

st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header[data-testid="stHeader"] {
            background: transparent;
            height: 0;
        }
        header[data-testid="stHeader"] > div:first-child {
            display: none;
        }
        [data-testid="stHeader"] button[data-testid="stExpandSidebarButton"] {
            display: block !important;
            visibility: visible !important;
            opacity: 1 !important;
        }
        [data-testid="stHeader"] button[data-testid="stSidebarCollapseButton"] {
            display: block !important;
            visibility: visible !important;
            opacity: 1 !important;
        }
        .stTextInput > div > div > input:focus, 
        .stTextArea > div > div > textarea:focus {
            border-color: #1f77b4 !important;
            box-shadow: 0 0 0 1px #1f77b4 !important;
        }
        div[data-testid="stForm"] {
            border-color: #1f77b4 !important;
        }
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

SENHA_CORRETA = get_secret("senha_lojista")
URL_APP_PADRAO = get_secret("url_app", "https://seu-app.streamlit.app")

DB_PATH = "sugestoes.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DROP TABLE IF EXISTS sugestoes")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sugestoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT,
            telefone TEXT NOT NULL,
            sugestao TEXT NOT NULL,
            data TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def salvar_sugestao(nome, telefone, sugestao):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO sugestoes (nome, telefone, sugestao, data) VALUES (?, ?, ?, ?)",
        (nome, telefone, sugestao, datetime.now().strftime("%d/%m/%Y %H:%M")),
    )
    conn.commit()
    conn.close()

def listar_sugestoes():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, nome, telefone, sugestao, data FROM sugestoes ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return rows

def deletar_sugestao(id_sugestao):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM sugestoes WHERE id = ?", (id_sugestao,))
    conn.commit()
    conn.close()

def validar_telefone(telefone):
    numeros = re.sub(r'\D', '', telefone)
    if len(numeros) in [10, 11]:
        return True, numeros
    return False, numeros

init_db()

try:
    st.sidebar.image("logo.png", width=140)
except Exception:
    pass

st.sidebar.title("Menu")
senha = st.sidebar.text_input("Senha do lojista (opcional):", type="password")

if SENHA_CORRETA is None:
    is_lojista = False
    st.sidebar.warning("⚠️ Senha não configurada. Defina `senha_lojista` em Secrets.")
else:
    is_lojista = senha == SENHA_CORRETA
    if senha and not is_lojista:
        st.sidebar.error("❌ Senha incorreta")

if is_lojista:
    modo = st.sidebar.radio("Navegar para:", ["📊 Ver Sugestões", "📱 Gerar QR Code"])
    st.sidebar.success("✅ Logado como lojista")
else:
    modo = "📝 Formulário do Cliente"
    st.sidebar.info("💡 Você está vendo a página do cliente")

if modo == "📝 Formulário do Cliente":
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

    st.divider()
    st.caption("💬 Sua sugestão nos ajuda a melhorar cada dia mais.")

elif modo == "📊 Ver Sugestões":
    st.title("📊 Sugestões Recebidas")
    sugestoes = listar_sugestoes()

    if not sugestoes:
        st.info("Ainda não há sugestões. Compartilhe o QR code com seus clientes!")
    else:
        col1, col2 = st.columns(2)
        col1.metric("Total de sugestões", len(sugestoes))
        col2.metric("Última sugestão", sugestoes[0][4].split(" ")[0] if sugestoes else "—")

        csv_buffer = StringIO()
        writer = csv.writer(csv_buffer, delimiter=";")
        writer.writerow(["ID", "Nome", "Telefone", "Sugestão", "Data"])
        writer.writerows(sugestoes)

        st.download_button(
            "⬇️ Baixar CSV",
            data=csv_buffer.getvalue().encode("utf-8-sig"),
            file_name=f"sugestoes_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

        st.divider()
        st.subheader("📋 Lista de sugestões")

        for s in sugestoes:
            with st.container(border=True):
                col_a, col_b = st.columns([4, 1])
                with col_a:
                    st.markdown(f"**#{s[0]}** — _{s[4]}_")
                with col_b:
                    if st.button("🗑️", key=f"del_{s[0]}", help="Excluir"):
                        deletar_sugestao(s[0])
                        st.rerun()

                if s[1]:
                    st.write(f"👤 **Nome:** {s[1]}")
                st.write(f"📞 **Telefone:** {s[2]}")
                st.info(f"💬 {s[3]}")

elif modo == "📱 Gerar QR Code":
    st.title("📱 QR Code para a Loja")
    st.write("Digite a URL pública do seu app e baixe o QR code para imprimir e colocar na loja.")

    url = st.text_input("URL do app:", value=URL_APP_PADRAO)

    if url:
        qr = qrcode.QRCode(version=None, box_size=10, border=4)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buffer = BytesIO()
        img.save(buffer, format="PNG")

        st.image(buffer.getvalue(), caption="Escaneie para testar", width=300)

        st.download_button(
            "⬇️ Baixar QR Code (PNG)",
            data=buffer.getvalue(),
            file_name="qrcode_loja.png",
            mime="image/png",
            use_container_width=True,
        )

        st.divider()
        st.subheader("💡 Dicas de impressão")
        st.markdown(
            """
            - Imprima em tamanho **mínimo de 5x5 cm**
            - Coloque em local **bem iluminado** e de fácil acesso
            - Adicione uma frase do tipo: *"Sua opinião vale ouro! Escaneie aqui."*
            - Teste o QR code com **2 ou 3 celulares diferentes** antes de imprimir em massa
            """
        )

st.divider()
st.caption("SUPERMERCADO BISTECÃO")
