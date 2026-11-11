"""wr: a linha de comando do WarRoom."""
import argparse
import os
import shutil
import sys

from . import config as C
from . import protocolo as P
from . import quadro as Q
from .assentos import AssentoCaiu, chamar, disponivel
from .trabalhadores import SemTrabalhador, pedir

AQUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _quadro(args):
    q = args.quadro or os.environ.get("WR_QUADRO") or os.getcwd()
    q = os.path.abspath(q)
    Q.exigir_repo(q)
    return q, C.carregar(q)


def cmd_init(args):
    q = os.path.abspath(args.dir)
    os.makedirs(q, exist_ok=True)
    if not os.path.isdir(os.path.join(q, ".git")):
        Q.git(q, "init", "-q")
    Q.exigir_repo(q)
    destino = os.path.join(q, C.ARQUIVO)
    if not os.path.exists(destino):
        shutil.copy(os.path.join(AQUI, "warroom.exemplo.toml"), destino)
    os.makedirs(os.path.join(q, Q.DIR), exist_ok=True)
    with open(os.path.join(q, Q.DIR, ".gitkeep"), "a"):
        pass
    Q.commit(q, "WarRoom: quadro criado", C.ARQUIVO, os.path.join(Q.DIR, ".gitkeep"))
    print("Quadro pronto em %s\nAjuste %s e confira com: wr --quadro %s assentos" % (q, destino, q))


def cmd_assentos(args):
    q, cfg = _quadro(args)
    ruim = 0
    for a in cfg.assentos:
        marcas = [m for m, v in (("réplica", a.replica), ("relator", a.relator)) if v]
        if a.tipo != "cli":
            situacao = a.tipo
        elif not disponivel(a):
            situacao, ruim = "FALTA o comando `%s`" % a.comando[0], ruim + 1
        elif args.testar:
            try:
                chamar(a, "Responda só com a palavra: pronto")
                situacao = "respondeu"
            except AssentoCaiu as e:
                situacao, ruim = "NÃO respondeu: %s" % str(e)[:200], ruim + 1
        else:
            situacao = "comando encontrado"
        print("%-10s %-22s %s%s" % (a.id, " ".join(a.comando)[:22], situacao,
                                    "  (%s)" % ", ".join(marcas) if marcas else ""))
    for t in cfg.trabalhadores:
        if args.testar:
            try:
                pedir([t], "Responda só: pronto", "pronto?", sensivel=False)
                situacao = "respondeu"
            except SemTrabalhador as e:
                situacao = "NÃO respondeu: %s" % str(e)[:200]
        else:
            situacao = "local" if t.local else ("chave em %s: %s" % (
                t.chave_env, "ok" if os.environ.get(t.chave_env) else "VAZIA") if t.chave_env else "sem chave")
        print("trabalhador %-12s %-28s %s" % (t.nome, t.modelo[:28], situacao))
    return 1 if ruim else 0


def _fim(fase):
    return {"fechada": 0, "escalada": 2, "aberta": 0}[fase]


def cmd_abrir(args):
    q, cfg = _quadro(args)
    texto = args.texto or ""
    if args.arquivo:
        with open(args.arquivo, encoding="utf-8") as f:
            texto = (texto + "\n\n" + f.read()).strip()
    if not texto:
        texto = args.titulo
    ident = P.abrir(q, cfg, args.titulo, texto, args.sensivel)
    print("Deliberação %s aberta." % ident)
    if args.sem_rodar:
        return 0
    return _fim(P.rodar(q, ident, cfg, max_rodadas=args.rodadas))


def cmd_continuar(args):
    q, cfg = _quadro(args)
    return _fim(P.rodar(q, args.id, cfg, max_rodadas=args.rodadas))


def cmd_falar(args):
    q, cfg = _quadro(args)
    rodada = P.falar(q, args.id, cfg, args.texto)
    print("Gravado. Entra antes da rodada %d. Retome com: wr continuar %s" % (rodada, args.id))


def cmd_estado(args):
    q, cfg = _quadro(args)
    for ident in ([args.id] if args.id else Q.listar(q)):
        e = P.estado(q, ident, cfg)
        print("%s  [%s]  rodadas: %d, limpas seguidas: %d/%d  %s%s" % (
            ident, e["fase"], e["ultima"], e["limpas"], cfg.rodadas_sem_objecao, e["titulo"],
            "  (sensível)" if e["sensivel"] else ""))
        if args.id:
            for f in e["falas"]:
                if f[1] == "_ata":
                    print("\n" + f[3].strip())


def cmd_mcp(args):
    from .mcp import servir
    q, cfg = _quadro(args)
    servir(q, cfg, tuple(args.assento or ()))


def cmd_demo(args):
    import tempfile
    q = tempfile.mkdtemp(prefix="warroom-demo-")
    cmd_init(argparse.Namespace(dir=q))
    shutil.copy(os.path.join(AQUI, "warroom.demo.toml"), os.path.join(q, C.ARQUIVO))
    Q.commit(q, "demo: assentos simulados", C.ARQUIVO)
    cfg = C.carregar(q)
    ident = P.abrir(q, cfg, "Demo do protocolo", "Tarefa de demonstração, com assentos simulados.")
    fase = P.rodar(q, ident, cfg)
    print("\nFase final: %s. O quadro ficou em %s (veja com: git -C %s log --oneline)" % (fase, q, q))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wr", description="WarRoom: conselho de IAs com quadro em Git.")
    ap.add_argument("--quadro", help="pasta do quadro (ou WR_QUADRO; padrão: a pasta atual)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init", help="cria um quadro novo")
    s.add_argument("dir")
    s.set_defaults(f=cmd_init)
    s = sub.add_parser("assentos", help="confere assentos e trabalhadores")
    s.add_argument("--testar", action="store_true", help="chama cada um de verdade (gasta cota)")
    s.set_defaults(f=cmd_assentos)
    s = sub.add_parser("abrir", help="abre uma deliberação e roda até fechar ou escalar")
    s.add_argument("titulo")
    s.add_argument("texto", nargs="?")
    s.add_argument("--arquivo", help="anexa um arquivo à tarefa")
    s.add_argument("--sensivel", action="store_true", help="trabalhadores: só os locais")
    s.add_argument("--sem-rodar", action="store_true")
    s.add_argument("--rodadas", type=int, help="para depois de N rodadas")
    s.set_defaults(f=cmd_abrir)
    s = sub.add_parser("continuar", help="retoma uma deliberação")
    s.add_argument("id")
    s.add_argument("--rodadas", type=int)
    s.set_defaults(f=cmd_continuar)
    s = sub.add_parser("falar", help="a palavra do dono, antes da próxima rodada")
    s.add_argument("id")
    s.add_argument("texto")
    s.set_defaults(f=cmd_falar)
    s = sub.add_parser("estado", help="lista as deliberações, ou as atas de uma")
    s.add_argument("id", nargs="?")
    s.set_defaults(f=cmd_estado)
    s = sub.add_parser("mcp", help="servidor MCP do quadro (stdio)")
    s.add_argument("--assento", action="append", help="só deixa gravar por este assento (repetível)")
    s.set_defaults(f=cmd_mcp)
    s = sub.add_parser("demo", help="roda o protocolo com assentos simulados, sem gastar cota")
    s.set_defaults(f=cmd_demo)
    args = ap.parse_args(argv)
    try:
        return args.f(args) or 0
    except (C.ErroConfig, Q.ErroQuadro) as e:
        print("wr: %s" % e, file=sys.stderr)
        return 1
