import os
import json
import random
import re
import asyncio
import time
import sys
from datetime import datetime
import requests
import edge_tts
import numpy as np
from moviepy.editor import *
from google import generativeai as genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from PIL import Image

# ============================================================
# Curadoria via Telegram (mantida — não fazia parte da lista de remoção)
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
VIDEO_TYPE = os.environ.get('VIDEO_TYPE', 'short')

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
YOUTUBE_CREDENTIALS = os.environ.get('YOUTUBE_CREDENTIALS')

# ── Fish Audio (voz) ─────────────────────────────────────────────────────────
# ⚠️ Confirme na documentação atual da Fish Audio (fish.audio/docs) o nome exato
#    do endpoint, do modelo gratuito e do formato do payload — essa API mudou de
#    política de free tier recentemente (S2 -> S2.1 Pro) e pode mudar de novo.
FISHAUDIO_API_KEY = os.environ.get('FISHAUDIO_API_KEY')
FISHAUDIO_VOICE_ID = os.environ.get('FISHAUDIO_VOICE_ID')  # reference_id do modelo de voz na sua conta
FISHAUDIO_MODEL = os.environ.get('FISHAUDIO_MODEL', 's2.1-pro-free')
FISHAUDIO_URL = "https://api.fish.audio/v1/tts"

# ── Gemini — imagem hiper-realista ("Nano Banana") ──────────────────────────
# ⚠️ Confirme o nome do modelo de imagem vigente na doc do Gemini — a Google
#    tem trocado esses nomes com frequência (ex.: gemini-2.5-flash-image).
IMAGEM_MODEL_NAME = os.environ.get('GEMINI_IMAGE_MODEL', 'gemini-2.5-flash-image')

# Configuração de curadoria
USAR_CURACAO = os.environ.get('USAR_CURACAO', 'false').lower() == 'true' and CURACAO_DISPONIVEL
CURACAO_TIMEOUT = int(os.environ.get('CURACAO_TIMEOUT', '3600'))

genai.configure(api_key=GEMINI_API_KEY)
GEMINI_TEXT_MODEL = os.environ.get('GEMINI_TEXT_MODEL', 'gemini-3.5-flash-lite')
model = genai.GenerativeModel(GEMINI_TEXT_MODEL)
imagem_model = genai.GenerativeModel(IMAGEM_MODEL_NAME)

with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    config = json.load(f)


HISTORIAS_LOG_FILE = 'historias_usadas.json'


