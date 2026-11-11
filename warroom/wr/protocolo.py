"""O protocolo, acima de qualquer orquestrador.

- Cada rodada, todo assento lê o quadro inteiro e grava a sua fala nele.
- O assento da réplica fala por último e é obrigado a atacar o que leu.
- Consenso: N rodadas seguidas sem objeção nova (padrão 2).
- Disjuntor: sem consenso em M rodadas (padrão 20), para e escala para o dono.
"""
import os
import re
import subprocess

from . import quadro as Q
from .assentos import AssentoCaiu, chamar
from .trabalhadores import SemTrabalhador, pedir

FORMATO = """Responda em português, só com estas seções, nesta ordem:

## Raciocínio
(os argumentos e as evidências que sustentam a sua posição, escritos para os
outros assentos poderem conferir e atacar)
%s
## Posição
(o que você defende agora, de forma que dê para executar)

## Veredito
POSICAO: concordo ou discordo (com o rumo que o quadro está tomando)
OBJECOES_NOVAS: nenhuma

Se tiver objeção que AINDA NÃO está no quadro, troque a última linha por:
OBJECOES_NOVAS:
- uma objeção por linha, curta e verificável

Repetir objeção que já está no quadro não conta como nova. Não invente objeção
para parecer rigoroso, e não esconda uma para acabar logo."""

REPLICA = """
## Réplica
(obrigatória: ataque o ponto mais fraco do que os outros assentos disseram nesta
rodada. Diga o que quebraria a posição deles. Concordar por educação é proibido;
se depois do ataque a posição ficar de pé, diga isso no Veredito.)
"""


def norm(texto):
    return re.sub(r"[^a-z0-9à-ú]+", " ", texto.lower()).strip()


def analisar(texto, replica):
    """Lê a fala de um assento. Fora do formato não entra como fala válida."""
    def secao(nome):
        return re.search(r"^##\s*%s\b" % nome, texto, re.M | re.I)
    if not secao("Racioc[ií]nio"):
        return {"valida": False, "motivo": "falta a seção Raciocínio"}
    if replica and not secao("R[ée]plica"):
        return {"valida": False, "motivo": "falta a seção Réplica, que é obrigatória neste assento"}
    pos = re.findall(r"^POSICAO:\s*(concordo|discordo)\b", texto, re.M | re.I)
    if not pos:
        return {"valida": False, "motivo": "falta a linha POSICAO: concordo|discordo"}
    m = list(re.finditer(r"^OBJECOES_NOVAS:[ \t]*(.*)$", texto, re.M | re.I))
    if not m:
        return {"valida": False, "motivo": "falta a linha OBJECOES_NOVAS:"}
    m = m[-1]
    objecoes = []
    if norm(m.group(1)) not in ("nenhuma", "nenhum", "nao", "não"):
        if m.group(1).strip():
            objecoes.append(m.group(1).strip())
        for linha in texto[m.end():].splitlines():
            linha = linha.strip()
            if re.match(r"^[-*•]\s+\S", linha):
                objecoes.append(re.sub(r"^[-*•]\s+", "", linha))
            elif linha:
                break
        if not objecoes:
            return {"valida": False, "motivo": "OBJECOES_NOVAS sem lista e sem 'nenhuma'"}
    return {"valida": True, "posicao": pos[-1].lower(), "objecoes": objecoes}


def conhecidas(falas, ate_rodada=None):
    """Objeções já levantadas no quadro (normalizadas)."""
    vistas = set()
    for rodada, autor, cab, corpo, _ in falas:
        if cab.get("estado") == "valida" and (ate_rodada is None or rodada <= ate_rodada):
            for o in analisar(corpo, False).get("objecoes", []):
                vistas.add(norm(o))
    return vistas


