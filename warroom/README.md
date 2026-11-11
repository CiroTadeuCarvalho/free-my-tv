# WarRoom

Um conselho de IAs que delibera por escrito num quadro compartilhado em Git, com réplica combativa obrigatória,
regra de consenso e disjuntor que escala para o dono. Python 3.11+ puro, sem biblioteca, sem tmux, sem WSL: roda
igual em Windows, Linux e macOS.

Este é o **protocolo**, a camada de cima. Orquestradores de agentes de código (Claw Orchestrator, Omnigent, CLI
Agent Orchestrator) ficam embaixo, como braço de execução: recebem a decisão pronta e executam.

Se existir um `WARROOM.md` fundador, ele manda. O que está aqui implementa o que estava descrito no insumo de
10/11/2026; onde o insumo deixava a decisão em aberto, a escolha feita está na seção [Decisões](#decisões-que-são-do-dono).

## Em um minuto

```bash
python3 wr.py demo                          # o protocolo rodando com assentos simulados, sem gastar cota
python3 wr.py init ~/warroom-quadro         # cria o quadro (um repositório Git só dele)
python3 wr.py --quadro ~/warroom-quadro assentos            # confere se cada CLI está instalado
python3 wr.py --quadro ~/warroom-quadro assentos --testar   # chama cada um de verdade (gasta cota)
python3 wr.py --quadro ~/warroom-quadro abrir "Título" "O que o conselho precisa decidir"
```

`WR_QUADRO=~/warroom-quadro` no ambiente dispensa o `--quadro`.

| Comando | O que faz |
|---|---|
| `abrir "título" ["texto"] [--arquivo F] [--sensivel] [--rodadas N]` | Abre a deliberação e roda até fechar ou escalar. |
| `continuar <id>` | Retoma de onde parou (queda de luz, cota, escalada respondida). |
| `falar <id> "texto"` | A palavra do dono, lida por todos antes da próxima rodada. |
| `estado [id]` | Lista as deliberações, ou mostra as atas de uma. |
| `assentos [--testar]` | Confere os CLIs e os trabalhadores. |
| `mcp [--assento ID]` | Servidor MCP do quadro, para um braço de fora. |

Código de saída: `0` fechou (ou parou no `--rodadas`), `2` escalou para o dono, `1` erro.

## Como uma deliberação anda

1. **Rodada.** Cada assento lê o quadro inteiro (inclusive o que os outros acabaram de dizer na mesma rodada) e
   grava a sua fala. A ordem gira a cada rodada, para ninguém ter sempre a primeira palavra.
2. **Réplica.** O assento marcado com `replica = true` (Theófilo) fala por último e é obrigado a atacar o ponto mais
   fraco do que leu. Fala dele sem a seção `## Réplica` é recusada. Se ele cair, outro assento faz a réplica daquela
   rodada: sem réplica, a rodada não conta como limpa.
3. **Objeção nova.** Toda fala termina com um veredito que a máquina lê:

   ```
   ## Veredito
   POSICAO: discordo
   OBJECOES_NOVAS:
   - o plano não tem critério de parada
   ```

   Objeção que já está no quadro não conta como nova, mesmo se o assento disser que é.
4. **Consenso.** Duas rodadas seguidas sem objeção nova, com quórum e com réplica feita. O relator escreve a
   `DECISAO.md`; se ele cair, ela sai com as falas finais de cada assento.
5. **Disjuntor.** Vinte rodadas sem consenso: para, grava a escalada com as objeções em aberto e espera o dono.
   Depois de `wr falar`, a contagem recomeça.

Fala fora do formato é pedida de novo uma vez; se voltar errada, fica no quadro marcada como inválida e não conta.

## O quadro

Um repositório Git só para isso. Cada fala é um arquivo, cada arquivo é um commit. O que não está no repositório
não existe: o estado de uma deliberação é lido só destes arquivos.

```
warroom.toml
deliberacoes/20261110-2210-backup-do-quadro/
  r00-tarefa.md        a tarefa
  r01-fabricio.md      fala do assento na rodada 1 (válida, inválida ou caída)
  r01-_ata.md          ata: quem falou, objeções novas, se a rodada foi limpa
  r01-_replica.md      réplica substituta, quando o assento dela caiu
  r02-dono.md          a palavra do dono antes da rodada 2
  r03-_resumo.md       resumo das rodadas antigas, feito por um trabalhador
  r20-_escalada.md     escalada para o dono
  DECISAO.md           a decisão
  EXECUCAO.md          o que o braço de execução devolveu
```

## Assentos

Cada assento é o CLI do fornecedor, logado na assinatura dele, sem chave de API. O `warroom.toml` diz como chamar:

| Assento | Comando padrão | Situação |
|---|---|---|
| Fabrício | `claude -p` (texto pela entrada padrão) | Testado de verdade. |
| Theófilo | `codex exec -` (texto pela entrada padrão) | Não testado: sem o CLI na máquina onde isto foi escrito. |
| Raj | `agy -p "<texto>"`, num pseudo-terminal | Não testado. Há relatos de `agy -p` não escrever nada, ou travar, sem terminal; por isso `tty = true`, que só existe em Linux e macOS. Para o Gemini 4 Argon, escolha-o com `/model` numa sessão normal do `agy` antes. |
| Zé | `grok --no-auto-update -p "<texto>"` | Não testado. |

Se um comando não servir, troque `comando` e `entrada` (`stdin`, `arg` ou `arquivo`) no `warroom.toml`: nada disso
está preso no código. `wr assentos --testar` diz na hora qual responde.

**Cota.** Quando um CLI sai com erro, não responde no tempo ou devolve vazio, o assento cai naquela rodada e a queda
fica gravada no quadro (com `cota: sim` quando a mensagem é de limite de uso).

**Braço 24/7 (Grok Bot e parecidos).** Não dá para chamar por comando, então entra como assento `tipo = "externo"` e
entrega a fala pelo servidor MCP: `wr --quadro <pasta> mcp --assento zebot`. As ferramentas são `wr_listar`,
`wr_ler`, `wr_formato` e `wr_contribuir`. Ele precisa entregar entre uma rodada e outra; se a rodada rodar sem a
fala dele, ele conta como caído. O servidor é local (stdio): um agente que mora na nuvem só o alcança se rodar
esse comando numa máquina com o quadro. Esse caminho foi testado com um cliente de mentira, nunca com o Grok Bot.

## Trabalhadores

Modelos abertos servem para volume, não para assento. Hoje fazem uma coisa: quando o quadro passa de
`limite_quadro` caracteres, resumem as rodadas antigas, e o resumo é gravado no próprio quadro. A lista é uma
cadeia de fallback: caiu um, tenta o próximo. Qualquer endpoint no formato OpenAI serve (Ollama, Z.ai, OpenRouter,
NVIDIA NIM). A chave fica numa variável de ambiente; no arquivo vai só o nome dela.

`--sensivel` ao abrir a tarefa: só os trabalhadores com `local = true` recebem o texto. **Os quatro assentos
continuam recebendo**, porque são eles que deliberam; material que não pode ir para Anthropic, OpenAI, Google e xAI
não entra no WarRoom.

Sem trabalhador disponível, as falas mais antigas são cortadas do texto enviado (continuam inteiras no repositório).

## Braço de execução

Com `[execucao] comando = [...]` no `warroom.toml`, depois do consenso o `wr` roda esse comando trocando `{decisao}`
pelo caminho da `DECISAO.md` e grava a saída em `EXECUCAO.md`. É aqui que um orquestrador de agentes de código entra.
Desligado por padrão; a sintaxe do orquestrador escolhido precisa ser conferida na documentação dele.

## Decisões que são do dono

O insumo deixou estes pontos em aberto. Cada um tem um padrão que funciona e uma linha no `warroom.toml` para mudar.

| Ponto | Padrão aqui | Como mudar |
|---|---|---|
| Assento cai por cota no meio da rodada | O conselho segue se houver quórum (3); abaixo disso, escala. | `assento_caido = "pausa"` para e escala na primeira queda. |
| Alguém ainda discorda, mas sem objeção nova | Fecha, e a `DECISAO.md` lista quem discorda. É a regra ao pé da letra. | Sem opção hoje: exigir unanimidade seria outra regra. |
| Raj: Spark ou `agy` | `agy` no conselho. O Spark pode entrar como assento externo pelo MCP. | `[[assento]]` |
| Zé: Grok Build ou Grok Bot | Grok Build no conselho; Grok Bot como assento externo, comentado no exemplo. | `[[assento]]` |
| OrIa e MemOria | Fora: não havia descrição delas no insumo. | |

## Limites conhecidos

- "Objeção nova" é o que o assento declara, menos o que já está escrito igual no quadro. A mesma objeção com outras
  palavras passa como nova. O efeito é atrasar o consenso, nunca adiantá-lo.
- As rodadas são em fila, um assento por vez. É o que faz todos lerem o mesmo quadro; custa tempo.
- O `wr` pede aos assentos que não usem ferramentas nem mexam em arquivos, mas quem obedece é o CLI. Rode-o numa
  pasta onde isso não faça estrago, ou ligue o modo somente leitura de cada CLI no `comando`.
- A seção `## Raciocínio` pede os argumentos e as evidências da posição, não o pensamento passo a passo do
  modelo. Pedir o passo a passo fez o CLI do Claude recusar as quatro falas num teste real.
- Dois `wr` na mesma deliberação ao mesmo tempo não são protegidos por trava.

## Testes

```bash
python3 -m unittest discover -s tests
```

Cobrem o formato, o consenso, o disjuntor, a queda de assento, a réplica substituta, a retomada, os três modos de
entrada dos CLIs, o pseudo-terminal, o fallback dos trabalhadores, o resumo do quadro e o servidor MCP.
