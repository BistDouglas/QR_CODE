import streamlit as st
import sqlite3
import csv
from datetime import datetime
from io import BytesIO, StringIO
import qrcode

# =========================================================
# Configuração inicial
# =========================================================
st.set_page_config(
    page_title="Bistecão Sugestões",
    page_icon="🏪",                 # emoji (o page_icon com PNG pode falhar)
    layout="centered",
)

# =========================================================
# Configurações via secrets (SEM fallback de senha)
# =========================================================
def get_secret(chave, padrao=None):
    try:
        return st.secrets[chave]
    except Exception:
        return padrao

SENHA_CORRETA = get_secret("senha_lojista")
URL_APP_PADRAO = get_secret("url_app", "https://seu-app.streamlit.app")

# =========================================================
# Banco de dados (SQLite)
# =========================================================
DB_PATH = "sugestoes.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sugestoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sugestao TEXT NOT NULL,
            contato TEXT,
            data TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def salvar_sugestao(sugestao, contato):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO sugestoes (sugestao, contato, data) VALUES (?, ?, ?)",
        (sugestao, contato, datetime.now().strftime("%d/%m/%Y %H:%M")),
    )
    conn.commit()
    conn.close()

def listar_sugestoes():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, sugestao, contato, data FROM sugestoes ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return rows

def deletar_sugestao(id_sugestao):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM sugestoes WHERE id = ?", (id_sugestao,))
    conn.commit()
    conn.close()

init_db()

# =========================================================
# Sidebar — Logo + Navegação + Login do lojista
# =========================================================
st.sidebar.image("logo.png", width=140)
st.sidebar.title("Menu")

senha = st.sidebar.text_input("Ignorar:", type="password")

if SENHA_CORRETA is None:
    is_lojista = False
    st.sidebar.warning("⚠️ Senha não configurada. Defina `senha_lojista` em Secrets.")
else:
    is_lojista = senha == SENHA_CORRETA
    if senha and not is_lojista:
        st.sidebar.error("❌ Senha incorreta")

if is_lojista:
    modo = st.sidebar.radio(
        "Navegar para:",
        ["📊 Ver Sugestões", "📱 Gerar QR Code"],
    )
    st.sidebar.success("✅ Logado como lojista")
else:
    modo = "📝 Formulário do Cliente"
    st.sidebar.info("💡 Você está vendo a página do cliente")

# =========================================================
# Página 1 — Formulário do Cliente (com logo no topo)
# =========================================================
if modo == "📝 Formulário do Cliente":
    col_logo, col_texto = st.columns([1, 4])
    with col_logo:
        st.image("logo.png", width=90)
    with col_texto:
        st.title("Supermercado Bistecão Sugestões.")

    st.write(
        "Conte o que está faltando na loja ou deixe uma sugestão. "
        "Leva menos de 1 minuto! ⏱️"
    )

    with st.form(key="form_sugestao", clear_on_submit=True):
        sugestao = st.text_area(
            "O que está faltando ou poderia melhorar? *",
            placeholder="Ex: Sinto falta de produtos sem lactose...",
            max_chars=500,
            height=150,
        )
        contato = st.text_input(
            "Deixe seu contato (opcional)",
            placeholder="Email ou WhatsApp (se quiser resposta)",
        )
        enviado = st.form_submit_button(
            "✅ Enviar Sugestão", use_container_width=True
        )

    if enviado:
        if not sugestao.strip():
            st.warning("⚠️ Por favor, escreva sua sugestão antes de enviar.")
        else:
            salvar_sugestao(sugestao.strip(), contato.strip())
            st.success("🎉 Obrigado! Sua sugestão foi registrada com sucesso.")
            st.balloons()

    st.divider()
    st.caption("💬 Sua sugestão nos ajuda a melhorar cada dia mais.")

# =========================================================
# Página 2 — Painel do Lojista
# =========================================================
elif modo == "📊 Ver Sugestões":
    st.title("📊 Sugestões Recebidas")
    sugestoes = listar_sugestoes()

    if not sugestoes:
        st.info(
            "Ainda não há sugestões. Compartilhe o QR code com seus clientes!"
        )
    else:
        col1, col2 = st.columns(2)
        col1.metric("Total de sugestões", len(sugestoes))
        col2.metric(
            "Última sugestão",
            sugestoes[0][3].split(" ")[0] if sugestoes else "—",
        )

        csv_buffer = StringIO()
        writer = csv.writer(csv_buffer, delimiter=";")
        writer.writerow(["ID", "Sugestão", "Contato", "Data"])
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
                    st.markdown(f"**#{s[0]}** — _{s[3]}_")
                with col_b:
                    if st.button("🗑️", key=f"del_{s[0]}", help="Excluir"):
                        deletar_sugestao(s[0])
                        st.rerun()

                st.write(s[1])
                if s[2]:
                    st.caption(f"📞 Contato: {s[2]}")

# =========================================================
# Página 3 — Gerador de QR Code
# =========================================================
elif modo == "📱 Gerar QR Code":
    st.title("📱 QR Code para a Loja")
    st.write(
        "Digite a URL pública do seu app e baixe o QR code para imprimir "
        "e colocar na loja."
    )

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

# =========================================================
# Rodapé
# =========================================================
st.divider()
st.caption("SUPERMERCADO BISTECÃO")