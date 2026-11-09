"""Renderizador seguro de Markdown para Streamlit.

A saida do modelo e os rotulos do banco sao texto nao confiavel. Links e
imagens nao devem ser renderizados: links permitem exfiltracao por clique e
imagens carregam recursos remotos automaticamente, o que vaza o IP do usuario
ou leva a sites maliciosos.
"""

from __future__ import annotations

from markdown_it import MarkdownIt
from markdown_it.token import Token

_MD = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])


def _without_links(children: list[Token]) -> list[Token]:
    """Remove links e imagens do conteudo inline, preservando o texto alternativo."""
    result: list[Token] = []
    for child in children:
        if child.type in ("link_open", "link_close"):
            continue
        if child.type == "image":
            text_token = Token("text", "", 0)
            text_token.content = child.content
            result.append(text_token)
            continue
        result.append(child)
    return result


def render_safe_html(text: str) -> str:
    """Converte Markdown em HTML, removendo links e imagens.

    O parser do markdown-it ja resolveu escapes, entidades e referencias,
    portanto nao ha sintaxe remanescente que possa ser interpretada como link
    ou imagem depois que os tokens sao removidos. Usar st.html evita que
    URLs soltas sejam convertidas em links automaticamente, como ocorre com
    st.markdown.
    """
    tokens = _MD.parse(text)
    for token in tokens:
        if token.type == "inline" and token.children:
            token.children = _without_links(token.children)
    return _MD.renderer.render(tokens, _MD.options, {})
