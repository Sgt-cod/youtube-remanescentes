"""
roteiro_engine.py
------------------
Substitui as funções gerar_titulo() / gerar_roteiro() de uma chamada única por uma
cadeia de 5 estágios (tese -> estrutura -> escrita -> crítica adversarial -> título/descrição).

Motivo: uma única chamada "escreva um roteiro sobre X" tende a produzir resumo com
tom dramático por cima — a textura genérica que qualquer LLM produz quando não é
forçado a assumir uma posição específica. Separar em passes obrigatórios resolve isso
porque cada passe sozinho é uma tarefa mais fácil de fazer bem do que pedir tudo junto.

Não depende de nada específico do generate_video.py — recebe a função de chamada ao
Gemini (com retry já embutido) como parâmetro, pra reusar exatamente o _gemini_generate()
que já existe lá, sem duplicar lógica de retry/backoff.

Uso no generate_video.py:

    from roteiro_engine import gerar_pacote_roteiro

    pacote = gerar_pacote_roteiro(
        tema=tema,
        contexto_nicho=CONTEXTO_NICHO,
        idioma_conteudo=IDIOMA_CONTEUDO,
        instrucao_extra=INSTRUCAO_EXTRA_ROTEIRO,
        documento_estilo=config.get('documento_estilo', []),
        tipo_video=VIDEO_TYPE,
        gemini_generate_fn=_gemini_generate,
    )

    roteiro = pacote['roteiro_texto']       # string corrida, pronta pra TTS (compatível com o resto do código)
    titulo_video = pacote['titulo']         # string, já escolhido entre as variantes
    descricao_extra = pacote['descricao']   # dict {abertura_seo, corpo}
    blocos_roteiro = pacote['roteiro_blocos']  # lista de {bloco, texto} — pra Fase 2 (casar B-roll por bloco)

Se qualquer estágio falhar, cai para geração simples (comportamento antigo) em vez de
quebrar o pipeline — mesma filosofia de fallback que já existe no resto do código.
"""

import json
import re


def _extrair_json(texto):
    """Mesmo padrão já usado em gerar_titulo() no generate_video.py: acha o primeiro { ... }."""
    texto = texto.strip().replace('```json', '').replace('```', '').strip()
    inicio = texto.find('{')
    fim = texto.rfind('}') + 1
    if inicio == -1 or fim == 0:
        raise ValueError(f"Nenhum JSON encontrado na resposta: {texto[:200]}")
    return json.loads(texto[inicio:fim])


# ============================================================
# ESTÁGIO 1 — TESE
# ============================================================

def gerar_tese(tema, contexto_nicho, idioma_conteudo, gemini_generate_fn):
    prompt = f"""Você é um pesquisador cético, não um narrador. Sua única tarefa é produzir
uma AFIRMAÇÃO específica e refutável sobre o tema abaixo — nunca um resumo ou generalidade.

NICHO: {contexto_nicho}
TEMA: "{tema}"

Regras rígidas:
- A afirmação precisa poder estar ERRADA. Se ninguém discordaria dela, rejeite-a.
- Proibido gerar afirmação do tipo "{tema} é importante" ou "{tema} muda tudo".
- A afirmação deve conectar uma causa específica a um efeito específico, ou revelar uma
  crença comum sobre o tema que é enganosa/incompleta.
- Escreva em {idioma_conteudo}.

Retorne APENAS JSON, neste formato exato:
{{
  "tese": "uma frase, a afirmação específica",
  "por_que_e_contestavel": "o que alguém poderia usar para discordar",
  "reprovar": false
}}

Se genuinamente não for possível gerar uma tese específica para esse tema (é raro),
retorne "reprovar": true e explique o motivo em "tese"."""

    resposta = gemini_generate_fn(prompt)
    return _extrair_json(resposta.text)


# ============================================================
# ESTÁGIO 2 — ESTRUTURA ARGUMENTATIVA
# ============================================================

