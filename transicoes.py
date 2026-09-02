"""
transicoes.py
-------------
Fase 3 — biblioteca de transições entre clipes de vídeo, plugável por nome.

Cada função de transição tem a MESMA assinatura:

    transicao_xxx(clip_saida, clip_entrada, tempo_corte, duracao) -> (clip_saida, clip_entrada)

- clip_saida: o clipe que está terminando (já recortado/redimensionado, sem áudio)
- clip_entrada: o clipe que está começando (idem), ainda SEM set_start aplicado
  pro instante de corte — cada função decide como sobrepor os dois
- tempo_corte: instante (no relógio final do vídeo) em que a troca de bloco acontece
- duracao: duração alvo do efeito em segundos (cada função pode usar menos, se o
  efeito ficar melhor mais curto — glitch e flash, por exemplo, tendem a ficar
  exagerados em 0.7s e usam uma fração disso)

Devolve os dois clipes já prontos (com set_start e efeito aplicados) pra entrar
direto na lista de clips do CompositeVideoClip.

Adicionar uma transição nova = escrever uma função com essa assinatura e
registrar em TRANSICOES_DISPONIVEIS lá embaixo — generate_video.py não precisa
mudar nada além de listar o nome no config.json (chave 'transicoes_video').
"""

import numpy as np


# ============================================================
# 1. CROSSFADE — o padrão anterior, mantido como opção e fallback seguro
# ============================================================

def transicao_crossfade(clip_saida, clip_entrada, tempo_corte, duracao):
    """Dissolve clássico. Bom pra nichos de tom calmo/reflexivo — reflexão,
    devocional, motivacional. Serve de fallback se uma transição mais
    elaborada falhar ao renderizar."""
    entrada = clip_entrada.set_start(max(0, tempo_corte - duracao)).crossfadein(duracao)
    saida = clip_saida.crossfadeout(duracao)
    return saida, entrada


# ============================================================
# 2. FLASH — corte com estouro de branco, tipo "flash de câmera"/manchete nova
# ============================================================

def _fade_para_cor(clip, duracao, cor=(255, 255, 255), no_inicio=True):
    """
    Fade de/para uma cor sólida — o MoviePy só tem fade de/pra PRETO nativo
    (fadein/fadeout), então isso reimplementa o mesmo princípio pra qualquer
    cor (aqui, branco, pro efeito de flash).
    """
    cor_arr = np.array(cor, dtype='float32')

    def _filtro(get_frame, t):
        frame = get_frame(t).astype('float32')
        if no_inicio:
            progresso = min(1.0, t / duracao) if duracao > 0 else 1.0
        else:
            tempo_restante = clip.duration - t
            progresso = min(1.0, tempo_restante / duracao) if duracao > 0 else 1.0
        progresso = max(0.0, progresso)
        return (frame * progresso + cor_arr * (1 - progresso)).astype('uint8')

    return clip.fl(_filtro)


def transicao_flash(clip_saida, clip_entrada, tempo_corte, duracao):
    """
    Corte seco com flash branco no meio — comum em documentário/jornalismo pra
    marcar uma virada de assunto (efeito de "clique de câmera"/nova manchete).
    Mais curto e mais abrupto que o crossfade de propósito: um flash de 0.7s
    fica lento e chamativo demais, então limitamos a duração usada aqui.
    """
    duracao_efetiva = min(duracao, 0.35)
    saida = _fade_para_cor(clip_saida, duracao_efetiva, cor=(255, 255, 255), no_inicio=False)
    entrada = clip_entrada.set_start(max(0, tempo_corte - duracao_efetiva))
    entrada = _fade_para_cor(entrada, duracao_efetiva, cor=(255, 255, 255), no_inicio=True)
    return saida, entrada


# ============================================================
# 3. GLITCH — separação de canal + fatias deslocadas, decaindo até sumir
# ============================================================

