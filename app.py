"""Aplicativo de sugestões do Supermercado Bistecão.

Fluxo do cliente: registro de sugestões com validação de telefone.
Área do lojista: consulta, exportação, exclusão e geração do QR Code de acesso.

Os dados são persistidos no Google Sheets configurado em ``st.secrets``.
"""
from __future__ import annotations

import hmac
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import qrcode
import streamlit as st
from streamlit_gsheets import GSheetsConnection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

APP_TITLE = "Sugestões | Supermercado Bistecão"
BASE_DIR = Path(__file__).resolve().parent
LOGO_PATH = BASE_DIR / "logo.png"
FAVICON_PATH = BASE_DIR / "favicon.png"
COLUNAS = ("Nome", "Telefone", "Sugestao", "Data")
DATE_FORMAT = "%d/%m/%Y %H:%M"
MAX_NOME = 80
MAX_SUGESTAO = 500

AUTH_KEY = "lojista_autenticado"
DELETE_CONFIRM_KEY = "sugestao_para_excluir"
INPUT_KEYS = ("campo_nome", "campo_telefone", "campo_sugestao")
FORM_RESET_KEY = "form_sugestao_reset"
FORM_RESET_APPLIED_KEY = "form_sugestao_reset_aplicado"
FORM_SUCCESS_KEY = "form_sugestao_sucesso"

CSS = """
<style>
  :root {
    --brand: #2f81f7;
    --surface: #161b22;
    --border: #30363d;
    --muted: #8b949e;
  }
  .block-container { max-width: 900px; padding-top: 2.2rem; padding-bottom: 3rem; }
  .app-title h1 { margin: 0; font-size: 1.55rem; letter-spacing: -0.02em; }
  .app-title p { margin: 0.35rem 0 0; color: var(--muted); font-size: 0.93rem; }
  div[data-testid="stForm"] {
    border: 1px solid var(--border) !important;
    border-radius: 14px !important;
    padding: 1.25rem !important;
  }
  .stTextInput input:focus, .stTextArea textarea:focus {
    border-color: var(--brand) !important;
    box-shadow: 0 0 0 1px var(--brand) !important;
  }
  footer, #MainMenu, .stDeployButton { visibility: hidden; }
  header[data-testid="stHeader"] { background: transparent; height: 0; }
  div[data-testid="stToolbar"] { visibility: hidden; height: 0; position: fixed; }
</style>
"""


# ---------------------------------------------------------------------------
# Modelos e erros
# ---------------------------------------------------------------------------


class ConfigurationError(Exception):
    """Configuração obrigatória ausente ou inválida."""


class DataAccessError(Exception):
    """Falha de leitura/escrita na fonte de dados."""


@dataclass(frozen=True)
class Config:
    """Configurações carregadas dos secrets."""

    senha_lojista: str
    url_app: str


@dataclass(frozen=True)
class Sugestao:
    """Uma sugestão registrada pelo cliente."""

    nome: str
    telefone: str
    mensagem: str
    criado_em: str

    def para_linha(self) -> dict[str, str]:
        """Retorna a sugestão no formato de colunas da planilha."""
        return {
            "Nome": self.nome,
            "Telefone": self.telefone,
            "Sugestao": self.mensagem,
            "Data": self.criado_em,
        }


# ---------------------------------------------------------------------------
# Configuração, autenticação e validações
# ---------------------------------------------------------------------------


def ler_secret(chave: str, *, obrigatorio: bool = True, padrao: str = "") -> str:
    """Lê um secret sem expor seu valor em mensagens de erro."""
    try:
        valor = st.secrets[chave]
    except Exception:
        if obrigatorio:
            raise ConfigurationError(f"O secret '{chave}' não foi configurado.") from None
        return padrao

    texto = "" if valor is None else str(valor).strip()
    if not texto and obrigatorio:
        raise ConfigurationError(f"O secret '{chave}' está vazio.")
    return texto or padrao


def carregar_config() -> Config:
    """Carrega a configuração da aplicação."""
    return Config(
        senha_lojista=ler_secret("senha_lojista"),
        url_app=ler_secret("url_app", obrigatorio=False),
    )