def gerar_estrutura(tese_dict, contexto_nicho, idioma_conteudo, gemini_generate_fn):
    prompt = f"""Você recebeu uma tese. Construa o esqueleto argumentativo do vídeo.
NÃO escreva prosa ainda — apenas a estrutura lógica, em {idioma_conteudo}.

NICHO: {contexto_nicho}
TESE: {tese_dict['tese']}
POR QUE É CONTESTÁVEL: {tese_dict['por_que_e_contestavel']}

Retorne APENAS JSON com estas 6 chaves (cada uma uma string curta, 1-2 frases):
{{
  "gancho": "a tensão ou pergunta que abre o vídeo — NÃO pode ser a tese repetida",
  "evidencia_a_favor": "o ponto principal que sustenta a tese",
  "objecao": "o argumento mais forte CONTRA a tese, ou a crença comum que ela contraria",
  "resposta_a_objecao": "como a tese sobrevive à objeção",
  "implicacao": "por que isso importa pra quem está assistindo, hoje, na prática",
  "fechamento": "a ideia final — não uma frase motivacional vaga, algo específico e acionável"
}}"""

    resposta = gemini_generate_fn(prompt)
    return _extrair_json(resposta.text)


# ============================================================
# ESTÁGIO 3 — ESCRITA (só aqui vira prosa)
# ============================================================

def gerar_prosa(estrutura, contexto_nicho, idioma_conteudo, instrucao_extra,
                 documento_estilo, palavras_alvo, gemini_generate_fn):
    bloco_estilo = ""
    if documento_estilo:
        exemplos = "\n\n".join(f"- {ex}" for ex in documento_estilo)
        bloco_estilo = f"""
DOCUMENTO DE ESTILO — escreva NESSA voz, não na sua voz padrão:
{exemplos}
"""

    linha_extra = f"\n- {instrucao_extra}" if instrucao_extra else ""

    prompt = f"""Escreva o roteiro de narração seguindo ESTRITAMENTE a estrutura abaixo, em {idioma_conteudo}.

NICHO: {contexto_nicho}
{bloco_estilo}
ESTRUTURA (siga esta ordem, um parágrafo curto por item):
1. gancho: {estrutura['gancho']}
2. evidencia_a_favor: {estrutura['evidencia_a_favor']}
3. objecao: {estrutura['objecao']}
4. resposta_a_objecao: {estrutura['resposta_a_objecao']}
5. implicacao: {estrutura['implicacao']}
6. fechamento: {estrutura['fechamento']}

REGRAS OBRIGATÓRIAS:
- Duração alvo: ~{palavras_alvo} palavras no total
- PROIBIDO usar: "mas o que isso realmente significa?", "e é aí que tudo muda",
  "prepare-se para descobrir", ou qualquer frase que serviria em vídeo sobre qualquer
  outro tema do mesmo nicho
- Frases curtas, sem formatação, sem asteriscos, sem emojis
- NÃO mencione apresentador, câmera ou elementos visuais{linha_extra}

Retorne APENAS JSON:
{{
  "blocos": [
    {{"bloco": "gancho", "texto": "..."}},
    {{"bloco": "evidencia_a_favor", "texto": "..."}},
    {{"bloco": "objecao", "texto": "..."}},
    {{"bloco": "resposta_a_objecao", "texto": "..."}},
    {{"bloco": "implicacao", "texto": "..."}},
    {{"bloco": "fechamento", "texto": "..."}}
  ]
}}"""

    resposta = gemini_generate_fn(prompt)
    dados = _extrair_json(resposta.text)
    blocos = dados['blocos']

    for b in blocos:
        b['texto'] = re.sub(r'\*+', '', b['texto'])
        b['texto'] = b['texto'].replace('#', '').replace('_', '').strip()

    return blocos


# ============================================================
# ESTÁGIO 4 — CRÍTICA ADVERSARIAL + REESCRITA CIRÚRGICA
# ============================================================

