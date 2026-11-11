"""Servidor MCP (stdio) do quadro, para um braço de fora ler e entregar a sua fala.

Feito para o Grok Bot e outros agentes 24/7: eles não são chamados pelo `wr`,
então leem o quadro e gravam a fala do assento deles por aqui.
"""
import json
import sys

from . import protocolo as P
from . import quadro as Q

FERRAMENTAS = [
    {"name": "wr_listar", "description": "Lista as deliberações do WarRoom e a fase de cada uma.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "wr_ler", "description": "Devolve a tarefa e o quadro inteiro de uma deliberação.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
    {"name": "wr_formato", "description": "Devolve o formato obrigatório da fala de um assento.",
     "inputSchema": {"type": "object", "properties": {"assento": {"type": "string"}}, "required": ["assento"]}},
    {"name": "wr_contribuir",
     "description": "Grava a fala de um assento para a próxima rodada. Recusa o que estiver fora do formato.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "assento": {"type": "string"},
                                                      "texto": {"type": "string"}},
                     "required": ["id", "assento", "texto"]}},
]


def executar(quadro, cfg, nome, args, permitidos):
    if nome == "wr_listar":
        return "\n".join("%s  [%s]  %s" % (i, e["fase"], e["titulo"])
                         for i in Q.listar(quadro) for e in [P.estado(quadro, i, cfg)]) or "(nenhuma)"
    if nome == "wr_ler":
        est = P.estado(quadro, args["id"], cfg)
        corpo = "\n\n".join(P.texto_fala(f) for f in est["falas"] if f[0] > 0 and not f[1].startswith("_ata"))
        return "# Tarefa: %s\n\n%s\n\n# Quadro (fase: %s, próxima rodada: %d)\n\n%s" % (
            est["titulo"], est["tarefa"].strip(), est["fase"], est["ultima"] + 1, corpo or "(vazio)")
    if nome == "wr_formato":
        a = next((a for a in cfg.assentos if a.id == args["assento"]), None)
        if not a:
            raise Q.ErroQuadro("assento desconhecido")
        return P.FORMATO % (P.REPLICA if a.replica else "")
    if nome == "wr_contribuir":
        if permitidos and args["assento"] not in permitidos:
            raise Q.ErroQuadro("este servidor só grava pelos assentos: %s" % ", ".join(permitidos))
        rodada = P.contribuir(quadro, args["id"], cfg, args["assento"], args["texto"])
        return "Fala gravada para a rodada %d." % rodada
    raise Q.ErroQuadro("ferramenta desconhecida: %s" % nome)


def servir(quadro, cfg, permitidos=(), entrada=sys.stdin, saida=sys.stdout):
    for linha in entrada:
        linha = linha.strip()
        if not linha:
            continue
        try:
            msg = json.loads(linha)
        except ValueError:
            continue
        ident, metodo = msg.get("id"), msg.get("method", "")
        if ident is None:             # notificação: não tem resposta
            continue
        if metodo == "initialize":
            r = {"protocolVersion": msg.get("params", {}).get("protocolVersion", "2024-11-05"),
                 "capabilities": {"tools": {}}, "serverInfo": {"name": "warroom", "version": "1"}}
        elif metodo == "tools/list":
            r = {"tools": FERRAMENTAS}
        elif metodo == "tools/call":
            p = msg.get("params", {})
            try:
                texto, erro = executar(quadro, cfg, p.get("name"), p.get("arguments") or {}, permitidos), False
            except (Q.ErroQuadro, KeyError) as e:
                texto, erro = "Erro: %s" % e, True
            r = {"content": [{"type": "text", "text": texto}], "isError": erro}
        elif metodo == "ping":
            r = {}
        else:
            saida.write(json.dumps({"jsonrpc": "2.0", "id": ident,
                                    "error": {"code": -32601, "message": "método desconhecido"}}) + "\n")
            saida.flush()
            continue
        saida.write(json.dumps({"jsonrpc": "2.0", "id": ident, "result": r}, ensure_ascii=False) + "\n")
        saida.flush()