def autenticar(senha_informada: str, senha_configurada: str) -> bool:
    """Compara senhas em tempo constante; nunca usa fallback embutido no código."""
    if not senha_configurada:
        return False
    return hmac.compare_digest(
        (senha_informada or "").encode("utf-8"),
        senha_configurada.encode("utf-8"),
    )


def normalizar_telefone(valor: str) -> str | None:
    """Valida DDD e retorna somente os dígitos, ou None quando inválido."""
    digitos = re.sub(r"\D", "", valor or "")
    if len(digitos) not in (10, 11):
        return None
    if not 11 <= int(digitos[:2]) <= 99:
        return None
    if len(digitos) == 11 and digitos[2] != "9":
        return None
    return digitos


def formatar_telefone(digitos: str) -> str:
    """Formata dígitos para exibição: (11) 99999-9999."""
    if len(digitos) == 11:
        return f"({digitos[:2]}) {digitos[2:7]}-{digitos[7:]}"
    return f"({digitos[:2]}) {digitos[2:6]}-{digitos[6:]}"


def validar_sugestao(nome: str, telefone: str, mensagem: str) -> tuple[Sugestao | None, str | None]:
    """Valida os campos do formulário e devolve a sugestão ou o erro."""
    nome_limpo = (nome or "").strip()[:MAX_NOME] or "Anônimo"
    telefone_valido = normalizar_telefone(telefone)
    mensagem_limpa = (mensagem or "").strip()

    if not telefone_valido:
        return None, "Informe um telefone com DDD (10 ou 11 dígitos). Ex.: (11) 99999-9999."
    if len(mensagem_limpa) < 5:
        return None, "Descreva a sugestão com pelo menos 5 caracteres."
    if len(mensagem_limpa) > MAX_SUGESTAO:
        return None, f"A sugestão deve ter no máximo {MAX_SUGESTAO} caracteres."

    return Sugestao(
        nome=nome_limpo,
        telefone=telefone_valido,
        mensagem=mensagem_limpa,
        criado_em=datetime.now().strftime(DATE_FORMAT),
    ), None