def criticar_e_reescrever(blocos, idioma_conteudo, gemini_generate_fn):
    """
    Chamada separada da escrita de propósito: crítica e geração são tarefas cognitivas
    diferentes, e o mesmo prompt que gera o clichê raramente enxerga o próprio clichê.
    Só reescreve os blocos marcados com problema — nunca o roteiro inteiro de novo.
    """
    roteiro_numerado = "\n".join(f"[{i}] ({b['bloco']}): {b['texto']}" for i, b in enumerate(blocos))

    prompt = f"""Você é um editor implacável. Sua ÚNICA função é achar defeito, nunca elogiar
nem reescrever ainda.

ROTEIRO (em {idioma_conteudo}, um bloco numerado por linha):
{roteiro_numerado}

Para cada bloco com problema, marque o tipo:
- clichê: frase que poderia estar em qualquer vídeo do nicho
- ritmo_quebrado: frase longa demais ou estrutura repetitiva
- redundancia: informação repetida sem necessidade

Retorne APENAS JSON, lista de problemas (vazio se não houver nenhum):
{{"problemas": [{{"indice": 0, "tipo": "cliche", "motivo": "..."}}]}}"""

    resposta = gemini_generate_fn(prompt)
    problemas = _extrair_json(resposta.text).get('problemas', [])

    if not problemas:
        return blocos

    indices_com_problema = sorted({p['indice'] for p in problemas if 0 <= p['indice'] < len(blocos)})
    if not indices_com_problema:
        return blocos

    trechos = "\n".join(
        f"[{i}] ({blocos[i]['bloco']}): {blocos[i]['texto']}\n"
        f"    problema: {[p['motivo'] for p in problemas if p['indice'] == i]}"
        for i in indices_com_problema
    )

    prompt_reescrita = f"""Reescreva APENAS os blocos abaixo, corrigindo o problema apontado.
Mantenha o mesmo sentido e o mesmo tamanho aproximado. Escreva em {idioma_conteudo}.

{trechos}

Retorne APENAS JSON: {{"reescritas": [{{"indice": 0, "texto_novo": "..."}}]}}"""

    resposta2 = gemini_generate_fn(prompt_reescrita)
    reescritas = _extrair_json(resposta2.text).get('reescritas', [])

    for r in reescritas:
        i = r.get('indice')
        if isinstance(i, int) and 0 <= i < len(blocos) and r.get('texto_novo'):
            blocos[i]['texto'] = r['texto_novo'].strip()

    return blocos


# ============================================================
# ESTÁGIO 5 — TÍTULO E DESCRIÇÃO (pipeline próprio)
# ============================================================

def gerar_titulo_final(tese_dict, estrutura, idioma_conteudo, gemini_generate_fn):
    prompt = f"""Gere 10 variantes de título de vídeo para YouTube, em {idioma_conteudo}.
Cada variante prioriza EXPLICITAMENTE um destes critérios (rotule qual):
- gap_curiosidade: cria uma lacuna de informação sem entregar a resposta
- especificidade: usa um detalhe concreto do vídeo
- contraste: usa a objeção/crença comum que a tese contraria

TESE: {tese_dict['tese']}
OBJEÇÃO: {estrutura['objecao']}
GANCHO: {estrutura['gancho']}

Para cada variante, responda também: esse título serviria pra QUALQUER vídeo desse nicho,
ou só faz sentido pra ESTE vídeo específico?

Retorne APENAS JSON:
{{
  "titulos": [
    {{"texto": "...", "criterio": "...", "exclusivo_deste_video": true}}
  ]
}}"""

    resposta = gemini_generate_fn(prompt)
    dados = _extrair_json(resposta.text)
    candidatos = [t for t in dados.get('titulos', []) if t.get('exclusivo_deste_video')]

    if not candidatos:
        candidatos = dados.get('titulos', [])
    if not candidatos:
        return tese_dict['tese'][:60]

    return candidatos[0]['texto']


