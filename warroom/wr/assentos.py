"""Chama o CLI de cada assento, na assinatura dele, e devolve o texto."""
import os
import re
import shutil
import subprocess
import tempfile

# Mensagens que os CLIs dão quando a cota do plano acaba.
COTA = re.compile(r"usage limit|rate limit|quota|limit reached|too many requests|429|limite de uso", re.I)


class AssentoCaiu(Exception):
    def __init__(self, motivo, cota=False):
        super().__init__(motivo)
        self.cota = cota


def disponivel(assento):
    if assento.tipo != "cli":
        return True
    return shutil.which(assento.comando[0]) is not None


def _com_tty(cmd, entrada, limite):
    """Alguns CLIs (agy -p) não escrevem nada sem terminal: dá um a eles."""
    import pty
    import select
    import time
    pid, fd = pty.fork()
    if pid == 0:
        try:
            os.execvp(cmd[0], cmd)
        finally:
            os._exit(127)
    if entrada:
        os.write(fd, entrada.encode() + b"\n\x04")
    partes, fim = [], time.time() + limite
    try:
        while True:
            if time.time() > fim:
                os.kill(pid, 9)
                os.waitpid(pid, 0)
                raise subprocess.TimeoutExpired(cmd, limite)
            if select.select([fd], [], [], 1)[0]:
                try:
                    dado = os.read(fd, 65536)
                except OSError:
                    break
                if not dado:
                    break
                partes.append(dado)
            elif os.waitpid(pid, os.WNOHANG)[0]:
                pid = 0
                break
    finally:
        os.close(fd)
    codigo = os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]) if pid else 0
    texto = b"".join(partes).decode("utf-8", "replace").replace("\r\n", "\n")
    return codigo, re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", texto), ""


def chamar(assento, prompt, rodada=1):
    if assento.tipo == "simulado":
        return _simulado(assento, rodada, "## Réplica" in prompt.rsplit("# Sua vez", 1)[-1])
    cmd, entrada, tmp = list(assento.comando), None, None
    if assento.entrada == "stdin":
        entrada = prompt
    elif assento.entrada == "arg":
        cmd.append(prompt)
    else:
        f = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
        f.write(prompt)
        f.close()
        tmp = f.name
        if not any("{arquivo}" in c for c in cmd):
            raise AssentoCaiu('entrada = "arquivo" pede {arquivo} no comando')
        cmd = [c.replace("{arquivo}", tmp) for c in cmd]
    try:
        if assento.tty and os.name == "posix":
            codigo, saida, erro = _com_tty(cmd, entrada, assento.limite)
        else:
            r = subprocess.run(cmd, input=entrada, capture_output=True, text=True,
                               timeout=assento.limite, encoding="utf-8", errors="replace")
            codigo, saida, erro = r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        raise AssentoCaiu("comando não encontrado: %s" % cmd[0])
    except subprocess.TimeoutExpired:
        raise AssentoCaiu("sem resposta em %d s" % assento.limite)
    finally:
        if tmp:
            os.unlink(tmp)
    saida = saida.strip()
    if codigo or not saida:
        tudo = (erro + "\n" + saida).strip()
        resumo = tudo[-400:] if tudo else "saída vazia"
        raise AssentoCaiu("código %d: %s" % (codigo, resumo), cota=bool(COTA.search(tudo)))
    return saida


def _simulado(assento, rodada, replica=False):
    """Assento de mentira para o demo e os testes. Um passo do roteiro por rodada:
    "ok", "discordo", "objecao: texto", "cota", "lixo"."""
    passo = assento.roteiro[min(rodada, len(assento.roteiro)) - 1] if assento.roteiro else "ok"
    if passo == "cota":
        raise AssentoCaiu("usage limit reached", cota=True)
    if passo == "lixo":
        return "resposta fora do formato"
    objecoes = [passo.split(":", 1)[1].strip()] if passo.startswith("objecao:") else []
    posicao = "discordo" if objecoes or passo == "discordo" else "concordo"
    replica = "## Réplica\n\nO ponto mais fraco do quadro nesta rodada (simulado).\n\n" if replica or assento.replica else ""
    lista = "\n".join("- " + o for o in objecoes) if objecoes else "nenhuma"
    return ("## Raciocínio\n\nRaciocínio simulado de %s na rodada %d.\n\n%s## Posição\n\nPosição simulada.\n\n"
            "## Veredito\n\nPOSICAO: %s\nOBJECOES_NOVAS:%s%s\n"
            % (assento.nome, rodada, replica, posicao, "\n" if objecoes else " ", lista))