def _carregar_historias_usadas():
    if os.path.exists(HISTORIAS_LOG_FILE):
        try:
            with open(HISTORIAS_LOG_FILE, 'r', encoding='utf-8') as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def _salvar_historia_usada(nome_historia):
    usadas = _carregar_historias_usadas()
    usadas.add(nome_historia)
    with open(HISTORIAS_LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(sorted(usadas), f, indent=2, ensure_ascii=False)


def escolher_historia_biblica():
    """
    Escolhe uma história bíblica para o episódio.

    Prioriza a lista fixa em config.json (campo 'historias'), o que garante
    conteúdo teologicamente apropriado e controlado por você. Se a lista
    configurada se esgotar, pede ao Gemini para sugerir uma história bíblica
    conhecida (Antigo ou Novo Testamento) ainda não usada, adequada para crianças.
    """
    historias_config = config.get('historias', [])
    usadas = _carregar_historias_usadas()

    disponiveis = [h for h in historias_config if h not in usadas]

    if disponiveis:
        historia = random.choice(disponiveis)
        print(f"📖 História (da lista configurada): {historia}")
        return historia

    print("📖 Lista de histórias configuradas esgotada — pedindo sugestão ao Gemini...")
    prompt = f"""Sugira UMA história bíblica conhecida (Antigo ou Novo Testamento),
adequada para crianças, que NÃO esteja nesta lista já usada: {sorted(usadas)}

Responda APENAS com o nome da história, de forma curta. Ex: "Daniel na cova dos leões"."""
    resposta = model.generate_content(prompt)
    historia = resposta.text.strip().strip('"')
    print(f"📖 História (sugerida pelo Gemini): {historia}")
    return historia


def gerar_titulo_infantil(historia):
    """Gera um título chamativo e adequado para crianças a partir da história bíblica escolhida."""
    prompt = f"""Baseado na história bíblica "{historia}", crie um título de vídeo curto,
chamativo e adequado para CRIANÇAS (estilo canal infantil no YouTube), e uma breve descrição do que a história ensina.

Retorne APENAS JSON: {{"titulo": "título aqui", "licao": "lição/moral da história em uma frase"}}"""

    response = model.generate_content(prompt)
    texto = response.text.strip().replace('```json', '').replace('```', '').strip()

    inicio = texto.find('{')
    fim = texto.rfind('}') + 1

    if inicio == -1 or fim == 0:
        return {"titulo": historia, "licao": ""}

    try:
        return json.loads(texto[inicio:fim])
    except Exception:
        return {"titulo": historia, "licao": ""}


def gerar_roteiro(duracao_alvo, historia, licao=""):
    """Gera roteiro de narração de história bíblica infantil (short)."""
    if duracao_alvo != 'short':
        raise Exception("Este fluxo foi ajustado apenas para shorts infantis")

    palavras_alvo = 200
    tempo = '60-90 segundos'

    prompt = f"""Crie um roteiro de narração para um short infantil contando a história bíblica: "{historia}"

{f'A lição/moral a transmitir é: {licao}' if licao else ''}

REGRAS OBRIGATÓRIAS:
- {tempo} de narração, aproximadamente {palavras_alvo} palavras
- Linguagem simples, calorosa e acolhedora, adequada para CRIANÇAS
- Tom de contador de histórias (storytelling), não jornalístico
- Fidelidade ao sentido da história bíblica, mas SEM detalhes gráficos, violentos ou assustadores — trate qualquer trecho de conflito de forma leve e apropriada para crianças pequenas
- Termine com a lição/moral da história de forma clara e positiva
- NÃO mencione apresentador ou elementos visuais/câmera
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
    """Gera narração usando a API do Fish Audio (voz clonada)."""
    if not FISHAUDIO_API_KEY:
        raise Exception("FISHAUDIO_API_KEY não configurada")

    headers = {
        "Authorization": f"Bearer {FISHAUDIO_API_KEY}",
        "Content-Type": "application/json",
        "model": FISHAUDIO_MODEL  # ⚠️ vai no header, não no body — confirmado no exemplo oficial
    }
    payload = {
        "text": texto,
        "reference_id": FISHAUDIO_VOICE_ID,
        "format": "mp3"
    }

    resp = requests.post(FISHAUDIO_URL, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()

    with open(output_file, 'wb') as f:
        f.write(resp.content)

    if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
        raise Exception("Arquivo de áudio vazio retornado pela Fish Audio")


async def criar_audio_edge_async(texto, output_file):
    """Fallback: Edge TTS (async)"""
    voz = config.get('voz_fallback', 'pt-BR-ThalitaMultilingualNeural')

    for tentativa in range(3):
        try:
            communicate = edge_tts.Communicate(texto, voz, rate="+0%", pitch="+0Hz")
            await asyncio.wait_for(communicate.save(output_file), timeout=120)
            print(f"✅ Edge TTS (fallback)")
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
    """Cria áudio: tenta Fish Audio (voz clonada) primeiro, cai para Edge TTS se falhar."""
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
# SEGMENTAÇÃO — Whisper (timestamps reais do áudio gerado)
# ============================================================

_whisper_model = None


def _carregar_whisper():
    """Carrega o modelo Whisper uma única vez (lazy load)."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        print("🧠 Carregando modelo Whisper (base, CPU)...")
        _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
    return _whisper_model


def transcrever_com_timestamps(audio_path):
    """Transcreve o áudio já gerado e retorna segmentos com início/fim reais."""
    whisper_model = _carregar_whisper()
    segments, _info = whisper_model.transcribe(audio_path, language="pt", word_timestamps=False)

    resultado = []
    for seg in segments:
        texto = seg.text.strip()
        if texto:
            resultado.append({
                'inicio': seg.start,
                'fim': seg.end,
                'texto': texto
            })
    return resultado


# ============================================================
# IMAGENS — geração via IA (hiper-realista), substitui a busca em assets/
# ============================================================


def gerar_prompt_imagem_profissional(texto_segmento, contexto_geral, tentativas=3):
    """
    Usa o Gemini para criar um prompt de geração de imagem em estilo Pixar 3D,
    no nível de um diretor de arte de animação profissional.
    """
    prompt = f"""Você é um diretor de arte de animação, especializado em prompts para geração de imagens
no estilo Pixar/DreamWorks (animação 3D infantil).

CONTEXTO GERAL DO VÍDEO (história bíblica infantil): {contexto_geral}

TRECHO DA NARRAÇÃO A ILUSTRAR: "{texto_segmento}"

Crie um prompt de geração de imagem em INGLÊS, extremamente detalhado, no nível de um diretor de arte de animação profissional. O prompt deve obrigatoriamente:
- Especificar estilo "3D Pixar-style animation, Disney-Pixar character design, soft rounded shapes, big expressive eyes, warm cinematic lighting, vibrant colors, family-friendly, 9:16 vertical composition"
- Descrever a cena, iluminação e composição de forma cinematográfica, adequada para crianças
- Para CADA personagem presente na cena, descrever: cor e modelo da roupa (vestes de época bíblica), detalhes da roupa (textura, tecido, acessórios), cor do cabelo e comprimento do cabelo, expressão facial gentil/expressiva
- Evitar QUALQUER elemento gráfico, violento ou assustador — a cena deve ser sempre acolhedora e apropriada para crianças pequenas, mesmo em momentos de tensão da história
- Manter consistência visual de "livro de histórias bíblicas animado para crianças"

Retorne APENAS o prompt final em inglês, sem explicações, sem aspas."""

    for tentativa in range(tentativas):
        try:
            resposta = model.generate_content(prompt)
            # Dá um tempinho de respiro para não estourar a cota de RPM
            time.sleep(3) 
            return resposta.text.strip()
            
        except Exception as e:
            print(f"  ⚠️ Erro ao gerar prompt (tentativa {tentativa + 1}): {e}")
            # Se der erro 504 ou 429, espera 10 segundos antes de tentar de novo
            time.sleep(10)
            
    # Se falhar todas as vezes, retorna uma string vazia ou um prompt genérico
    return "3D Pixar-style animation, beautiful scene, family-friendly, 9:16 vertical composition"


def gerar_imagem_ia(prompt_imagem, output_path, tentativas=3):
    """Gera uma imagem hiper-realista via Gemini (Nano Banana) e salva em disco."""
    for tentativa in range(tentativas):
        try:
            resposta = imagem_model.generate_content(prompt_imagem)
            for parte in resposta.candidates[0].content.parts:
                inline_data = getattr(parte, 'inline_data', None)
                if inline_data is not None and inline_data.data:
                    with open(output_path, 'wb') as f:
                        f.write(inline_data.data)
                    
                    # Pausa no SUCESSO para não estourar limite do Google
                    time.sleep(6) 
                    return output_path
                    
            print(f"  ⚠️ Resposta sem dados de imagem (tentativa {tentativa + 1})")
        except Exception as e:
            print(f"  ⚠️ Erro ao gerar imagem (tentativa {tentativa + 1}): {e}")
        
        # Pausa no ERRO (seja timeout ou limite excedido)
        time.sleep(10) 
        
    return None


def gerar_midias_sincronizadas_ia(roteiro, audio_path, titulo_video):
    """
    Substitui a antiga busca em assets/: segmenta o áudio via Whisper (timestamps reais)
    e gera uma imagem hiper-realista por IA para cada segmento.
    """
    print("🧠 Transcrevendo áudio com Whisper para obter timestamps reais...")
    segmentos_whisper = transcrever_com_timestamps(audio_path)
    print(f"   {len(segmentos_whisper)} segmentos identificados pelo Whisper")

    midias_sincronizadas = []
    ultima_imagem_ok = None

    for i, seg in enumerate(segmentos_whisper):
        duracao_seg = seg['fim'] - seg['inicio']
        if duracao_seg <= 0 or not seg['texto']:
            continue

        print(f"\n  🎬 Segmento {i + 1}/{len(segmentos_whisper)} ({duracao_seg:.1f}s): {seg['texto'][:60]}...")

        prompt_imagem = gerar_prompt_imagem_profissional(seg['texto'], titulo_video)
        caminho_imagem = f"{ASSETS_DIR}/gerado_{i:03d}.png"
        resultado = gerar_imagem_ia(prompt_imagem, caminho_imagem)

        if resultado:
            ultima_imagem_ok = resultado
        else:
            print("  ⚠️ Falha na geração — reutilizando última imagem gerada com sucesso")
            resultado = ultima_imagem_ok

        if resultado:
            midias_sincronizadas.append({
                'midia': (resultado, 'imagem_ia'),
                'inicio': seg['inicio'],
                'duracao': duracao_seg,
                'texto': seg['texto'][:50],
                'texto_completo': seg['texto'],
                'keywords': []
            })

    print(f"\n✅ Total: {len(midias_sincronizadas)}/{len(segmentos_whisper)} segmentos com imagem")

    # CURADORIA (Telegram) — fluxo mantido, agora sobre imagens geradas por IA
    if USAR_CURACAO:
        print("\n" + "=" * 60)
        print("🎬 MODO CURADORIA ATIVADO")
        print("=" * 60)

        try:
            curator = TelegramCuratorNoticias()
            curator.solicitar_curacao(midias_sincronizadas)
            midias_aprovadas = curator.aguardar_aprovacao(timeout=CURACAO_TIMEOUT)

            if midias_aprovadas:
                print("✅ Mídias aprovadas pela curadoria!")
                midias_sincronizadas = midias_aprovadas
            else:
                print("⏰ Timeout da curadoria — usando imagens geradas automaticamente")
                try:
                    curator.enviar_mensagem(
                        "⚠️ <b>Curadoria expirou</b>\n"
                        "Vídeo montado automaticamente com as imagens geradas por IA."
                    )
                except Exception:
                    pass

        except Exception as e:
            print(f"⚠️ Erro na curadoria: {e} — continuando automaticamente")

    # Fallback final: se nada foi gerado, evita quebrar o pipeline
    if not midias_sincronizadas:
        print("⚠️ Nenhuma imagem gerada — o vídeo não pode ser montado sem mídia.")

    return midias_sincronizadas


# ============================================================
# TRANSIÇÃO "ONDA DE CALOR" (heat wave), estilo CapCut
# ============================================================

def _efeito_onda_calor(frame, t_relativo, duracao_transicao, direcao=1):
    """Distorce o frame horizontalmente em ondas, com intensidade decaindo com o tempo."""
    progresso = min(max(t_relativo / duracao_transicao, 0.0), 1.0) if duracao_transicao > 0 else 1.0
    intensidade = (1 - progresso) * 18.0  # deslocamento máximo em pixels, decai até 0

    if intensidade <= 0.2:
        return frame

    altura, largura = frame.shape[0], frame.shape[1]
    linhas = np.arange(altura)
    deslocamento = (intensidade * np.sin(linhas / 22.0 + t_relativo * 14 * direcao)).astype(np.int32)

    idx_colunas = np.arange(largura)[None, :] - deslocamento[:, None]
    idx_colunas = np.clip(idx_colunas, 0, largura - 1)
    idx_colunas_expandido = np.repeat(idx_colunas[:, :, None], frame.shape[2], axis=2)

    frame_distorcido = np.take_along_axis(frame, idx_colunas_expandido, axis=1)
    return frame_distorcido


def aplicar_transicao_onda_calor(clip, duracao_transicao=0.4, aparecendo=True):
    """
    Aplica a distorção de onda de calor no início (aparecendo=True) ou
    no final (aparecendo=False) do clip, simulando a transição do CapCut.
    """
    duracao_transicao = min(duracao_transicao, clip.duration / 2) if clip.duration else duracao_transicao

    if aparecendo:
        def filtro(get_frame, t):
            frame = get_frame(t)
            if t < duracao_transicao:
                t_relativo = duracao_transicao - t
                return _efeito_onda_calor(frame, t_relativo, duracao_transicao, direcao=1)
            return frame
    else:
        fim = clip.duration

        def filtro(get_frame, t):
            frame = get_frame(t)
            if t > fim - duracao_transicao:
                t_relativo = t - (fim - duracao_transicao)
                return _efeito_onda_calor(frame, t_relativo, duracao_transicao, direcao=-1)
            return frame

    return clip.fl(filtro)


# ============================================================
# MONTAGEM DE VÍDEO
# ============================================================

def preparar_clip_video(video_path, duracao_alvo, orientacao='short'):
    """Carrega e prepara um clip de vídeo, cortando o excedente se necessário."""
    try:
        clip = VideoFileClip(video_path)
        duracao_original = clip.duration

        print(f"  🎬 Vídeo: {duracao_original:.1f}s | Segmento: {duracao_alvo:.1f}s")

        if duracao_original > duracao_alvo:
            print(f"  ✂️ Cortando vídeo de {duracao_original:.1f}s → {duracao_alvo:.1f}s")
            clip = clip.subclip(0, duracao_alvo)

        if orientacao == 'short':
            clip = clip.resize(height=1920)
            if clip.w > 1080:
                clip = clip.crop(x_center=clip.w / 2, width=1080, height=1920)
            elif clip.w < 1080:
                clip = clip.resize(width=1080)
            if clip.size != (1080, 1920):
                clip = clip.resize((1080, 1920))
        else:
            clip = clip.resize(height=1080)
            if clip.w < 1920:
                clip = clip.resize(width=1920)
            clip = clip.crop(x_center=clip.w / 2, y_center=clip.h / 2, width=1920, height=1080)
            if clip.size != (1920, 1080):
                clip = clip.resize((1920, 1080))

        clip = clip.without_audio()
        return clip

    except Exception as e:
        print(f"  ❌ Erro ao preparar clip de vídeo: {e}")
        return None


def _mixar_musica_fundo(audio_narracao, duracao_total: float,
                         volume: float = 0.09,
                         musicas_dir: str = 'assets/musicas'):
    """Escolhe uma música aleatória da pasta assets/musicas/ e mixa com a narração."""
    import glob
    import random as _random
    from moviepy.editor import AudioFileClip, CompositeAudioClip

    try:
        musicas = (glob.glob(f'{musicas_dir}/*.mp3') +
                   glob.glob(f'{musicas_dir}/*.wav') +
                   glob.glob(f'{musicas_dir}/*.ogg'))

        if not musicas:
            print("  ⚠️ Nenhuma música encontrada em assets/musicas/ — sem fundo")
            return audio_narracao

        musica_escolhida = _random.choice(musicas)
        print(f"  🎼 Música: {os.path.basename(musica_escolhida)} (volume {int(volume * 100)}%)")

        musica = AudioFileClip(musica_escolhida)

        if musica.duration < duracao_total:
            import math
            repeticoes = math.ceil(duracao_total / musica.duration)
            from moviepy.editor import concatenate_audioclips
            musica = concatenate_audioclips([musica] * repeticoes)

        musica = musica.subclip(0, duracao_total).volumex(volume)

        audio_mixado = CompositeAudioClip([audio_narracao, musica])
        return audio_mixado

    except Exception as e:
        print(f"  ⚠️ Erro ao adicionar música: {e} — usando só narração")
        return audio_narracao


def _montar_clips_imagem(midias_sincronizadas, orientacao='short'):
    """Constrói a lista de clips (zoom Ken Burns + transição onda de calor) a partir das mídias geradas por IA."""
    clips_imagem = []
    tempo_coberto = 0
    total = len(midias_sincronizadas)

    for i, item in enumerate(midias_sincronizadas):
        midia_info, midia_tipo = item['midia']
        inicio = item['inicio']
        duracao_clip = item['duracao']

        try:
            if midia_tipo == 'video_local' and os.path.exists(midia_info):
                clip = preparar_clip_video(midia_info, duracao_clip, orientacao=orientacao)
                if clip is None:
                    raise Exception("Falha no clip de vídeo")

            elif midia_tipo == 'imagem_ia' and os.path.exists(midia_info):
                clip = ImageClip(midia_info, duration=duracao_clip)
                if orientacao == 'short':
                    clip = clip.resize(height=1920)
                    if clip.w > 1080:
                        clip = clip.crop(x_center=clip.w / 2, width=1080, height=1920)
                    elif clip.w < 1080:
                        clip = clip.resize(width=1080)
                    if clip.size != (1080, 1920):
                        clip = clip.resize((1080, 1920))
                    fator_zoom = 0.04
                else:
                    clip = clip.resize(height=1080)
                    if clip.w < 1920:
                        clip = clip.resize(width=1920)
                    clip = clip.crop(x_center=clip.w / 2, y_center=clip.h / 2, width=1920, height=1080)
                    if clip.size != (1920, 1080):
                        clip = clip.resize((1920, 1080))
                    fator_zoom = 0.03

                # Zoom Ken Burns
                clip = clip.resize(lambda t: 1 + fator_zoom * (t / duracao_clip))

                # Transição "onda de calor" entre segmentos (estilo CapCut)
                duracao_transicao = min(0.4, duracao_clip * 0.3)
                if i > 0:
                    clip = aplicar_transicao_onda_calor(clip, duracao_transicao, aparecendo=True)
                if i < total - 1:
                    clip = aplicar_transicao_onda_calor(clip, duracao_transicao, aparecendo=False)
            else:
                continue

            clip = clip.set_start(inicio)
            clips_imagem.append(clip)
            tempo_coberto = max(tempo_coberto, inicio + duracao_clip)

        except Exception as e:
            print(f"  ⚠️ Erro mídia {i}: {e}")

    return clips_imagem, tempo_coberto


def criar_video_short_sem_legendas(audio_path, midias_sincronizadas, output_file, duracao_total):
    """Cria SHORT sem legendas usando imagens geradas por IA."""
    print(f"📹 Criando short (sem legendas)...")

    clips_imagem, tempo_coberto = _montar_clips_imagem(midias_sincronizadas, orientacao='short')

    if tempo_coberto < duracao_total and clips_imagem:
        # Fallback simples: estende o último clip até cobrir o tempo total
        print(f"⚠️ Cobertura incompleta ({tempo_coberto:.1f}s/{duracao_total:.1f}s) — estendendo último clip")
        ultimo = clips_imagem[-1]
        extra = duracao_total - tempo_coberto
        clips_imagem[-1] = ultimo.set_duration(ultimo.duration + extra)

    if not clips_imagem:
        print("❌ Nenhum clip de imagem criado!")
        return None

    print("🎬 Compondo vídeo...")
    video_base = CompositeVideoClip(clips_imagem, size=(1080, 1920))
    video_base = video_base.set_duration(duracao_total)

    print("🎵 Adicionando áudio...")
    audio_narr = AudioFileClip(audio_path)

    audio_final = _mixar_musica_fundo(audio_narr, duracao_total, volume=0.06)
    video_final = video_base.set_audio(audio_final)

    print("💾 Renderizando...")
    video_final.write_videofile(
        output_file,
        fps=30,
        codec='libx264',
        audio_codec='aac',
        preset='medium',
        bitrate='8000k',
        threads=4
    )

    print("🧹 Limpando memória...")
    video_final.close()
    audio_narr.close()
    for clip in clips_imagem:
        clip.close()

    return output_file


def criar_video_long_sem_legendas(audio_path, midias_sincronizadas, output_file, duracao_total):
    """Cria vídeo longo sem legendas usando imagens geradas por IA."""
    print(f"📹 Criando vídeo longo...")

    clips_imagem, tempo_coberto = _montar_clips_imagem(midias_sincronizadas, orientacao='long')

    if tempo_coberto < duracao_total and clips_imagem:
        print(f"⚠️ Cobertura incompleta ({tempo_coberto:.1f}s/{duracao_total:.1f}s) — estendendo último clip")
        ultimo = clips_imagem[-1]
        extra = duracao_total - tempo_coberto
        clips_imagem[-1] = ultimo.set_duration(ultimo.duration + extra)

    if not clips_imagem:
        return None

    video_base = CompositeVideoClip(clips_imagem, size=(1920, 1080))
    video_base = video_base.set_duration(duracao_total)

    print("🎵 Adicionando áudio...")
    audio_narr = AudioFileClip(audio_path)

    audio_final = _mixar_musica_fundo(audio_narr, duracao_total, volume=0.06)
    video_final = video_base.set_audio(audio_final)

    print("💾 Renderizando...")
    video_final.write_videofile(
        output_file,
        fps=24,
        codec='libx264',
        audio_codec='aac',
        preset='medium',
        bitrate='5000k',
        threads=4
    )

    video_final.close()
    audio_narr.close()
    for clip in clips_imagem:
        clip.close()

    return output_file


def fazer_upload_youtube(video_path, titulo, descricao, tags, thumbnail_path=None):
    """Faz upload para YouTube"""
    try:
        creds_dict = json.loads(YOUTUBE_CREDENTIALS)
        credentials = Credentials.from_authorized_user_info(creds_dict)
        youtube = build('youtube', 'v3', credentials=credentials)

        body = {
            'snippet': {
                'title': titulo,
                'description': descricao,
                'tags': tags,
                'categoryId': '1'  # Film & Animation — troque para '27' (Education) se preferir
            },
            'status': {
                'privacyStatus': 'public',
                # ⚠️ DECISÃO IMPORTANTE (não é só estética): como este canal é de
                # histórias bíblicas para crianças, o YouTube/COPPA provavelmente
                # espera "made for kids" = True. Isso desativa comentários,
                # anúncios personalizados e alguns recursos (ex.: notificações,
                # cards). Mantive False aqui só para você decidir consciente —
                # avalie o público real do canal antes de trocar.
                'selfDeclaredMadeForKids': False
            }
        }

        media = MediaFileUpload(video_path, resumable=True)
        request = youtube.videos().insert(
            part='snippet,status',
            body=body,
            media_body=media
        )

        response = request.execute()
        video_id = response['id']

        if thumbnail_path and os.path.exists(thumbnail_path):
            print("📤 Fazendo upload da thumbnail...")
            try:
                youtube.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(thumbnail_path)
                ).execute()
                print("✅ Thumbnail configurada!")
            except Exception as e:
                print(f"❌ Erro thumbnail: {e}")

        return video_id

    except Exception as e:
        print(f"❌ Erro upload: {e}")
        raise