def validar_url(valor: str) -> tuple[str | None, str | None]:
    """Valida e normaliza a URL usada no QR Code."""
    url = (valor or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None, "Informe uma URL válida, começando com http:// ou https://."
    return parsed.geturl(), None


# ---------------------------------------------------------------------------
# Camada de dados
# ---------------------------------------------------------------------------


@st.cache_resource(show_spinner=False)
def obter_conexao() -> GSheetsConnection:
    """Cria (e memoiza) a conexão com o Google Sheets."""
    try:
        return st.connection("gsheets", type=GSheetsConnection)
    except Exception as exc:
        logger.exception("Falha ao conectar ao Google Sheets")
        raise DataAccessError("Não foi possível conectar à planilha. Verifique os secrets.") from exc


def carregar_sugestoes(conn: GSheetsConnection) -> pd.DataFrame:
    """Lê a planilha e garante o schema esperado."""
    try:
        df = conn.read(ttl=0)
    except Exception as exc:
        logger.exception("Falha ao ler sugestões")
        raise DataAccessError("Não foi possível carregar as sugestões.") from exc

    if df is None or df.empty:
        return pd.DataFrame(columns=list(COLUNAS))

    df = df.copy()
    for coluna in COLUNAS:
        if coluna not in df.columns:
            df[coluna] = ""

    return df[list(COLUNAS)].fillna("").astype(str).reset_index(drop=True)


def salvar_sugestao(conn: GSheetsConnection, sugestao: Sugestao) -> None:
    """Acrescenta uma sugestão ao final da planilha."""
    df = carregar_sugestoes(conn)
    df_final = pd.concat([df, pd.DataFrame([sugestao.para_linha()])], ignore_index=True)
    try:
        conn.update(data=df_final)
    except Exception as exc:
        logger.exception("Falha ao salvar sugestão")
        raise DataAccessError("Não foi possível salvar a sugestão. Tente novamente.") from exc


def excluir_sugestao(conn: GSheetsConnection, indice: int) -> None:
    """Remove uma sugestão pelo índice exibido na listagem."""
    df = carregar_sugestoes(conn)
    if indice not in df.index:
        raise DataAccessError("Sugestão não encontrada. Recarregue a página.")
    try:
        conn.update(data=df.drop(index=indice).reset_index(drop=True))
    except Exception as exc:
        logger.exception("Falha ao excluir sugestão")
        raise DataAccessError("Não foi possível excluir a sugestão. Tente novamente.") from exc


def gerar_qrcode(url: str) -> bytes:
    """Gera o QR Code da URL em PNG."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    imagem = qr.make_image(fill_color="#111111", back_color="white")

    buffer = BytesIO()
    imagem.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------


def aplicar_estilo() -> None:
    """Aplica o CSS da aplicação."""
    st.markdown(CSS, unsafe_allow_html=True)


def renderizar_cabecalho() -> None:
    """Exibe logo e título da aplicação."""
    col_logo, col_titulo = st.columns([1, 6], gap="medium")
    with col_logo:
        try:
            st.image(LOGO_PATH, width=76)
        except (FileNotFoundError, OSError):
            pass
    with col_titulo:
        st.markdown(
            f"""<div class="app-title">
                <h1>{APP_TITLE}</h1>
                <p>Conte o que está faltando ou o que pode melhorar. Leva menos de um minuto.</p>
            </div>""",
            unsafe_allow_html=True,
        )


def renderizar_cliente(conn: GSheetsConnection) -> None:
    """Formulário público de envio de sugestões."""
    renderizar_cabecalho()

    if st.session_state.pop(FORM_SUCCESS_KEY, False):
        st.success("Sugestão registrada com sucesso. Obrigado por nos ajudar a melhorar!")

    # O reset precisa ser aplicado ANTES da criação dos widgets.
    reset_atual = st.session_state.get(FORM_RESET_KEY, 0)
    if st.session_state.get(FORM_RESET_APPLIED_KEY, 0) != reset_atual:
        for chave in INPUT_KEYS:
            st.session_state[chave] = ""
        st.session_state[FORM_RESET_APPLIED_KEY] = reset_atual

    st.subheader("Deixe sua sugestão")

    with st.form("form_sugestao", clear_on_submit=False):
        nome = st.text_input(
            "Nome (opcional)",
            max_chars=MAX_NOME,
            placeholder="Como podemos te chamar?",
            key=INPUT_KEYS[0],
        )
        telefone = st.text_input(
            "Telefone / WhatsApp *",
            placeholder="(11) 99999-9999",
            help="Informe o DDD e o número com 10 ou 11 dígitos.",
            key=INPUT_KEYS[1],
        )
        mensagem = st.text_area(
            "Sua sugestão *",
            placeholder="Ex.: Sinto falta de produtos sem lactose na seção de laticínios.",
            max_chars=MAX_SUGESTAO,
            height=140,
            key=INPUT_KEYS[2],
        )
        enviado = st.form_submit_button("Enviar sugestão", use_container_width=True)

    if not enviado:
        return

    sugestao, erro = validar_sugestao(nome, telefone, mensagem)
    if erro:
        st.error(erro)
        return

    try:
        salvar_sugestao(conn, sugestao)
    except DataAccessError as exc:
        st.error(str(exc))
        return

    st.session_state[FORM_SUCCESS_KEY] = True
    st.session_state[FORM_RESET_KEY] = reset_atual + 1
    st.rerun()


def renderizar_login(config: Config) -> None:
    """Autenticação do lojista."""
    st.subheader("Área do lojista")
    st.caption("Acesso restrito à equipe da loja.")

    with st.form("login_lojista", clear_on_submit=True):
        senha = st.text_input("Senha", type="password", placeholder="Digite a senha de acesso")
        entrar = st.form_submit_button("Entrar", use_container_width=True)

    if entrar and autenticar(senha, config.senha_lojista):
        st.session_state[AUTH_KEY] = True
        st.rerun()
    elif entrar:
        st.error("Senha incorreta. Tente novamente.")


def renderizar_cartao_sugestao(conn: GSheetsConnection, indice: int, linha: pd.Series) -> None:
    """Exibe uma sugestão com opção de exclusão confirmada."""
    with st.container(border=True):
        col_info, col_acao = st.columns([5, 1])
        with col_info:
            st.markdown(f"**{linha['Nome'] or 'Anônimo'}**")
            st.caption(linha["Data"])
        with col_acao:
            if st.button("Excluir", key=f"excluir_{indice}"):
                st.session_state[DELETE_CONFIRM_KEY] = indice

        st.caption(f"Contato: {formatar_telefone(linha['Telefone'])}")
        st.write(linha["Sugestao"])

        if st.session_state.get(DELETE_CONFIRM_KEY) != indice:
            return

        st.warning("Excluir esta sugestão? Essa ação não pode ser desfeita.")
        col_confirmar, col_cancelar = st.columns([1, 1])
        if col_confirmar.button("Confirmar exclusão", key=f"confirmar_{indice}"):
            try:
                excluir_sugestao(conn, indice)
            except DataAccessError as exc:
                st.error(str(exc))
                return
            st.session_state.pop(DELETE_CONFIRM_KEY, None)
            st.success("Sugestão excluída.")
            st.rerun()
        if col_cancelar.button("Cancelar", key=f"cancelar_{indice}"):
            st.session_state.pop(DELETE_CONFIRM_KEY, None)
            st.rerun()


def renderizar_lista(conn: GSheetsConnection) -> None:
    """Lista, resume e exporta as sugestões recebidas."""
    try:
        df = carregar_sugestoes(conn)
    except DataAccessError as exc:
        st.error(str(exc))
        return

    hoje = datetime.now().strftime("%d/%m/%Y")
    col_total, col_hoje = st.columns(2)
    col_total.metric("Total de sugestões", len(df))
    col_hoje.metric("Recebidas hoje", int(df["Data"].str.startswith(hoje).sum()))

    if df.empty:
        st.info("Ainda não há sugestões registradas.")
        return

    csv_bytes = df.to_csv(index=False, sep=";").encode("utf-8-sig")
    st.download_button(
        "Baixar relatório CSV",
        data=csv_bytes,
        file_name=f"sugestoes_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )
    st.divider()

    for indice, linha in df.iterrows():
        renderizar_cartao_sugestao(conn, indice, linha)


def renderizar_qrcode(config: Config) -> None:
    """Gera e disponibiliza o QR Code de acesso ao aplicativo."""
    st.subheader("QR Code de acesso")
    st.caption("Imprima o código e cole na loja para os clientes acessarem o formulário.")

    url = st.text_input(
        "Endereço do aplicativo",
        value=config.url_app,
        placeholder="https://seu-app.streamlit.app/",
        help="Defina 'url_app' nos secrets para preencher automaticamente.",
    )
    if not url:
        st.info("Informe a URL do aplicativo ou configure o secret 'url_app'.")
        return

    url_valida, erro = validar_url(url)
    if erro:
        st.error(erro)
        return

    png = gerar_qrcode(url_valida)
    st.image(png, caption="Aponte a câmera do celular para testar.", width=280)
    st.download_button(
        "Baixar QR Code (PNG)",
        data=png,
        file_name="qrcode_sugestoes.png",
        mime="image/png",
    )


def renderizar_lojista(conn: GSheetsConnection, config: Config) -> None:
    """Painel administrativo do lojista."""
    col_sessao, col_sair = st.columns([5, 1])
    with col_sessao:
        st.caption(f"Sessão do lojista · {datetime.now().strftime('%d/%m/%Y')}")
    with col_sair:
        if st.button("Sair", use_container_width=True):
            st.session_state[AUTH_KEY] = False
            st.session_state.pop(DELETE_CONFIRM_KEY, None)
            st.rerun()

    tab_lista, tab_qr = st.tabs(["📊 Sugestões recebidas", "📱 QR Code"])
    with tab_lista:
        renderizar_lista(conn)
    with tab_qr:
        renderizar_qrcode(config)


def main() -> None:
    """Ponto de entrada da aplicação."""
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon=str(FAVICON_PATH),
        layout="centered",
        menu_items={"Get Help": None, "Report a bug": None, "About": None},
    )
    aplicar_estilo()

    try:
        config = carregar_config()
        conn = obter_conexao()
    except ConfigurationError as exc:
        st.error(f"Configuração incompleta: {exc}")
        st.stop()
    except DataAccessError as exc:
        st.error(str(exc))
        st.stop()

    tab_cliente, tab_lojista = st.tabs(["🛒 Deixar sugestão", "🔐 Área do lojista"])
    with tab_cliente:
        renderizar_cliente(conn)
    with tab_lojista:
        if st.session_state.get(AUTH_KEY, False):
            renderizar_lojista(conn, config)
        else:
            renderizar_login(config)


if __name__ == "__main__":
    main()
