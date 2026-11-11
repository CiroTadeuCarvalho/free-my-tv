"""Lê o warroom.toml que fica na raiz do quadro."""
import os
import tomllib
from dataclasses import dataclass, field

ARQUIVO = "warroom.toml"


class ErroConfig(Exception):
    pass


@dataclass
class Assento:
    id: str
    nome: str
    papel: str = ""
    tipo: str = "cli"            # cli | simulado | externo
    comando: list = field(default_factory=list)
    entrada: str = "stdin"       # stdin | arg | arquivo ({arquivo} no comando)
    tty: bool = False            # roda num pseudo-terminal (só Linux/macOS)
    replica: bool = False        # assento da réplica combativa
    relator: bool = False        # escreve a síntese da decisão
    limite: int = 900            # segundos por chamada
    roteiro: list = field(default_factory=list)  # só no tipo simulado


@dataclass
class Trabalhador:
    nome: str
    url: str
    modelo: str
    chave_env: str = ""
    local: bool = False
    limite: int = 120


@dataclass
class Config:
    dono: str = "Dono"
    rodadas_sem_objecao: int = 2
    disjuntor: int = 20
    quorum: int = 3
    assento_caido: str = "segue"  # segue | pausa
    limite_quadro: int = 60000    # caracteres do quadro enviados a cada assento
    assentos: list = field(default_factory=list)
    trabalhadores: list = field(default_factory=list)
    execucao: list = field(default_factory=list)
    execucao_limite: int = 3600


def _so(campos, dados, onde):
    sobra = set(dados) - set(campos)
    if sobra:
        raise ErroConfig("%s: campo desconhecido: %s" % (onde, ", ".join(sorted(sobra))))


def carregar(quadro):
    caminho = os.path.join(quadro, ARQUIVO)
    if not os.path.isfile(caminho):
        raise ErroConfig("não achei %s (rode: wr init %s)" % (caminho, quadro))
    with open(caminho, "rb") as f:
        try:
            dados = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ErroConfig("%s: %s" % (caminho, e))
    _so({"dono", "protocolo", "assento", "trabalhador", "execucao"}, dados, ARQUIVO)
    c = Config(dono=dados.get("dono", "Dono"))
    p = dados.get("protocolo", {})
    _so({"rodadas_sem_objecao", "disjuntor", "quorum", "assento_caido", "limite_quadro"}, p, "[protocolo]")
    for k, v in p.items():
        setattr(c, k, v)
    if c.assento_caido not in ("segue", "pausa"):
        raise ErroConfig('[protocolo] assento_caido é "segue" ou "pausa"')
    if c.rodadas_sem_objecao < 1 or c.disjuntor < c.rodadas_sem_objecao:
        raise ErroConfig("[protocolo] disjuntor precisa ser >= rodadas_sem_objecao >= 1")
    campos = set(Assento.__dataclass_fields__)
    for a in dados.get("assento", []):
        _so(campos, a, "[[assento]]")
        if "id" not in a:
            raise ErroConfig("[[assento]] sem id")
        a.setdefault("nome", a["id"])
        c.assentos.append(Assento(**a))
    ids = [a.id for a in c.assentos]
    if len(ids) != len(set(ids)):
        raise ErroConfig("dois assentos com o mesmo id")
    for a in c.assentos:
        if not a.id.isalnum() or a.id == "dono":
            raise ErroConfig("id de assento inválido: %r (só letras e números; 'dono' é reservado)" % a.id)
        if a.tipo not in ("cli", "simulado", "externo"):
            raise ErroConfig("assento %s: tipo desconhecido %r" % (a.id, a.tipo))
        if a.tipo == "cli" and not a.comando:
            raise ErroConfig("assento %s: falta comando" % a.id)
        if a.entrada not in ("stdin", "arg", "arquivo"):
            raise ErroConfig("assento %s: entrada é stdin, arg ou arquivo" % a.id)
    if not c.assentos:
        raise ErroConfig("nenhum [[assento]] configurado")
    if sum(a.replica for a in c.assentos) != 1:
        raise ErroConfig("exatamente um assento precisa ter replica = true")
    if c.quorum > len(c.assentos) or c.quorum < 1:
        raise ErroConfig("[protocolo] quorum fora do número de assentos")
    campos = set(Trabalhador.__dataclass_fields__)
    for t in dados.get("trabalhador", []):
        _so(campos, t, "[[trabalhador]]")
        try:
            c.trabalhadores.append(Trabalhador(**t))
        except TypeError:
            raise ErroConfig("[[trabalhador]] precisa de nome, url e modelo")
    e = dados.get("execucao", {})
    _so({"comando", "limite"}, e, "[execucao]")
    c.execucao = e.get("comando", [])
    c.execucao_limite = e.get("limite", 3600)
    return c
