import http.server
import io
import json
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wr import config as C, protocolo as P, quadro as Q  # noqa: E402
from wr.assentos import AssentoCaiu, chamar  # noqa: E402
from wr.cli import main  # noqa: E402
from wr.mcp import servir  # noqa: E402
from wr.trabalhadores import SemTrabalhador, pedir  # noqa: E402

BOA = "## Raciocínio\n\nx\n\n## Posição\n\ny\n\n## Veredito\n\nPOSICAO: concordo\nOBJECOES_NOVAS: nenhuma\n"


def quadro(assentos, protocolo="", extra=""):
    q = tempfile.mkdtemp(prefix="wr-teste-")
    main(["init", q])
    partes = ['dono = "Dono"\n[protocolo]\n%s\n' % protocolo]
    for ident, roteiro, resto in assentos:
        partes.append('[[assento]]\nid = "%s"\ntipo = "simulado"\nroteiro = %s\n%s\n'
                      % (ident, json.dumps(roteiro), resto))
    with open(os.path.join(q, C.ARQUIVO), "w", encoding="utf-8") as f:
        f.write("\n".join(partes) + extra)
    Q.commit(q, "teste: assentos", C.ARQUIVO)
    return q, C.carregar(q)


def calado(_):
    pass


QUATRO = [("a", ["ok"], ""), ("b", ["ok"], ""), ("c", ["ok"], ""), ("t", ["ok"], "replica = true")]


class Formato(unittest.TestCase):
    def test_valida(self):
        a = P.analisar(BOA, False)
        self.assertEqual((a["valida"], a["posicao"], a["objecoes"]), (True, "concordo", []))

    def test_objecoes_em_lista(self):
        t = BOA.replace("concordo", "discordo").replace(" nenhuma", "\n- uma\n- duas\n\nfim")
        self.assertEqual(P.analisar(t, False)["objecoes"], ["uma", "duas"])

    def test_recusas(self):
        self.assertFalse(P.analisar("oi", False)["valida"])
        self.assertFalse(P.analisar(BOA, True)["valida"])          # réplica obrigatória
        self.assertFalse(P.analisar(BOA.replace("POSICAO", "POS"), False)["valida"])
        self.assertFalse(P.analisar(BOA.replace(" nenhuma", ""), False)["valida"])