def estado(quadro, ident, cfg):
    falas = Q.falas(quadro, ident)
    atas = {r: cab for r, autor, cab, _, _ in falas if autor == "_ata"}
    ultima = max(atas) if atas else 0
    dono = max([r for r, autor, *_ in falas if autor == "dono"] or [0])
    escalada = max([r for r, autor, *_ in falas if autor == "_escalada"] or [0])
    base = max(dono - 1, 0)          # a fala do dono zera as contagens
    limpas, r = 0, ultima
    while r > base and atas.get(r, {}).get("limpa") == "sim":
        limpas, r = limpas + 1, r - 1
    tarefa = Q.ler(quadro, ident, "r00-tarefa.md") or ({}, "")
    if os.path.exists(os.path.join(Q.pasta(quadro, ident), "DECISAO.md")):
        fase = "fechada"
    elif escalada and dono <= escalada:
        fase = "escalada"
    else:
        fase = "aberta"
    return {"falas": falas, "ultima": ultima, "limpas": limpas, "fase": fase, "base": base,
            "sensivel": tarefa[0].get("sensivel") == "sim", "titulo": tarefa[0].get("titulo", ident),
            "tarefa": tarefa[1]}


def texto_fala(f):
    rodada, autor, cab, corpo, _ = f
    quem = cab.get("nome") or autor
    if autor == "dono":
        return "### Antes da rodada %d — %s (dono, a palavra dele decide)\n\n%s" % (rodada, quem, corpo.strip())
    if cab.get("estado") == "caido":
        return "### Rodada %d — %s: não falou (%s)" % (rodada, quem, cab.get("motivo", "caiu"))
    if cab.get("estado") == "invalida":
        return "### Rodada %d — %s: fala fora do formato, desconsiderada" % (rodada, quem)
    return "### Rodada %d — %s\n\n%s" % (rodada, quem, corpo.strip())


def texto_quadro(quadro, ident, cfg, est, log):
    """O quadro como texto para o prompt; resume as rodadas antigas se não couber."""
    falas = [f for f in est["falas"] if f[0] > 0 and f[1] not in ("_ata", "_escalada")]
    resumos = [f for f in falas if f[1] == "_resumo"]
    falas = [f for f in falas if f[1] != "_resumo"]

    def montar(resumo):
        corte = resumo[0] if resumo else 0
        partes = []
        if resumo:
            partes.append("### Resumo das rodadas 1 a %d (feito por %s; o original está no repositório)\n\n%s"
                          % (corte, resumo[2].get("por", "trabalhador"), resumo[3].strip()))
        partes += [texto_fala(f) for f in falas if f[0] > corte]
        return "\n\n".join(partes) or "(vazio: esta é a primeira rodada)"

    resumo = resumos[-1] if resumos else None
    texto = montar(resumo)
    if len(texto) <= cfg.limite_quadro:
        return texto
    corte = est["ultima"] - 1         # a última rodada completa sempre vai inteira
    if corte >= 1 and (not resumo or resumo[0] < corte):
        antigo = "\n\n".join(texto_fala(f) for f in falas if f[0] <= corte)
        try:
            feito, por = pedir(cfg.trabalhadores,
                               "Resuma em português este trecho de uma deliberação. Preserve, por assento: "
                               "a posição atual, cada objeção levantada e se foi respondida. Não opine.",
                               antigo[:200000], sensivel=est["sensivel"])
            nome = "r%02d-_resumo.md" % corte
            Q.gravar(quadro, ident, nome, {"rodada": corte, "por": por}, feito,
                     "%s: resumo das rodadas 1 a %d (%s)" % (ident, corte, por))
            log("  quadro resumido até a rodada %d por %s" % (corte, por))
            texto = montar((corte, "_resumo", {"por": por}, feito, nome))
            if len(texto) <= cfg.limite_quadro:
                return texto
        except SemTrabalhador as e:
            log("  sem trabalhador para resumir (%s); corto as rodadas antigas" % e)
    aviso = "(As falas mais antigas foram cortadas por tamanho; estão inteiras no repositório.)\n\n"
    return aviso + texto[-cfg.limite_quadro:]


