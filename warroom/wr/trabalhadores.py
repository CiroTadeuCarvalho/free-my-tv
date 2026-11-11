"""Trabalhadores: modelos abertos para volume (resumir, triar), nunca assento.

Cada um é um endpoint no formato OpenAI (/chat/completions). A lista é uma
cadeia: se um cai, tenta o próximo. Material sensível só vai a quem é local.
"""
import json
import os
import urllib.error
import urllib.request


class SemTrabalhador(Exception):
    pass


def pedir(trabalhadores, sistema, texto, sensivel=False):
    """Devolve (resposta, nome de quem respondeu)."""
    falhas = []
    for t in trabalhadores:
        if sensivel and not t.local:
            continue
        chave = os.environ.get(t.chave_env, "") if t.chave_env else ""
        if t.chave_env and not chave:
            falhas.append("%s: variável %s vazia" % (t.nome, t.chave_env))
            continue
        corpo = json.dumps({"model": t.modelo, "messages": [
            {"role": "system", "content": sistema}, {"role": "user", "content": texto}]}).encode()
        req = urllib.request.Request(t.url.rstrip("/") + "/chat/completions", data=corpo,
                                     headers={"Content-Type": "application/json"})
        if chave:
            req.add_header("Authorization", "Bearer " + chave)
        try:
            with urllib.request.urlopen(req, timeout=t.limite) as r:
                resposta = json.load(r)["choices"][0]["message"]["content"]
            if resposta and resposta.strip():
                return resposta.strip(), t.nome
            falhas.append("%s: resposta vazia" % t.nome)
        except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError) as e:
            falhas.append("%s: %s" % (t.nome, e))
    raise SemTrabalhador("; ".join(falhas) or "nenhum trabalhador serve para esta tarefa")