def _distorcer_frame(frame, intensidade, seed):
    """intensidade vai de 0 (sem efeito) a 1 (efeito máximo)."""
    h, w = frame.shape[:2]
    resultado = frame.copy()

    rng = np.random.RandomState(seed)
    n_fatias = max(1, int(6 * intensidade))
    altura_fatia = max(1, h // 20)
    for _ in range(n_fatias):
        y0 = rng.randint(0, max(1, h - altura_fatia))
        deslocamento = int(rng.randint(-w // 12, w // 12 + 1) * intensidade)
        if deslocamento == 0:
            continue
        resultado[y0:y0 + altura_fatia] = np.roll(resultado[y0:y0 + altura_fatia], deslocamento, axis=1)

    deslocamento_canal = int(8 * intensidade)
    if deslocamento_canal > 0:
        resultado[:, :, 0] = np.roll(resultado[:, :, 0], deslocamento_canal, axis=1)
        resultado[:, :, 2] = np.roll(resultado[:, :, 2], -deslocamento_canal, axis=1)

    return resultado


def transicao_glitch(clip_saida, clip_entrada, tempo_corte, duracao):
    """
    Glitch digital: nos últimos instantes do clipe que sai e primeiros do que
    entra, desloca fatias horizontais da imagem e separa os canais RGB
    (chromatic aberration), decaindo até sumir. Efeito de transição dinâmico —
    combina com nicho tech/curiosidade/notícia, destoa de conteúdo calmo.
    """
    duracao_efetiva = min(duracao, 0.4)

    def _aplicar(clip, no_inicio, seed_base):
        def _filtro(get_frame, t):
            if no_inicio:
                progresso = max(0.0, 1.0 - t / duracao_efetiva) if duracao_efetiva > 0 else 0.0
            else:
                tempo_restante = clip.duration - t
                progresso = max(0.0, 1.0 - tempo_restante / duracao_efetiva) if duracao_efetiva > 0 else 0.0
            frame = get_frame(t)
            if progresso <= 0.02:
                return frame
            seed = seed_base + int(t * 1000)
            return _distorcer_frame(frame, progresso, seed)

        return clip.fl(_filtro)

    saida = _aplicar(clip_saida, no_inicio=False, seed_base=1)
    entrada = clip_entrada.set_start(max(0, tempo_corte - duracao_efetiva * 0.5))
    entrada = _aplicar(entrada, no_inicio=True, seed_base=2)
    return saida, entrada


# ============================================================
# 4. SHADOW WIPE — cortina com borda de sombra suave, tipo wipe duro
# ============================================================

def transicao_shadow_wipe(clip_saida, clip_entrada, tempo_corte, duracao, direcao='esquerda'):
    """
    O clipe novo "empurra" o antigo pra fora da tela (wipe), com uma faixa
    escura suave na linha de corte simulando sombra/profundidade — different
    do dissolve: é um corte duro com direção, não uma mistura gradual.
    """
    duracao_efetiva = min(duracao, 0.5)
    w, h = clip_saida.size
    largura_sombra = max(4, int(w * 0.03))
    duracao_total_saida = clip_saida.duration

    def _filtro_saida(get_frame, t):
        frame = get_frame(t)
        tempo_no_efeito = t - (duracao_total_saida - duracao_efetiva)
        if tempo_no_efeito < 0:
            return frame
        frame = frame.copy()
        progresso = min(1.0, tempo_no_efeito / duracao_efetiva) if duracao_efetiva > 0 else 1.0

        if direcao == 'esquerda':
            borda_x = int(w * (1 - progresso))
            if borda_x < w:
                frame[:, borda_x:] = 0
                ini_sombra = max(0, borda_x - largura_sombra)
                largura_real = borda_x - ini_sombra
                if largura_real > 0:
                    gradiente = np.linspace(1, 0, largura_real).reshape(1, -1, 1)
                    frame[:, ini_sombra:borda_x] = (
                        frame[:, ini_sombra:borda_x].astype('float32') * gradiente
                    ).astype('uint8')
        else:
            borda_x = int(w * progresso)
            if borda_x > 0:
                frame[:, :borda_x] = 0
                fim_sombra = min(w, borda_x + largura_sombra)
                largura_real = fim_sombra - borda_x
                if largura_real > 0:
                    gradiente = np.linspace(0, 1, largura_real).reshape(1, -1, 1)
                    frame[:, borda_x:fim_sombra] = (
                        frame[:, borda_x:fim_sombra].astype('float32') * gradiente
                    ).astype('uint8')
        return frame

    saida = clip_saida.fl(_filtro_saida)
    entrada = clip_entrada.set_start(max(0, tempo_corte - duracao_efetiva))
    return saida, entrada


# ============================================================
# REGISTRO — nome usado no config.json ('transicoes_video': [...])
# ============================================================

TRANSICOES_DISPONIVEIS = {
    'crossfade': transicao_crossfade,
    'flash': transicao_flash,
    'glitch': transicao_glitch,
    'shadow_wipe': transicao_shadow_wipe,
}