def prompt(cfg, assento, est, rodada, texto, replica):
    papel = "assento da réplica combativa" if replica else "assento"
    return "\n\n".join([
        "Você é %s, %s do WarRoom, um conselho de IAs que delibera por escrito num quadro "
        "compartilhado. %s" % (assento.nome, papel, assento.papel),
        "Regras: o quadro abaixo é a única fonte de verdade. Leia tudo antes de responder. O conselho "
        "fecha quando passam %d rodadas seguidas sem objeção nova de nenhum assento; em %d rodadas sem "
        "isso, o caso sobe para %s. Não use ferramentas nem altere arquivos: só responda no formato."
        % (cfg.rodadas_sem_objecao, cfg.disjuntor, cfg.dono),
        "# Tarefa: %s\n\n%s" % (est["titulo"], est["tarefa"].strip()),
        "# Quadro até agora\n\n" + texto,
        "# Sua vez: rodada %d\n\n%s" % (rodada, FORMATO % (REPLICA if replica else "")),
    ])


def _falar(quadro, ident, cfg, assento, est, rodada, texto, replica, nome, ordem, log):
    """Chama um assento e grava a fala (válida, inválida ou caída). Devolve o cabeçalho."""
    cab = {"rodada": rodada, "assento": assento.id, "nome": assento.nome, "ordem": "%02d" % ordem}
    if replica:
        cab["replica"] = "sim"
    p = prompt(cfg, assento, est, rodada, texto, replica)
    corpo, a = "", None
    try:
        if assento.tipo == "externo":
            raise AssentoCaiu("assento externo não entregou a fala desta rodada")
        corpo = chamar(assento, p, rodada)
        a = analisar(corpo, replica)
        if not a["valida"]:
            log("  %s: fora do formato (%s); peço de novo" % (assento.nome, a["motivo"]))
            corpo = chamar(assento, p + "\n\nSua resposta anterior foi recusada: %s. Responda de novo, "
                           "exatamente no formato." % a["motivo"], rodada)
            a = analisar(corpo, replica)
    except AssentoCaiu as e:
        cab.update(estado="caido", motivo=str(e)[:300], cota="sim" if e.cota else "nao")
        Q.gravar(quadro, ident, nome, cab, "Não falou: %s" % e, "%s r%02d: %s caiu" % (ident, rodada, assento.id))
        log("  %s: CAIU (%s)" % (assento.nome, str(e)[:120]))
        return cab
    if not a["valida"]:
        cab.update(estado="invalida", motivo=a["motivo"])
        Q.gravar(quadro, ident, nome, cab, corpo, "%s r%02d: %s fora do formato" % (ident, rodada, assento.id))
        log("  %s: fala inválida (%s)" % (assento.nome, a["motivo"]))
        return cab
    return _registrar(quadro, ident, cab, corpo, a, nome, log)


def _registrar(quadro, ident, cab, corpo, a, nome, log):
    vistas = conhecidas(Q.falas(quadro, ident))
    novas = [o for o in a["objecoes"] if norm(o) not in vistas]
    cab.update(estado="valida", posicao=a["posicao"], objecoes_novas=len(novas),
               objecoes_repetidas=len(a["objecoes"]) - len(novas))
    Q.gravar(quadro, ident, nome, cab, corpo,
             "%s r%02d: %s (%s, %d objeção nova)" % (ident, cab["rodada"], cab["assento"], a["posicao"], len(novas)))
    log("  %s: %s, %d objeção nova" % (cab.get("nome", cab["assento"]), a["posicao"], len(novas)))
    return cab


