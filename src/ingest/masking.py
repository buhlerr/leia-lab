"""Mascaramento de PII e segmentacao de texto de contratos: a fronteira de privacidade.

Porta fiel de ``leia-kb-legislacao/scripts/langflow/mask_core.py`` (regras de
nome e regex de dados pessoais) mais utilitarios de alias e split.

``MaskedText`` e o unico texto que pode sair do processo (LLM, Jev, embeddings) ou ser gravado
(``analyses``, ``kb_chunks``). So este modulo o cria. Cada funcao de fronteira e decorada com
``requires_masked`` e recusa ``str`` comum com ``UnmaskedTextError``, antes de qualquer rastreio.
"""

from __future__ import annotations

import hashlib
import inspect
import re
from collections.abc import Awaitable, Callable
from functools import wraps
from pathlib import PurePath
from typing import Any, TypeVar

_FIX = (
    "pass it through src.ingest.masking.mask_personal_data first: mask the whole document once, "
    "outside the graph (analyze(), ingest() and ask() do this)"
)
_KEY = object()


class MaskedText(str):
    """Texto que passou por este modulo. Fatiar ou concatenar devolve ``str`` comum."""

    __slots__ = ()

    def __new__(cls, value: str, *, _key: object = None) -> MaskedText:
        if _key is not _KEY:
            raise TypeError(f"MaskedText is created only by src.ingest.masking; {_FIX}")
        return super().__new__(cls, value)

    def __reduce__(self) -> tuple[Any, ...]:
        return (_masked, (str(self),))


def _masked(value: str) -> MaskedText:
    return MaskedText(value, _key=_KEY)


class UnmaskedTextError(ValueError):
    """Texto comum (``str``, nao ``MaskedText``) tentou cruzar a fronteira de privacidade."""


def require_masked(value: object, *, what: str) -> None:
    """Recusa qualquer ``str`` comum em ``value`` (str, ou dict/list/tuple que as contenham).

    A mensagem diz onde o texto tentou passar e como corrigir; nunca cita o texto.
    """
    if isinstance(value, MaskedText):
        return
    if isinstance(value, str):
        raise UnmaskedTextError(f"{what} got unmasked text; {_FIX}")
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, (list, tuple)):
        for item in value:
            require_masked(item, what=what)


_F = TypeVar("_F", bound=Callable[..., Awaitable[Any]])


def requires_masked(*params: str) -> Callable[[_F], _F]:
    """Marca uma funcao assincrona como fronteira: ``params`` so aceitam ``MaskedText``.

    Fica por fora de ``client_span``: a recusa acontece antes de o rastreio registrar a entrada.
    """

    def decorate(fn: _F) -> _F:
        sig = inspect.signature(fn)

        @wraps(fn)
        async def guarded(*args: Any, **kwargs: Any) -> Any:
            bound = sig.bind(*args, **kwargs)
            for p in params:
                require_masked(bound.arguments.get(p), what=f"{fn.__name__}({p})")
            return await fn(*args, **kwargs)

        return guarded  # type: ignore[return-value]

    return decorate