class Protocolo(unittest.TestCase):
    def test_consenso_em_duas_rodadas_limpas(self):
        q, cfg = quadro(QUATRO)
        i = P.abrir(q, cfg, "t", "t")
        self.assertEqual(P.rodar(q, i, cfg, calado), "fechada")
        e = P.estado(q, i, cfg)
        self.assertEqual((e["ultima"], e["fase"]), (2, "fechada"))
        self.assertIn("DECISÃO", Q.git(q, "log", "--oneline"))
        self.assertEqual(Q.git(q, "status", "--porcelain"), "")   # tudo commitado

    def test_objecao_nova_zera_a_contagem(self):
        s = [("a", ["ok", "objecao: furo", "ok"], ""), ("b", ["ok"], ""), ("c", ["ok"], ""),
             ("t", ["ok"], "replica = true")]
        q, cfg = quadro(s)
        i = P.abrir(q, cfg, "t", "t")
        P.rodar(q, i, cfg, calado)
        self.assertEqual(P.estado(q, i, cfg)["ultima"], 4)

    def test_objecao_repetida_nao_e_nova(self):
        s = [("a", ["objecao: Mesmo furo!", "ok"], ""), ("b", ["ok"], ""), ("c", ["ok"], ""),
             ("t", ["ok", "objecao: mesmo furo", "ok"], "replica = true")]
        q, cfg = quadro(s)
        i = P.abrir(q, cfg, "t", "t")
        P.rodar(q, i, cfg, calado)
        self.assertEqual(P.estado(q, i, cfg)["ultima"], 3)
        self.assertEqual(Q.ler(q, i, "r02-t.md")[0]["objecoes_repetidas"], "1")

    def test_disjuntor_escala_e_o_dono_destrava(self):
        s = QUATRO[:3] + [("t", ["objecao: a", "objecao: b", "objecao: c", "ok"], "replica = true")]
        q, cfg = quadro(s, "disjuntor = 3")
        i = P.abrir(q, cfg, "t", "t")
        self.assertEqual(P.rodar(q, i, cfg, calado), "escalada")
        self.assertEqual(P.estado(q, i, cfg)["ultima"], 3)
        self.assertEqual(P.rodar(q, i, cfg, calado), "escalada")   # não anda sem o dono
        self.assertEqual(P.estado(q, i, cfg)["ultima"], 3)
        self.assertEqual(P.falar(q, i, cfg, "decidi: sigam com b"), 4)
        self.assertEqual(P.rodar(q, i, cfg, calado), "fechada")
        self.assertEqual(P.estado(q, i, cfg)["ultima"], 5)

    def test_assento_caido_segue_com_quorum(self):
        s = [("a", ["cota"], "")] + QUATRO[1:]
        q, cfg = quadro(s)
        i = P.abrir(q, cfg, "t", "t")
        self.assertEqual(P.rodar(q, i, cfg, calado), "fechada")
        self.assertEqual(Q.ler(q, i, "r01-a.md")[0]["cota"], "sim")

    def test_abaixo_do_quorum_escala(self):
        s = [("a", ["cota"], ""), ("b", ["cota"], "")] + QUATRO[2:]
        q, cfg = quadro(s)
        i = P.abrir(q, cfg, "t", "t")
        self.assertEqual(P.rodar(q, i, cfg, calado), "escalada")

    def test_pausa_para_na_primeira_queda(self):
        s = [("a", ["cota", "ok"], "")] + QUATRO[1:]
        q, cfg = quadro(s, 'assento_caido = "pausa"')
        i = P.abrir(q, cfg, "t", "t")
        self.assertEqual(P.rodar(q, i, cfg, calado), "escalada")
        self.assertIsNone(Q.ler(q, i, "r01-b.md"))                # os outros nem foram chamados
        P.falar(q, i, cfg, "pode seguir")
        self.assertEqual(P.rodar(q, i, cfg, calado), "fechada")

    def test_replica_substituta_quando_o_assento_dela_cai(self):
        s = QUATRO[:3] + [("t", ["cota"], "replica = true")]
        q, cfg = quadro(s)
        i = P.abrir(q, cfg, "t", "t")
        self.assertEqual(P.rodar(q, i, cfg, calado), "fechada")
        sub = Q.ler(q, i, "r01-_replica.md")
        self.assertEqual((sub[0]["assento"], sub[0]["replica"]), ("a", "sim"))
        self.assertIn("## Réplica", sub[1])

    def test_fala_fora_do_formato_nao_conta(self):
        s = [("a", ["lixo"], "")] + QUATRO[1:]
        q, cfg = quadro(s)
        i = P.abrir(q, cfg, "t", "t")
        P.rodar(q, i, cfg, calado, max_rodadas=1)
        self.assertEqual(Q.ler(q, i, "r01-a.md")[0]["estado"], "invalida")

    def test_retoma_do_meio_da_rodada(self):
        q, cfg = quadro(QUATRO)
        i = P.abrir(q, cfg, "t", "t")
        P.contribuir(q, i, cfg, "b", BOA)                         # fala entregue de fora
        P.rodar(q, i, cfg, calado, max_rodadas=1)
        self.assertEqual(Q.ler(q, i, "r01-b.md")[0]["via"], "externo")
        with self.assertRaises(Q.ErroQuadro):
            P.contribuir(q, i, cfg, "t", BOA)                     # réplica sem a seção Réplica

    def test_execucao_grava_o_resultado(self):
        q, cfg = quadro(QUATRO, extra='\n[execucao]\ncomando = ["%s", "-c", "import sys; print(open(sys.argv[1]).read()[:3])", "{decisao}"]\n'
                        % sys.executable.replace("\\", "/"))
        i = P.abrir(q, cfg, "t", "t")
        P.rodar(q, i, cfg, calado)
        with open(os.path.join(Q.pasta(q, i), "EXECUCAO.md"), encoding="utf-8") as f:
            self.assertIn("código 0", f.read())


class Assentos(unittest.TestCase):
    def assento(self, codigo, entrada="stdin", **mais):
        cmd = [sys.executable, "-c", codigo]
        return C.Assento(id="x", nome="x", comando=cmd + (["{arquivo}"] if entrada == "arquivo" else []),
                         entrada=entrada, **mais)

    def test_tres_entradas(self):
        self.assertEqual(chamar(self.assento("import sys; print(sys.stdin.read().upper())"), "oi"), "OI")
        self.assertEqual(chamar(self.assento("import sys; print(sys.argv[-1]*2)", "arg"), "oi"), "oioi")
        self.assertEqual(chamar(self.assento("import sys; print(open(sys.argv[-1]).read())", "arquivo"), "oi"), "oi")

    def test_quedas(self):
        with self.assertRaises(AssentoCaiu) as e:
            chamar(self.assento("import sys; sys.stderr.write('Usage limit reached'); sys.exit(1)"), "oi")
        self.assertTrue(e.exception.cota)
        with self.assertRaises(AssentoCaiu):
            chamar(self.assento("pass"), "oi")                     # saída vazia
        with self.assertRaises(AssentoCaiu):
            chamar(self.assento("import time; time.sleep(5)", limite=1), "oi")
        with self.assertRaises(AssentoCaiu):
            chamar(C.Assento(id="x", nome="x", comando=["comando-que-nao-existe-wr"]), "oi")

    @unittest.skipUnless(os.name == "posix", "pseudo-terminal só no Linux/macOS")
    def test_com_terminal(self):
        a = self.assento("import sys; print('tty' if sys.stdout.isatty() else 'pipe', sys.argv[-1])", "arg", tty=True)
        self.assertEqual(chamar(a, "oi"), "tty oi")