def contribuir(quadro, ident, cfg, assento_id, texto):
    """Fala entregue de fora (MCP, braço 24/7): entra na próxima rodada a rodar."""
    assento = next((a for a in cfg.assentos if a.id == assento_id), None)
    if not assento:
        raise Q.ErroQuadro("assento desconhecido: %s" % assento_id)
    est = estado(quadro, ident, cfg)
    if est["fase"] == "fechada":
        raise Q.ErroQuadro("deliberação já fechada")
    rodada = est["ultima"] + 1
    nome = "r%02d-%s.md" % (rodada, assento.id)
    if Q.ler(quadro, ident, nome):
        raise Q.ErroQuadro("%s já falou na rodada %d" % (assento.nome, rodada))
    a = analisar(texto, assento.replica)
    if not a["valida"]:
        raise Q.ErroQuadro("fala recusada: %s" % a["motivo"])
    cab = {"rodada": rodada, "assento": assento.id, "nome": assento.nome, "ordem": "00", "via": "externo"}
    if assento.replica:
        cab["replica"] = "sim"
    _registrar(quadro, ident, cab, texto, a, nome, lambda s: None)
    return rodada


def abrir(quadro, cfg, titulo, texto, sensivel=False):
    ident = Q.novo_id(quadro, titulo)
    Q.gravar(quadro, ident, "r00-tarefa.md", {"titulo": titulo, "sensivel": "sim" if sensivel else "nao"},
             texto, "%s: tarefa aberta" % ident)
    return ident


def falar(quadro, ident, cfg, texto):
    est = estado(quadro, ident, cfg)
    if est["fase"] == "fechada":
        raise Q.ErroQuadro("deliberação já fechada; abra outra")
    rodada = est["ultima"] + 1
    nome, n = "r%02d-dono.md" % rodada, 2
    anterior = Q.ler(quadro, ident, nome)
    if anterior:                      # segunda fala antes da mesma rodada: junta
        texto = anterior[1].strip() + "\n\n" + texto
    Q.gravar(quadro, ident, nome, {"rodada": rodada, "assento": "dono", "nome": cfg.dono}, texto,
             "%s: %s falou antes da rodada %d" % (ident, cfg.dono, rodada))
    return rodada


def _escalar(quadro, ident, cfg, rodada, motivo, log):
    falas = Q.falas(quadro, ident)
    abertas = []
    for r, autor, cab, corpo, _ in falas:
        if cab.get("estado") == "valida":
            for o in analisar(corpo, False).get("objecoes", []):
                abertas.append("- (rodada %d, %s) %s" % (r, cab.get("nome", autor), o))
    posicoes = ["- %s: %s" % (cab.get("nome", autor), cab.get("posicao") or cab.get("estado"))
                for r, autor, cab, _, _ in falas if r == rodada and "assento" in cab and autor != "dono"]
    corpo = ("## Raciocínio\n\nO conselho parou na rodada %d: %s.\n\n## Posições na última rodada\n\n%s\n\n"
             "## Objeções levantadas até aqui\n\n%s\n\n## O que fazer\n\n%s decide ou orienta com "
             "`wr falar %s \"...\"` e retoma com `wr continuar %s`.\n"
             % (rodada, motivo, "\n".join(posicoes) or "(nenhuma)", "\n".join(abertas[-40:]) or "(nenhuma)",
                cfg.dono, ident, ident))
    Q.gravar(quadro, ident, "r%02d-_escalada.md" % rodada, {"rodada": rodada, "motivo": motivo}, corpo,
             "%s: escalado para %s (%s)" % (ident, cfg.dono, motivo))
    log("ESCALADO para %s: %s" % (cfg.dono, motivo))
    return "escalada"