_P = r"[A-ZÀ-Ý][A-Za-zÀ-ÿ'´-]+"
_L = r"(?:\s+(?:de|da|do|dos|das|e|DE|DA|DO|DOS|DAS|E))?"
_NC = rf"{_P}(?:{_L}\s+{_P}){{1,7}}"
_Q = (
    r"(?i:brasileir[oa]|portugues[a]?|argentin[oa]|uruguai[oa]|estrangeir[oa]|naturalizad[oa]"
    r"|solteir[oa]|casad[oa]|divorciad[oa]|vi[úu]v[oa]|separad[oa]|maior\s+e\s+capaz)"
)
_PARTY_LABELS = (
    r"nome(?:\s+completo)?",
    r"locador[a]?",
    r"locat[áa]ri[oa]",
    r"inquilin[oa]",
    r"propriet[áa]ri[oa]",
    r"fiador[a]?",
    r"c[ôo]njuge",
    r"contratante",
    r"contratad[oa]",
    r"outorgante",
    r"outorgad[oa]",
    r"interveniente",
    r"anuente",
    r"procurador[a]?",
    r"representantes?(?:\s+lega(?:l|is))?",
    r"respons[áa]ve(?:l|is)",
    r"assinante",
    r"testemunha(?:\s*\d)?",
)
_PLURAL_SUFFIX = r"(?:e?s)?(?:\s?\([aoe]?s?\)s?|/[ao]s?)*"
_R = rf"(?i:(?:{'|'.join(_PARTY_LABELS)}){_PLURAL_SUFFIX})"
_NAME_RULES = [
    re.compile(rf"({_NC})(?=\s*,\s*{_Q})"),
    re.compile(rf"{_R}\s*:\s*({_NC})"),
    re.compile(rf"(?i:\bSr[a]?\.|\bSenhor[a]?)\s+({_NC})"),
    re.compile(rf"({_NC})\s*,?\s*(?i:inscrit[oa]\s+no\s+|portador[a]?\s+do\s+)?C\.?P\.?F\b"),
]
_IGNORE = re.compile(
    r"(?i)^(contrato|cl[áa]usula|locador|locat[áa]ri|fiador|parte|partes|pessoa"
    r"|imobili[áa]ria|administradora|empresa|ltda|s\.?a\.?)\b"
)
_RULES = [
    (re.compile(r"(?i)\b(endere[çc]o(?:\s+completo)?\s*:)\s*[^●]{3,120}?(?=\s*(?:●|\bCNH\b|\bCPF\b|\bRG\b|\[))"), r"\1 [ENDERECO]"),
    (re.compile(r"(?i)\b((?:situad[oa]|localizad[oa])\s+(?:na|no|em|à|a)\s+)(?=[^.;]{0,160}\d)[^.;]{5,160}"), r"\1[ENDERECO]"),
    (re.compile(r"(?i)\b(residente\s+e\s+domiciliad[oa]\s+(?:na|no|em|à|a)\s+)[^;\n]{5,180}"), r"\1[ENDERECO]"),
    (re.compile(r"(?i)\b(?:rua|r\.|avenida|av\.|alameda|travessa|estrada|rodovia|pra[çc]a|largo)\s+[^,]{2,80},?\s*(?:n[º°o.]*\s*)?\d{1,6}\b"), "[ENDERECO]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"(?<![\d./-])\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?![\d/-])"), "[CNPJ]"),
    (re.compile(r"(?<![\d./-])\d{3}[.\s]?\d{3}[.\s]?\d{3}[-\s]?\d{2}(?![\d/-])"), "[CPF]"),
    (re.compile(r"(?i)\b((?:RG|R\.G\.|identidade|C\.I\.)(?:\s*(?:n[º°o.]*|sob o|:))*\s*)[\dXx][\dXx.\-]{3,14}"), r"\1[RG]"),
    (re.compile(r"(?:\+?55[\s-]?)?\(\d{2}\)\s?9?\d{4}[\s-]?\d{4}\b|(?<![\d.,/-])\d{2}\s9\d{4}-\d{4}\b"), "[TELEFONE]"),
    (re.compile(r"(?<![\d-])\d{2}\.?\d{3}-\d{3}(?![\d-])"), "[CEP]"),
    (re.compile(r"(?i)\b((?:ag[êe]ncia|conta(?:\s+corrente)?|c/c)\s*(?:n[º°o.]*|:)?\s*)[\d][\d.\-]{2,}"), r"\1[DADO_BANCARIO]"),
]


def mask_personal_data(text: str) -> MaskedText:
    """Substitui PII por marcadores; nomes mais longos primeiro. ``MaskedText`` volta como veio."""
    if isinstance(text, MaskedText):
        return text
    nomes: set[str] = set()
    for regra in _NAME_RULES:
        for m in regra.finditer(text):
            nome = m.group(1).strip()
            if not _IGNORE.match(nome):
                nomes.add(nome)
    for nome in sorted(nomes, key=len, reverse=True):
        padrao = r"\s+".join(re.escape(p) for p in nome.split())
        text = re.sub(padrao, "[NOME]", text, flags=re.IGNORECASE)
    for regra, troca in _RULES:
        text = regra.sub(troca, text)
    return _masked(text)


def mask_payload(value: Any) -> Any:
    """``mask_personal_data`` em cada ``str`` de um payload (dict/list/tuple) montado no grafo."""
    if isinstance(value, str):
        return mask_personal_data(value)
    if isinstance(value, dict):
        return {k: mask_payload(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(mask_payload(v) for v in value)
    return value


def resolve_doc_alias(filename: str, doc_name: str = "") -> MaskedText:
    """Nome publico do documento: ``doc_name`` ou ``documento-<sha8>.<ext>``; o nome real nunca."""
    if doc_name:
        return _masked(doc_name)
    digest = hashlib.sha256(filename.encode("utf-8")).hexdigest()[:8]
    return _masked(f"documento-{digest}{PurePath(filename).suffix}")


def split_contract_text(
    text: MaskedText,
    chunk_size: int = 1200,
    chunk_overlap: int = 200,
    separator: str = "\n",
) -> list[MaskedText]:
    """Agrupa segmentos separados por ``separator`` ate ``chunk_size`` caracteres.

    Cada novo chunk reinicia com ate ``chunk_overlap`` caracteres finais do
    anterior. Nenhum chunk excede ``chunk_size``. Pedaco de texto mascarado continua mascarado.
    """
    require_masked(text, what="split_contract_text(text)")
    pieces: list[str] = []
    for seg in text.split(separator):
        seg = seg.strip()
        while len(seg) > chunk_size:  # segmento maior que o chunk: corta duro
            pieces.append(seg[:chunk_size])
            seg = seg[chunk_size:]
        if seg:
            pieces.append(seg)

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}{separator}{piece}" if current else piece
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        chunks.append(current)
        carry = current[-chunk_overlap:] if chunk_overlap > 0 else ""
        candidate = f"{carry}{separator}{piece}" if carry else piece
        if len(candidate) > chunk_size:  # overlap nao cabe: descarta-o
            candidate = piece
        current = candidate
    if current:
        chunks.append(current)
    return [_masked(c) for c in chunks]