def gerar_descricao_final(tese_dict, estrutura, idioma_conteudo, gemini_generate_fn):
    prompt = f"""Escreva a descrição do vídeo em duas partes, em {idioma_conteudo}.

TESE: {tese_dict['tese']}
OBJEÇÃO: {estrutura['objecao']}
IMPLICAÇÃO: {estrutura['implicacao']}

1. abertura_seo (até 150 caracteres): termos de busca reais que alguém digitaria sobre
   esse tema — não invente termos.
2. corpo: o que o espectador vai aprender e por que a tese é contestável, SEM entregar
   a conclusão do vídeo.

Retorne APENAS JSON: {{"abertura_seo": "...", "corpo": "..."}}"""

    resposta = gemini_generate_fn(prompt)
    return _extrair_json(resposta.text)


# ============================================================
# ORQUESTRAÇÃO — chamada única a partir do generate_video.py
# ============================================================

def gerar_pacote_roteiro(tema, contexto_nicho, idioma_conteudo, instrucao_extra,
                          documento_estilo, tipo_video, gemini_generate_fn):
    """
    Roda a cadeia completa. Se qualquer estágio falhar, cai pra um roteiro simples de
    emergência (uma chamada só, igual ao comportamento antigo) em vez de quebrar o
    workflow inteiro — mesmo espírito de fallback que já existe em criar_audio().
    """
    palavras_alvo = 180 if tipo_video == 'short' else 650

    try:
        print("  🎯 Estágio 1/5 — tese...")
        tese_dict = gerar_tese(tema, contexto_nicho, idioma_conteudo, gemini_generate_fn)
        if tese_dict.get('reprovar'):
            raise ValueError(f"Tese reprovada pelo próprio modelo: {tese_dict.get('tese')}")
        print(f"     tese: {tese_dict['tese']}")

        print("  🧱 Estágio 2/5 — estrutura argumentativa...")
        estrutura = gerar_estrutura(tese_dict, contexto_nicho, idioma_conteudo, gemini_generate_fn)

        print("  ✍️ Estágio 3/5 — escrita...")
        blocos = gerar_prosa(estrutura, contexto_nicho, idioma_conteudo, instrucao_extra,
                              documento_estilo, palavras_alvo, gemini_generate_fn)

        print("  🔍 Estágio 4/5 — crítica adversarial...")
        blocos = criticar_e_reescrever(blocos, idioma_conteudo, gemini_generate_fn)

        print("  🏷️ Estágio 5/5 — título e descrição...")
        titulo = gerar_titulo_final(tese_dict, estrutura, idioma_conteudo, gemini_generate_fn)
        descricao = gerar_descricao_final(tese_dict, estrutura, idioma_conteudo, gemini_generate_fn)

        roteiro_texto = " ".join(b['texto'] for b in blocos)

        return {
            'roteiro_texto': roteiro_texto,
            'roteiro_blocos': blocos,
            'titulo': titulo,
            'descricao': descricao,
            'tese': tese_dict['tese'],
            'modo': 'cadeia_completa',
        }

    except Exception as e:
        print(f"  ⚠️ Cadeia de roteiro falhou ({e}) — usando geração simples de emergência")
        prompt_simples = f"""Crie um roteiro de narração para um vídeo de {contexto_nicho} sobre "{tema}",
em {idioma_conteudo}, ~{palavras_alvo} palavras, tom direto. Escreva APENAS o roteiro corrido."""
        resposta = gemini_generate_fn(prompt_simples)
        roteiro_texto = re.sub(r'\*+', '', resposta.text).replace('#', '').strip()

        return {
            'roteiro_texto': roteiro_texto,
            'roteiro_blocos': [{'bloco': 'roteiro_completo', 'texto': roteiro_texto}],
            'titulo': tema,
            'descricao': {'abertura_seo': tema, 'corpo': roteiro_texto[:200]},
            'tese': None,
            'modo': 'fallback_simples',
        }