def rodada_unica(quadro, ident, cfg, rodada, log):
    """Roda uma rodada. Devolve None para seguir, ou o motivo para escalar."""
    comuns = [a for a in cfg.assentos if not a.replica]
    giro = (rodada - 1) % len(comuns) if comuns else 0
    ordem = comuns[giro:] + comuns[:giro] + [a for a in cfg.assentos if a.replica]
    cabs, pausa = {}, None
    for i, assento in enumerate(ordem, 1):
        nome = "r%02d-%s.md" % (rodada, assento.id)
        ja = Q.ler(quadro, ident, nome)
        if ja:                        # retomada, ou fala entregue de fora
            cabs[assento.id] = ja[0]
            continue
        est = estado(quadro, ident, cfg)
        texto = texto_quadro(quadro, ident, cfg, est, log)
        cabs[assento.id] = _falar(quadro, ident, cfg, assento, est, rodada, texto, assento.replica, nome, i, log)
        if cabs[assento.id]["estado"] == "caido" and cfg.assento_caido == "pausa":
            pausa = "%s caiu (%s) e a regra é pausar" % (assento.nome, cabs[assento.id]["motivo"][:80])
            break
    for a in ordem:                   # quem nem foi chamado por causa da pausa
        cabs.setdefault(a.id, {"nome": a.nome, "estado": "não chamado"})
    validas = [a for a in ordem if cabs[a.id].get("estado") == "valida"]
    dono_replica = next(a for a in cfg.assentos if a.replica)
    teve_replica = cabs[dono_replica.id].get("estado") == "valida"
    sub = Q.ler(quadro, ident, "r%02d-_replica.md" % rodada)
    if not teve_replica and not sub and validas and not pausa:
        # A réplica é obrigatória: se o assento dela caiu, outro assume nesta rodada.
        est = estado(quadro, ident, cfg)
        texto = texto_quadro(quadro, ident, cfg, est, log)
        log("  réplica substituta: %s" % validas[0].nome)
        cab = _falar(quadro, ident, cfg, validas[0], est, rodada, texto, True,
                     "r%02d-_replica.md" % rodada, len(ordem) + 1, log)
        sub = (cab, "")
    if sub and sub[0].get("estado") == "valida":
        teve_replica = True
        cabs["_replica"] = sub[0]
    novas = sum(int(c.get("objecoes_novas", 0)) for c in cabs.values() if c.get("estado") == "valida")
    limpa = novas == 0 and teve_replica and len(validas) >= cfg.quorum
    caidos = [a.nome for a in ordem if cabs[a.id].get("estado") != "valida"]
    linhas = ["- %s: %s%s" % (c.get("nome", k), c.get("posicao") or c.get("estado"),
                              ", %s objeção nova" % c["objecoes_novas"] if c.get("objecoes_novas") else "")
              for k, c in cabs.items()]
    corpo = ("## Rodada %d\n\n%s\n\nObjeções novas: %d. Falas válidas: %d de %d (quórum %d). Réplica: %s.\n"
             % (rodada, "\n".join(linhas), novas, len(validas), len(ordem), cfg.quorum,
                "feita" if teve_replica else "NÃO FEITA"))
    Q.gravar(quadro, ident, "r%02d-_ata.md" % rodada,
             {"rodada": rodada, "limpa": "sim" if limpa else "nao", "objecoes_novas": novas,
              "validas": len(validas)}, corpo, "%s r%02d: ata (%s)" % (ident, rodada, "limpa" if limpa else "com pendência"))
    if pausa:
        return pausa
    if len(validas) < cfg.quorum:
        return "só %d fala válida, abaixo do quórum de %d (fora: %s)" % (len(validas), cfg.quorum, ", ".join(caidos))
    return None


