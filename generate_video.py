import os
import json
import random
import re
import asyncio
import time
from datetime import datetime
import requests
import edge_tts
import numpy as np
from moviepy.editor import *
from google import generativeai as genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ============================================================
# Curadoria via Telegram (opcional)
# ============================================================
try:
    from telegram_curator_noticias import TelegramCuratorNoticias
    CURACAO_DISPONIVEL = True
except ImportError:
    print("⚠️ telegram_curator_noticias.py não encontrado")
    CURACAO_DISPONIVEL = False

CONFIG_FILE = 'config.json'
VIDEOS_DIR = 'videos'
ASSETS_DIR = 'assets'
VIDEO_TYPE = os.environ.get('VIDEO_TYPE', 'short')  # 'short' (vertical) ou 'long' (horizontal)

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
YOUTUBE_CREDENTIALS = os.environ.get('YOUTUBE_CREDENTIALS')
PEXELS_API_KEY = os.environ.get('PEXELS_API_KEY')

# ── Fish Audio (voz) ─────────────────────────────────────────────────────────
FISHAUDIO_API_KEY = os.environ.get('FISHAUDIO_API_KEY')
FISHAUDIO_VOICE_ID = os.environ.get('FISHAUDIO_VOICE_ID')
FISHAUDIO_MODEL = os.environ.get('FISHAUDIO_MODEL', 's2.1-pro-free')
FISHAUDIO_URL = "https://api.fish.audio/v1/tts"

GEMINI_TEXT_MODEL = os.environ.get('GEMINI_TEXT_MODEL', 'gemini-3.5-flash-lite')

USAR_CURACAO = os.environ.get('USAR_CURACAO', 'false').lower() == 'true' and CURACAO_DISPONIVEL
CURACAO_TIMEOUT = int(os.environ.get('CURACAO_TIMEOUT', '3600'))

# ── Modo de teste rápido (não usar em produção) ──────────────────────────────
LIMITE_CLIPES_TESTE = int(os.environ.get('LIMITE_CLIPES_TESTE', '0'))  # 0 = sem limite
PULAR_UPLOAD = os.environ.get('PULAR_UPLOAD', 'false').lower() == 'true'

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(GEMINI_TEXT_MODEL)

with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    config = json.load(f)


# ============================================================
# TEMA DO DIA — rotação sem repetição, igual ao canal infantil
# ============================================================

TEMAS_LOG_FILE = 'temas_usados.json'


