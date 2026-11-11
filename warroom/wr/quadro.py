"""O quadro: um repositório Git onde cada fala é um arquivo MD commitado.

O que não está aqui não existe. O estado de uma deliberação é lido só destes
arquivos, então qualquer rodada pode ser retomada de onde parou.
"""
import os
import re
import subprocess
from datetime import datetime

DIR = "deliberacoes"
NOME = re.compile(r"^r(\d\d)-([a-z0-9_]+)\.md$")


class ErroQuadro(Exception):
    pass


def git(quadro, *args):
    r = subprocess.run(["git", "-C", quadro] + list(args), capture_output=True, text=True)
    if r.returncode:
        raise ErroQuadro("git %s: %s" % (" ".join(args), (r.stderr or r.stdout).strip()))
    return r.stdout


def exigir_repo(quadro):
    """O quadro é a raiz do próprio repositório, nunca uma pasta de outro."""
    try:
        raiz = git(quadro, "rev-parse", "--show-toplevel").strip()
    except (ErroQuadro, FileNotFoundError):
        raise ErroQuadro("%s não é um repositório Git (rode: wr init %s)" % (quadro, quadro))
    if os.path.realpath(raiz) != os.path.realpath(quadro):
        raise ErroQuadro("%s está dentro de outro repositório (%s); o quadro precisa do seu" % (quadro, raiz))


def commit(quadro, mensagem, *caminhos):
    git(quadro, "add", "--", *caminhos)
    if git(quadro, "status", "--porcelain", "--", *caminhos).strip():
        git(quadro, "-c", "user.name=WarRoom", "-c", "user.email=warroom@localhost",
            "commit", "-q", "-m", mensagem, "--", *caminhos)


def pasta(quadro, ident):
    if not re.match(r"^[a-z0-9-]+$", ident):
        raise ErroQuadro("id de deliberação inválido: %r" % ident)
    return os.path.join(quadro, DIR, ident)


def listar(quadro):
    d = os.path.join(quadro, DIR)
    return sorted(x for x in os.listdir(d) if os.path.isdir(os.path.join(d, x))) if os.path.isdir(d) else []


def meta(texto):
    """Cabeçalho `chave: valor` entre --- e o corpo."""
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", texto, re.S)
    if not m:
        return {}, texto
    d = {}
    for linha in m.group(1).splitlines():
        if ":" in linha:
            k, v = linha.split(":", 1)
            d[k.strip()] = v.strip()
    return d, m.group(2)


def montar(cab, corpo):
    linhas = ["%s: %s" % (k, str(v).replace("\n", " ")) for k, v in cab.items()]
    return "---\n" + "\n".join(linhas) + "\n---\n\n" + corpo.strip() + "\n"


def gravar(quadro, ident, nome, cab, corpo, mensagem):
    p = pasta(quadro, ident)
    os.makedirs(p, exist_ok=True)
    cab = dict(cab)
    cab.setdefault("data", datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z"))
    with open(os.path.join(p, nome), "w", encoding="utf-8") as f:
        f.write(montar(cab, corpo))
    commit(quadro, mensagem, os.path.join(DIR, ident, nome))


def ler(quadro, ident, nome):
    try:
        with open(os.path.join(pasta(quadro, ident), nome), encoding="utf-8") as f:
            return meta(f.read())
    except FileNotFoundError:
        return None


def falas(quadro, ident):
    """Lista ordenada de (rodada, autor, cabeçalho, corpo, nome do arquivo)."""
    p = pasta(quadro, ident)
    if not os.path.isdir(p):
        raise ErroQuadro("deliberação não existe: %s" % ident)
    saida = []
    for nome in sorted(os.listdir(p)):
        m = NOME.match(nome)
        if m:
            cab, corpo = ler(quadro, ident, nome)
            saida.append((int(m.group(1)), m.group(2), cab, corpo, nome))
    # Dentro da rodada: o dono fala antes, depois a ordem em que foi gravado.
    saida.sort(key=lambda f: (f[0], f[1] != "dono", f[1].startswith("_"), f[2].get("ordem", "99"), f[1]))
    return saida


def novo_id(quadro, titulo):
    base = re.sub(r"[^a-z0-9]+", "-", titulo.lower().encode("ascii", "ignore").decode())[:40].strip("-") or "tema"
    ident = datetime.now().strftime("%Y%m%d-%H%M") + "-" + base
    n, final = 2, ident
    while os.path.exists(os.path.join(quadro, DIR, final)):
        final, n = "%s-%d" % (ident, n), n + 1
    return final