class Servidor(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        pedido = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Servidor.vistos.append((self.headers.get("Authorization"), pedido["model"]))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"choices": [{"message": {"content": "RESUMO"}}]}).encode())

    def log_message(self, *a):
        pass


class Trabalhadores(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), Servidor)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = "http://127.0.0.1:%d/v1" % cls.srv.server_port

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        Servidor.vistos = []

    def test_fallback_e_chave(self):
        os.environ["WR_TESTE_CHAVE"] = "segredo"
        cadeia = [C.Trabalhador("morto", "http://127.0.0.1:9/v1", "m", limite=2),
                  C.Trabalhador("semchave", self.url, "m", chave_env="WR_TESTE_VAZIA"),
                  C.Trabalhador("vivo", self.url, "m2", chave_env="WR_TESTE_CHAVE")]
        self.assertEqual(pedir(cadeia, "s", "t"), ("RESUMO", "vivo"))
        self.assertEqual(Servidor.vistos, [("Bearer segredo", "m2")])

    def test_sensivel_so_local(self):
        nuvem = C.Trabalhador("nuvem", self.url, "m")
        with self.assertRaises(SemTrabalhador):
            pedir([nuvem], "s", "t", sensivel=True)
        self.assertEqual(Servidor.vistos, [])
        self.assertEqual(pedir([nuvem, C.Trabalhador("casa", self.url, "m", local=True)], "s", "t", True)[1], "casa")

    def test_quadro_grande_e_resumido_no_proprio_quadro(self):
        s = QUATRO[:3] + [("t", ["objecao: a", "objecao: b", "ok"], "replica = true")]
        q, cfg = quadro(s, "limite_quadro = 900",
                        '\n[[trabalhador]]\nnome = "casa"\nurl = "%s"\nmodelo = "m"\nlocal = true\n' % self.url)
        i = P.abrir(q, cfg, "t", "t", sensivel=True)
        self.assertEqual(P.rodar(q, i, cfg, calado), "fechada")
        resumos = [f for f in P.estado(q, i, cfg)["falas"] if f[1] == "_resumo"]
        self.assertTrue(resumos)
        self.assertEqual(resumos[0][2]["por"], "casa")


class Mcp(unittest.TestCase):
    def test_ler_e_contribuir(self):
        q, cfg = quadro(QUATRO)
        i = P.abrir(q, cfg, "tema", "corpo da tarefa")
        pedidos = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                   {"jsonrpc": "2.0", "method": "notifications/initialized"},
                   {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                   {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "wr_ler", "arguments": {"id": i}}},
                   {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                    "params": {"name": "wr_contribuir", "arguments": {"id": i, "assento": "a", "texto": BOA}}},
                   {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                    "params": {"name": "wr_contribuir", "arguments": {"id": i, "assento": "b", "texto": BOA}}}]
        saida = io.StringIO()
        servir(q, cfg, ("a",), io.StringIO("\n".join(json.dumps(p) for p in pedidos) + "\n"), saida)
        r = [json.loads(x) for x in saida.getvalue().splitlines()]
        self.assertEqual([x["id"] for x in r], [1, 2, 3, 4, 5])
        self.assertEqual(len(r[1]["result"]["tools"]), 4)
        self.assertIn("corpo da tarefa", r[2]["result"]["content"][0]["text"])
        self.assertFalse(r[3]["result"]["isError"])
        self.assertTrue(r[4]["result"]["isError"])                # assento b não é permitido aqui
        self.assertEqual(Q.ler(q, i, "r01-a.md")[0]["estado"], "valida")


class Guardas(unittest.TestCase):
    def test_quadro_dentro_de_outro_repo_e_recusado(self):
        q, _ = quadro(QUATRO)
        dentro = os.path.join(q, "sub")
        os.makedirs(dentro)
        with self.assertRaises(Q.ErroQuadro):
            Q.exigir_repo(dentro)

    def test_config_ruim(self):
        for s in (QUATRO[:3], QUATRO + [("u", ["ok"], "replica = true")], [("dono", ["ok"], "replica = true")]):
            with self.assertRaises(C.ErroConfig):
                quadro(s, "quorum = 1")
        with self.assertRaises(C.ErroConfig):
            quadro(QUATRO, "quorun = 3")

    def test_exemplo_carrega(self):
        q = tempfile.mkdtemp(prefix="wr-teste-")
        main(["init", q])
        cfg = C.carregar(q)
        self.assertEqual([a.id for a in cfg.assentos if a.replica], ["theofilo"])


if __name__ == "__main__":
    unittest.main()