def _carregar_temas_usados():
    if os.path.exists(TEMAS_LOG_FILE):
        try:
            with open(TEMAS_LOG_FILE, 'r', encoding='utf-8') as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def _salvar_tema_usado(tema):
    usados = _carregar_temas_usados()
    usados.add(tema)
    with open(TEMAS_LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(sorted(usados), f, indent=2, ensure_ascii=False)


def escolher_tema_reflexao():
    """Escolhe um tema de reflexão cristã/motivacional, priorizando a lista configurada."""
    temas_config = config.get('temas_reflexao', [])
    usados = _carregar_temas_usados()

    disponiveis = [t for t in temas_config if t not in usados]

    if disponiveis:
        tema = random.choice(disponiveis)
        print(f"💭 Tema (da lista configurada): {tema}")
        return tema

    print("💭 Lista de temas esgotada — pedindo sugestão ao Gemini...")
    prompt = f"""Sugira UM tema de reflexão cristã/motivacional (ex: gratidão, perdão, esperança),
que NÃO esteja nesta lista já usada: {sorted(usados)}

Responda APENAS com o nome do tema, curto. Ex: "confiança em tempos de incerteza"."""
    resposta = model.generate_content(prompt)
    tema = resposta.text.strip().strip('"')
    print(f"💭 Tema (sugerido pelo Gemini): {tema}")
    return tema


def gerar_titulo(tema):
    """Gera um título de vídeo chamativo a partir do tema do dia."""
    prompt = f"""Baseado no tema de reflexão cristã "{tema}", crie um título de vídeo curto e chamativo
para YouTube (estilo motivacional/inspiracional).

Retorne APENAS JSON: {{"titulo": "título aqui"}}"""

    response = model.generate_content(prompt)
    texto = response.text.strip().replace('```json', '').replace('```', '').strip()
    inicio = texto.find('{')
    fim = texto.rfind('}') + 1

    if inicio == -1 or fim == 0:
        return tema

    try:
        return json.loads(texto[inicio:fim]).get('titulo', tema)
    except Exception:
        return tema


def gerar_roteiro(tema, tipo_video):
    """Gera o roteiro de narração: versão curta (short) ou longa (vídeo de reflexão)."""
    if tipo_video == 'short':
        palavras_alvo = 180
        duracao_desc = '60-90 segundos'
    else:
        palavras_alvo = 650
        duracao_desc = '4-5 minutos'

    prompt = f"""Crie um roteiro de narração para um vídeo de reflexão cristã/motivacional sobre o tema:
"{tema}"

REGRAS OBRIGATÓRIAS:
- Duração alvo: {duracao_desc} de narração (~{palavras_alvo} palavras)
- Tom acolhedor, reflexivo, encorajador — como uma conversa sincera, não um sermão formal
- Pode referenciar ensinamentos ou princípios bíblicos relacionados ao tema, mas NUNCA cite passagens
  bíblicas literalmente/palavra por palavra — parafraseie a ideia ou mencione a referência (livro/capítulo)
  sem transcrever o texto integral, por respeito a direitos autorais de traduções específicas
- Termine com uma mensagem de esperança/encorajamento prática para o dia a dia
- NÃO mencione apresentador, elementos visuais ou câmera
- Texto corrido, pronto para narração
- SEM formatação, asteriscos, marcadores ou emojis

Escreva APENAS o roteiro."""

    response = model.generate_content(prompt)
    texto = response.text
    texto = re.sub(r'\*+', '', texto)
    texto = re.sub(r'#+\s', '', texto)
    texto = re.sub(r'^-\s', '', texto, flags=re.MULTILINE)
    texto = texto.replace('*', '').replace('#', '').replace('_', '').strip()
    return texto


# ============================================================
# ÁUDIO — Fish Audio (voz clonada) com fallback para Edge TTS
# ============================================================

def criar_audio_fishaudio(texto, output_file):
    if not FISHAUDIO_API_KEY:
        raise Exception("FISHAUDIO_API_KEY não configurada")

    headers = {
        "Authorization": f"Bearer {FISHAUDIO_API_KEY}",
        "Content-Type": "application/json",
        "model": FISHAUDIO_MODEL  # vai no header, não no body
    }
    payload = {
        "text": texto,
        "reference_id": FISHAUDIO_VOICE_ID,
        "format": "mp3"
    }

    resp = requests.post(FISHAUDIO_URL, headers=headers, json=payload, timeout=180)
    resp.raise_for_status()

    with open(output_file, 'wb') as f:
        f.write(resp.content)

    if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
        raise Exception("Arquivo de áudio vazio retornado pela Fish Audio")


async def criar_audio_edge_async(texto, output_file):
    voz = config.get('voz_fallback', 'pt-BR-ThalitaMultilingualNeural')
    for tentativa in range(3):
        try:
            communicate = edge_tts.Communicate(texto, voz, rate="+0%", pitch="+0Hz")
            await asyncio.wait_for(communicate.save(output_file), timeout=180)
            print("✅ Edge TTS (fallback)")
            return
        except asyncio.TimeoutError:
            print(f"⏱️ Timeout {tentativa + 1}")
            if tentativa < 2:
                await asyncio.sleep(10)
        except Exception as e:
            print(f"⚠️ Erro {tentativa + 1}: {e}")
            if tentativa < 2:
                await asyncio.sleep(10)
    raise Exception("Edge TTS falhou")


def criar_audio(texto, output_file):
    print("🎙️ Criando narração (Fish Audio)...")
    try:
        criar_audio_fishaudio(texto, output_file)
        print("✅ Fish Audio")
        return output_file
    except Exception as e:
        print(f"⚠️ Fish Audio falhou: {e} — usando Edge TTS como fallback")

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(criar_audio_edge_async(texto, output_file))
        loop.close()
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            return output_file
    except Exception as e:
        print(f"❌ Edge TTS: {e}")
        from gtts import gTTS
        tts = gTTS(text=texto, lang='pt-br', slow=False)
        tts.save(output_file)
        print("⚠️ gTTS usado (último recurso)")

    return output_file


# ============================================================
# PEXELS — busca e download de vídeos de banco, até cobrir a duração do áudio
# ============================================================

def escolher_termo_pesquisa(tema, roteiro):
    """
    Escolhe 1 termo de busca (em inglês) de uma lista PRÉ-VALIDADA por você no config.json.
    Isso evita o problema de termos ambíguos (ex: 'space' trazendo salas em vez de espaço sideral) —
    só termos já testados e confirmados como convergentes entram na lista.
    """
    termos_validados = config.get('termos_pesquisa_validados', [])
    if not termos_validados:
        raise Exception("config.json precisa ter 'termos_pesquisa_validados' preenchido")

    prompt = f"""Tema do vídeo: "{tema}"
Trecho do roteiro: "{roteiro[:300]}"

Escolha o termo MAIS adequado desta lista pré-aprovada (responda EXATAMENTE um item da lista, sem alterar
o texto, sem aspas, sem explicação):

{json.dumps(termos_validados, ensure_ascii=False)}"""

    resposta = model.generate_content(prompt)
    termo_escolhido = resposta.text.strip().strip('"').strip("'")

    if termo_escolhido not in termos_validados:
        print(f"  ⚠️ Gemini retornou termo fora da lista ('{termo_escolhido}') — usando aleatório da lista")
        termo_escolhido = random.choice(termos_validados)

    print(f"🔍 Termo de busca escolhido: {termo_escolhido}")
    return termo_escolhido


def _escolher_arquivo_video(video_files, largura_alvo):
    """Escolhe, entre os arquivos disponíveis de um vídeo do Pexels, o mais próximo da largura alvo."""
    candidatos = [vf for vf in video_files if vf.get('width') and vf.get('height')]
    if not candidatos:
        return None
    return min(candidatos, key=lambda vf: abs(vf['width'] - largura_alvo))


def pesquisar_videos_pexels(termo, orientacao, pagina=1, por_pagina=15):
    """Busca vídeos no Pexels. orientacao: 'portrait' (shorts) ou 'landscape' (vídeo longo)."""
    headers = {"Authorization": PEXELS_API_KEY}
    params = {
        "query": termo,
        "orientation": orientacao,
        "per_page": por_pagina,
        "page": pagina,
        "min_duration": 4,
    }
    resp = requests.get("https://api.pexels.com/videos/search", headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json().get('videos', [])


def baixar_clipes_pexels(termo, orientacao, duracao_alvo, offset_inicio=0.0):
    """
    Baixa vídeos do Pexels sequencialmente até cobrir duracao_alvo (segundos).
    Retorna lista de dicts: {'path', 'inicio', 'duracao'}.
    """
    largura_alvo = 1080 if orientacao == 'portrait' else 1920
    os.makedirs(f'{ASSETS_DIR}/pexels', exist_ok=True)

    videos_encontrados = pesquisar_videos_pexels(termo, orientacao, por_pagina=40)
    if not videos_encontrados:
        print(f"  ⚠️ Nenhum vídeo encontrado para '{termo}' ({orientacao})")
        return []

    random.shuffle(videos_encontrados)

    clipes = []
    tempo_coberto = 0.0
    usados_ids = set()

    for video in videos_encontrados:
        if tempo_coberto >= duracao_alvo:
            break
        if LIMITE_CLIPES_TESTE > 0 and len(clipes) >= LIMITE_CLIPES_TESTE:
            print(f"   ✂️ MODO TESTE: limitado a {LIMITE_CLIPES_TESTE} clipe(s)")
            break

        video_id = video.get('id')
        if video_id in usados_ids:
            continue
        usados_ids.add(video_id)

        arquivo = _escolher_arquivo_video(video.get('video_files', []), largura_alvo)
        if not arquivo:
            continue

        destino = f"{ASSETS_DIR}/pexels/{video_id}.mp4"
        try:
            print(f"  ⬇️ Baixando vídeo {video_id} ({video.get('duration')}s, {arquivo['width']}x{arquivo['height']})...")
            resp = requests.get(arquivo['link'], timeout=60)
            resp.raise_for_status()
            with open(destino, 'wb') as f:
                f.write(resp.content)
        except Exception as e:
            print(f"  ⚠️ Erro ao baixar vídeo {video_id}: {e}")
            continue

        duracao_disponivel = video.get('duration', 6)
        duracao_uso = min(duracao_disponivel, duracao_alvo - tempo_coberto)

        clipes.append({
            'path': destino,
            'inicio': offset_inicio + tempo_coberto,
            'duracao': duracao_uso
        })
        tempo_coberto += duracao_uso

    if tempo_coberto < duracao_alvo and clipes:
        print(f"  ⚠️ Cobertura parcial: {tempo_coberto:.1f}s/{duracao_alvo:.1f}s — "
              f"último clipe será esticado no momento da montagem")

    print(f"  ✅ {len(clipes)} clipe(s) baixado(s), cobrindo {tempo_coberto:.1f}s de {duracao_alvo:.1f}s")
    return clipes


# ============================================================
# TRANSIÇÃO "ONDA DE CALOR" (heat wave), estilo CapCut
# ============================================================

def _efeito_onda_calor(frame, t_relativo, duracao_transicao, direcao=1):
    progresso = min(max(t_relativo / duracao_transicao, 0.0), 1.0) if duracao_transicao > 0 else 1.0
    intensidade = (1 - progresso) * 18.0
    if intensidade <= 0.2:
        return frame

    altura, largura = frame.shape[0], frame.shape[1]
    linhas = np.arange(altura)
    deslocamento = (intensidade * np.sin(linhas / 22.0 + t_relativo * 14 * direcao)).astype(np.int32)

    idx_colunas = np.arange(largura)[None, :] - deslocamento[:, None]
    idx_colunas = np.clip(idx_colunas, 0, largura - 1)
    idx_colunas_expandido = np.repeat(idx_colunas[:, :, None], frame.shape[2], axis=2)

    return np.take_along_axis(frame, idx_colunas_expandido, axis=1)


def aplicar_transicao_onda_calor(clip, duracao_transicao=0.4, aparecendo=True):
    duracao_transicao = min(duracao_transicao, clip.duration / 2) if clip.duration else duracao_transicao

    if aparecendo:
        def filtro(get_frame, t):
            frame = get_frame(t)
            if t < duracao_transicao:
                return _efeito_onda_calor(frame, duracao_transicao - t, duracao_transicao, direcao=1)
            return frame
    else:
        fim = clip.duration

        def filtro(get_frame, t):
            frame = get_frame(t)
            if t > fim - duracao_transicao:
                return _efeito_onda_calor(frame, t - (fim - duracao_transicao), duracao_transicao, direcao=-1)
            return frame

    return clip.fl(filtro)


# ============================================================
# MONTAGEM DE VÍDEO
# ============================================================

def _preparar_clip_pexels(item, largura, altura):
    """Carrega, corta e redimensiona um clipe do Pexels pro formato alvo."""
    clip = VideoFileClip(item['path'])
    duracao_disponivel = clip.duration

    if duracao_disponivel > item['duracao']:
        clip = clip.subclip(0, item['duracao'])

    clip = clip.resize(height=altura)
    if clip.w > largura:
        clip = clip.crop(x_center=clip.w / 2, width=largura, height=altura)
    elif clip.w < largura:
        clip = clip.resize(width=largura)
    if clip.size != (largura, altura):
        clip = clip.resize((largura, altura))

    return clip.without_audio()


def _montar_clips_pexels(lista_clipes, largura, altura):
    clips_prontos = []
    total = len(lista_clipes)

    for i, item in enumerate(lista_clipes):
        try:
            clip = _preparar_clip_pexels(item, largura, altura)

            duracao_transicao = min(0.4, item['duracao'] * 0.3)
            if i > 0:
                clip = aplicar_transicao_onda_calor(clip, duracao_transicao, aparecendo=True)
            if i < total - 1:
                clip = aplicar_transicao_onda_calor(clip, duracao_transicao, aparecendo=False)

            clip = clip.set_start(item['inicio'])
            clips_prontos.append(clip)
        except Exception as e:
            print(f"  ⚠️ Erro ao preparar clipe {i}: {e}")

    return clips_prontos


def _mixar_musica_fundo(audio_narracao, duracao_total, volume=0.06, musicas_dir='assets/musicas'):
    import glob
    from moviepy.editor import AudioFileClip, CompositeAudioClip

    musicas = (glob.glob(f'{musicas_dir}/*.mp3') + glob.glob(f'{musicas_dir}/*.wav') +
               glob.glob(f'{musicas_dir}/*.ogg'))
    if not musicas:
        print("  ⚠️ Nenhuma música encontrada em assets/musicas/ — sem fundo")
        return audio_narracao

    musica_escolhida = random.choice(musicas)
    print(f"  🎼 Música: {os.path.basename(musica_escolhida)} (volume {int(volume * 100)}%)")
    musica = AudioFileClip(musica_escolhida)

    if musica.duration < duracao_total:
        import math
        from moviepy.editor import concatenate_audioclips
        repeticoes = math.ceil(duracao_total / musica.duration)
        musica = concatenate_audioclips([musica] * repeticoes)

    musica = musica.subclip(0, duracao_total).volumex(volume)
    return CompositeAudioClip([audio_narracao, musica])


def criar_video_curto(audio_path, lista_clipes, output_file, duracao_total):
    """Vídeo vertical (short), sem intro."""
    print("📹 Criando short (Pexels)...")
    clips_prontos = _montar_clips_pexels(lista_clipes, 1080, 1920)

    if not clips_prontos:
        return None

    if clips_prontos:
        ultimo = clips_prontos[-1]
        cobertura = ultimo.start + ultimo.duration
        if cobertura < duracao_total:
            clips_prontos[-1] = ultimo.set_duration(ultimo.duration + (duracao_total - cobertura))

    video_base = CompositeVideoClip(clips_prontos, size=(1080, 1920)).set_duration(duracao_total)

    audio_narr = AudioFileClip(audio_path)
    audio_final = _mixar_musica_fundo(audio_narr, duracao_total, volume=0.06)
    video_final = video_base.set_audio(audio_final)

    video_final.write_videofile(output_file, fps=30, codec='libx264', audio_codec='aac',
                                 preset='medium', bitrate='8000k', threads=4)

    video_final.close()
    audio_narr.close()
    for c in clips_prontos:
        c.close()
    return output_file


def criar_video_longo(audio_path, lista_clipes, output_file, duracao_narracao):
    """Vídeo horizontal (long), com intro fixa de assets/intro/."""
    print("📹 Criando vídeo longo (Pexels + intro)...")

    import glob
    intros = glob.glob(f'{ASSETS_DIR}/intro/*.mp4') + glob.glob(f'{ASSETS_DIR}/intro/*.mov')
    intro_duracao = 0.0
    intro_clip = None

    if intros:
        intro_path = random.choice(intros) if len(intros) > 1 else intros[0]
        print(f"  🎬 Intro: {os.path.basename(intro_path)}")
        intro_bruto = VideoFileClip(intro_path)
        intro_clip = intro_bruto.resize(height=1080)
        if intro_clip.w > 1920:
            intro_clip = intro_clip.crop(x_center=intro_clip.w / 2, width=1920, height=1080)
        elif intro_clip.w < 1920:
            intro_clip = intro_clip.resize(width=1920)
        if intro_clip.size != (1920, 1080):
            intro_clip = intro_clip.resize((1920, 1080))
        intro_clip = intro_clip.without_audio()
        intro_duracao = intro_clip.duration
    else:
        print("  ℹ️ Nenhuma intro encontrada em assets/intro/ — seguindo sem intro")

    clips_prontos = _montar_clips_pexels(lista_clipes, 1920, 1080)
    # Desloca todos os clipes de conteúdo pra depois da intro
    clips_deslocados = [c.set_start(c.start + intro_duracao) for c in clips_prontos]

    duracao_total = intro_duracao + duracao_narracao

    if clips_deslocados:
        ultimo = clips_deslocados[-1]
        cobertura = ultimo.start + ultimo.duration
        if cobertura < duracao_total:
            clips_deslocados[-1] = ultimo.set_duration(ultimo.duration + (duracao_total - cobertura))

    todos_os_clips = ([intro_clip] if intro_clip else []) + clips_deslocados
    if not todos_os_clips:
        return None

    video_base = CompositeVideoClip(todos_os_clips, size=(1920, 1080)).set_duration(duracao_total)

    audio_narr = AudioFileClip(audio_path).set_start(intro_duracao)
    audio_final = _mixar_musica_fundo(audio_narr, duracao_total, volume=0.06)
    video_final = video_base.set_audio(audio_final)

    video_final.write_videofile(output_file, fps=24, codec='libx264', audio_codec='aac',
                                 preset='medium', bitrate='6000k', threads=4)

    video_final.close()
    audio_narr.close()
    for c in todos_os_clips:
        c.close()
    return output_file


def fazer_upload_youtube(video_path, titulo, descricao, tags, thumbnail_path=None):
    creds_dict = json.loads(YOUTUBE_CREDENTIALS)
    credentials = Credentials.from_authorized_user_info(creds_dict)
    youtube = build('youtube', 'v3', credentials=credentials)

    body = {
        'snippet': {'title': titulo, 'description': descricao, 'tags': tags, 'categoryId': '22'},
        'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}
    }

    media = MediaFileUpload(video_path, resumable=True)
    request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
    response = request.execute()
    video_id = response['id']

    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(thumbnail_path)).execute()
        except Exception as e:
            print(f"❌ Erro thumbnail: {e}")

    return video_id


def main():
    print(f"{'📱' if VIDEO_TYPE == 'short' else '🎬'} Iniciando ({VIDEO_TYPE})...")
    os.makedirs(VIDEOS_DIR, exist_ok=True)
    os.makedirs(ASSETS_DIR, exist_ok=True)

    tema = escolher_tema_reflexao()
    titulo_video = gerar_titulo(tema)
    print(f"🎯 Título: {titulo_video}")

    print("✍️ Gerando roteiro...")
    roteiro = gerar_roteiro(tema, VIDEO_TYPE)

    audio_path = f'{ASSETS_DIR}/audio.mp3'
    criar_audio(roteiro, audio_path)

    audio_clip = AudioFileClip(audio_path)
    duracao_narracao = audio_clip.duration
    audio_clip.close()
    print(f"⏱️ {duracao_narracao:.1f}s de narração")

    termo = escolher_termo_pesquisa(tema, roteiro)
    orientacao = 'portrait' if VIDEO_TYPE == 'short' else 'landscape'
    lista_clipes = baixar_clipes_pexels(termo, orientacao, duracao_narracao)

    if not lista_clipes:
        print("❌ Nenhum clipe baixado — abortando este ciclo.")
        return

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    video_path = f'{VIDEOS_DIR}/{VIDEO_TYPE}_{timestamp}.mp4'

    print("🎥 Montando vídeo...")
    try:
        if VIDEO_TYPE == 'short':
            resultado = criar_video_curto(audio_path, lista_clipes, video_path, duracao_narracao)
        else:
            resultado = criar_video_longo(audio_path, lista_clipes, video_path, duracao_narracao)

        if not resultado:
            print("❌ Erro ao criar vídeo")
            return
        print("✅ Vídeo criado!")
    except Exception as e:
        print(f"❌ Erro: {e}")
        import traceback
        traceback.print_exc()
        return

    titulo = titulo_video[:60] if len(titulo_video) <= 60 else titulo_video[:57] + '...'
    if VIDEO_TYPE == 'short':
        titulo += ' #shorts'

    descricao = roteiro[:300] + '...\n\n🔔 Inscreva-se para reflexões diárias!\n#' + \
                ('shorts' if VIDEO_TYPE == 'short' else 'reflexao')
    tags = config.get('tags_padrao', ['reflexao ccrista', 'motivacional', 'fe', 'inspiracao'])
    if VIDEO_TYPE == 'short':
        tags.append('shorts')

    _salvar_tema_usado(tema)

    if PULAR_UPLOAD:
        print(f"\n⏭️ PULAR_UPLOAD ativo — vídeo NÃO será publicado. Disponível em: {video_path}")
        print("=" * 60)
        print("✅ TESTE CONCLUÍDO (sem publicação)")
        print("=" * 60)
        return

    print("\n📤 Upload YouTube...")
    try:
        video_id = fazer_upload_youtube(video_path, titulo, descricao, tags)
        url = f'https://youtube.com/{"shorts/" if VIDEO_TYPE == "short" else "watch?v="}{video_id}'
        print(f"✅ Publicado!\n🔗 {url}")

        log_entry = {
            'data': datetime.now().isoformat(), 'tipo': VIDEO_TYPE, 'tema': tema,
            'titulo': titulo, 'duracao': duracao_narracao, 'video_id': video_id, 'url': url
        }
        log_file = 'videos_gerados.json'
        logs = []
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                logs = json.load(f)
        logs.append(log_entry)
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(logs, f, indent=2, ensure_ascii=False)

    except Exception as e:
        print(f"❌ Erro no upload YouTube: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)
    print("✅ WORKFLOW CONCLUÍDO")
    print("=" * 60)


if __name__ == '__main__':
    main()