def _decisao(quadro, ident, cfg, est, log):
    ultima = est["ultima"]
    finais = [f for f in est["falas"] if f[0] == ultima and f[2].get("estado") == "valida"]
    dissidentes = sorted({f[2].get("nome", f[1]) for f in finais if f[2].get("posicao") == "discordo"})
    relator = next((a for a in cfg.assentos if a.relator), None)
    sintese, por = "", "fechamento mecânico"
    if relator:
        texto = texto_quadro(quadro, ident, cfg, est, log)
        pedido = "\n\n".join([
            "Você é %s, relator do WarRoom. O conselho fechou a deliberação abaixo. Escreva a decisão final, "
            "fiel ao quadro, sem acrescentar posição sua." % relator.nome,
            "# Tarefa: %s\n\n%s" % (est["titulo"], est["tarefa"].strip()),
            "# Quadro\n\n" + texto,
            "Responda em português, só com:\n\n## Raciocínio\n(os argumentos que sustentam a decisão e as "
            "objeções que caíram, com o motivo)\n\n## Decisão\n(o que foi decidido, em passos executáveis)\n\n"
            "## Ressalvas\n(o que ficou em aberto e quem ainda discorda)"])
        try:
            sintese = chamar(relator, pedido, ultima)
            if re.search(r"^##\s*Decis[ãa]o", sintese, re.M | re.I):
                por = relator.nome
            else:
                sintese = ""
        except AssentoCaiu as e:
            log("  relator caiu (%s); fecho com as posições finais" % str(e)[:80])
    if not sintese:
        sintese = "## Raciocínio\n\nFechamento sem relator: seguem as falas finais de cada assento, como estão no quadro.\n\n" \
                  + "\n\n".join(texto_fala(f) for f in finais)
    cab = {"deliberacao": ident, "titulo": est["titulo"], "rodadas": ultima, "sintese": por,
           "dissidentes": ", ".join(dissidentes) or "nenhum"}
    p = Q.pasta(quadro, ident)
    with open(os.path.join(p, "DECISAO.md"), "w", encoding="utf-8") as f:
        f.write(Q.montar(cab, sintese))
    Q.commit(quadro, "%s: DECISÃO em %d rodadas" % (ident, ultima), os.path.join(Q.DIR, ident, "DECISAO.md"))
    log("CONSENSO em %d rodadas%s." % (ultima, " (discordam: %s)" % ", ".join(dissidentes) if dissidentes else ""))
    if cfg.execucao:
        _executar(quadro, ident, cfg, os.path.join(p, "DECISAO.md"), log)


def _executar(quadro, ident, cfg, decisao, log):
    """Braço de execução: entrega a decisão a um orquestrador e grava o que voltou."""
    cmd = [c.replace("{decisao}", decisao) for c in cfg.execucao]
    log("execução: %s" % " ".join(cmd))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=cfg.execucao_limite,
                           encoding="utf-8", errors="replace")
        codigo, saida = r.returncode, (r.stdout + ("\n" + r.stderr if r.stderr.strip() else ""))
    except (OSError, subprocess.TimeoutExpired) as e:
        codigo, saida = -1, str(e)
    corpo = "## Raciocínio\n\nA decisão foi entregue ao braço de execução (`%s`), que terminou com código %d.\n\n" \
            "## Saída\n\n```\n%s\n```\n" % (" ".join(cfg.execucao), codigo, saida.strip()[-20000:])
    with open(os.path.join(Q.pasta(quadro, ident), "EXECUCAO.md"), "w", encoding="utf-8") as f:
        f.write(Q.montar({"deliberacao": ident, "codigo": codigo}, corpo))
    Q.commit(quadro, "%s: execução (código %d)" % (ident, codigo), os.path.join(Q.DIR, ident, "EXECUCAO.md"))
    log("execução terminou com código %d" % codigo)


def rodar(quadro, ident, cfg, log=print, max_rodadas=None):
    """Roda rodadas até o consenso, a escalada ou max_rodadas. Devolve a fase."""
    feitas = 0
    while True:
        est = estado(quadro, ident, cfg)
        if est["fase"] == "fechada":
            return "fechada"
        if est["fase"] == "escalada":
            log("Parado: escalado para %s. Use `wr falar` e depois `wr continuar`." % cfg.dono)
            return "escalada"
        if est["limpas"] >= cfg.rodadas_sem_objecao:
            _decisao(quadro, ident, cfg, est, log)
            return "fechada"
        if est["ultima"] - est["base"] >= cfg.disjuntor:
            return _escalar(quadro, ident, cfg, est["ultima"],
                            "disjuntor: %d rodadas sem consenso" % cfg.disjuntor, log)
        if max_rodadas is not None and feitas >= max_rodadas:
            return "aberta"
        rodada = est["ultima"] + 1
        log("Rodada %d" % rodada)
        motivo = rodada_unica(quadro, ident, cfg, rodada, log)
        feitas += 1
        if motivo:
            return _escalar(quadro, ident, cfg, rodada, motivo, log)