def main():
    print(f"{'📱' if VIDEO_TYPE == 'short' else '🎬'} Iniciando...")

    os.makedirs(VIDEOS_DIR, exist_ok=True)
    os.makedirs(ASSETS_DIR, exist_ok=True)

    # Escolher história bíblica do episódio
    historia = escolher_historia_biblica()
    info_titulo = gerar_titulo_infantil(historia)
    titulo_video = info_titulo['titulo']
    licao = info_titulo.get('licao', '')

    print(f"🎯 Título: {titulo_video}")
    if licao:
        print(f"💡 Lição: {licao}")

    # Gerar roteiro
    print("✍️ Gerando roteiro...")
    roteiro = gerar_roteiro(VIDEO_TYPE, historia, licao)

    # Criar áudio (Fish Audio -> fallback Edge TTS)
    audio_path = f'{ASSETS_DIR}/audio.mp3'
    criar_audio(roteiro, audio_path)

    audio_clip = AudioFileClip(audio_path)
    duracao = audio_clip.duration
    audio_clip.close()
    print(f"⏱️ {duracao:.1f}s")

    # Segmentar via Whisper + gerar imagens por IA
    midias_sincronizadas = gerar_midias_sincronizadas_ia(roteiro, audio_path, titulo_video)

    if not midias_sincronizadas:
        print("❌ Não foi possível gerar mídias — abortando este ciclo.")
        return

    # Definir video_path
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    video_path = f'{VIDEOS_DIR}/{VIDEO_TYPE}_{timestamp}.mp4'
    print(f"📹 Arquivo: {video_path}")

    # Montar vídeo
    print("🎥 Montando vídeo...")
    try:
        if VIDEO_TYPE == 'short':
            resultado = criar_video_short_sem_legendas(
                audio_path, midias_sincronizadas, video_path, duracao)
        else:
            resultado = criar_video_long_sem_legendas(
                audio_path, midias_sincronizadas, video_path, duracao)

        if not resultado:
            print("❌ Erro ao criar vídeo")
            return
        print("✅ Vídeo criado!")

    except Exception as e:
        print(f"❌ Erro: {e}")
        import traceback
        traceback.print_exc()
        return

    # Preparar metadados
    titulo_completo = titulo_video
    titulo = titulo_video[:60] if len(titulo_video) <= 60 else titulo_video[:57] + '...'
    if VIDEO_TYPE == 'short':
        titulo += ' #shorts'

    descricao = roteiro[:300] + '...\n\n🔔 Inscreva-se para mais histórias bíblicas!\n#' + ('shorts' if VIDEO_TYPE == 'short' else 'video')
    tags = config.get('tags_padrao', ['historias biblicas', 'biblia infantil', 'desenho biblico', 'para criancas'])
    if VIDEO_TYPE == 'short':
        tags.append('shorts')

    _salvar_historia_usada(historia)

    # Thumbnail (via curadoria Telegram, se ativada)
    thumbnail_path = None
    if USAR_CURACAO:
        print("\n" + "=" * 60)
        print("🖼️ VERIFICANDO THUMBNAIL")
        print("=" * 60)
        thumbnail_custom = f'{ASSETS_DIR}/thumbnail_custom.jpg'
        if os.path.exists(thumbnail_custom):
            print("✅ Thumbnail já recebida")
            thumbnail_path = thumbnail_custom
        else:
            try:
                curator = TelegramCuratorNoticias()
                thumbnail_path = curator.solicitar_thumbnail(titulo, timeout=1200)
                if thumbnail_path:
                    print(f"✅ Thumbnail: {thumbnail_path}")
                else:
                    print("⚠️ Thumbnail automática")
            except Exception as e:
                print(f"⚠️ Erro: {e}")

    # Upload YouTube
    print("\n📤 Upload YouTube...")
    try:
        video_id = fazer_upload_youtube(
            video_path, titulo, descricao, tags, thumbnail_path)

        url = f'https://youtube.com/{"shorts/" if VIDEO_TYPE == "short" else "watch?v="}{video_id}'
        print(f"✅ Publicado!\n🔗 {url}")

        # Log
        log_entry = {
            'data': datetime.now().isoformat(),
            'tipo': VIDEO_TYPE,
            'historia': historia,
            'titulo': titulo,
            'duracao': duracao,
            'video_id': video_id,
            'url': url,
            'com_legendas': False,
            'com_thumbnail_custom': thumbnail_path is not None
        }
        log_file = 'videos_gerados.json'
        logs = []
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                logs = json.load(f)
        logs.append(log_entry)
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(logs, f, indent=2, ensure_ascii=False)

        # Envio para bot pessoal (curadoria / cópia do vídeo publicado)
        if USAR_CURACAO:
            print("\n" + "=" * 60)
            print("📱 ENVIANDO PARA TELEGRAM (bot pessoal)")
            print("=" * 60)
            try:
                curator = TelegramCuratorNoticias()
                tamanho_mb = os.path.getsize(video_path) / (1024 * 1024)
                print(f"   📦 Tamanho: {tamanho_mb:.2f} MB")

                if tamanho_mb <= 50:
                    print("   📤 Enviando arquivo direto...")
                    sucesso = curator.enviar_video_publicado(
                        video_path=video_path,
                        titulo=titulo,
                        descricao=descricao,
                        tags=tags,
                        url_youtube=url
                    )
                    print("✅ Enviado!" if sucesso else "⚠️ Falha ao enviar")
                else:
                    print("   📦 Vídeo > 50 MB - criando release no GitHub...")
                    from create_release import criar_release_com_video
                    release_info = criar_release_com_video(
                        video_path=video_path,
                        titulo=titulo,
                        descricao=descricao
                    )
                    if release_info:
                        download_url = release_info['download_url']
                        tag_name = release_info['tag_name']
                        print(f"   ✅ Release criada! 🔗 {download_url}")
                        curator.enviar_link_download(
                            download_url=download_url,
                            titulo=titulo,
                            descricao=descricao,
                            tags=tags,
                            url_youtube=url,
                            duracao=duracao,
                            tamanho_mb=tamanho_mb,
                            tag_name=tag_name
                        )
                        print("💡 Baixe o vídeo pelo link acima quando quiser")
                    else:
                        print("❌ Erro ao criar release")
                        curator.enviar_mensagem(
                            f"⚠️ <b>Vídeo muito grande ({tamanho_mb:.2f} MB)</b>\n\n"
                            f"📺 {titulo}\n🔗 YouTube: {url}\n\n"
                            f"📁 Disponível nos GitHub Actions Artifacts por 7 dias"
                        )
            except Exception as e:
                print(f"⚠️ Erro ao enviar para bot pessoal: {e}")
                import traceback
                traceback.print_exc()

    except Exception as e:
        print(f"❌ Erro no upload YouTube: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)
    print("✅ WORKFLOW CONCLUÍDO")
    print("=" * 60)


if __name__ == '__main__':
    main()
