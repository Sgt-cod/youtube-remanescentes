"""
compilar_shorts.py — Vídeo Longo Semanal
-----------------------------------------
Toda segunda-feira gera um vídeo longo original buscando
notícias diretamente dos feeds RSS (igual aos shorts).
Não depende do videos_gerados.json.
"""

import os, json, random, time, glob, re, asyncio
from datetime import datetime
from pathlib import Path

import requests
import feedparser
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google import generativeai as genai

# ── Secrets ───────────────────────────────────────────────────────────────
GEMINI_API_KEY       = os.environ.get('GEMINI_API_KEY', '')
YOUTUBE_CREDENTIALS  = os.environ.get('YOUTUBE_CREDENTIALS', '')
TELEGRAM_BOT_TOKEN   = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID     = os.environ.get('TELEGRAM_CHAT_ID', '')
TELEGRAM_CANAL_ID    = os.environ.get('TELEGRAM_CANAL_ID', '')
BLOGGER_BLOG_ID      = os.environ.get('BLOGGER_BLOG_ID', '')
BLOGGER_CREDENTIALS  = os.environ.get('BLOGGER_CREDENTIALS', '')
CANAL_YOUTUBE_URL    = os.environ.get('CANAL_YOUTUBE_URL', '')

VIDEOS_DIR  = 'videos'
ASSETS_DIR  = 'assets'
LOG_FILE    = 'videos_gerados.json'

# Lê config.json para pegar os feeds RSS
def _carregar_config():
    for nome in ['config.json', 'config_noticias.json']:
        if os.path.exists(nome):
            with open(nome, encoding='utf-8') as f:
                return json.load(f)
    return {}

config = _carregar_config()

# ════════════════════════════════════════════════════════════════════════════
# 1. GEMINI
# ════════════════════════════════════════════════════════════════════════════

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash-lite')

# ════════════════════════════════════════════════════════════════════════════
# 2. BUSCAR NOTÍCIAS (mesmo mecanismo dos shorts)
# ════════════════════════════════════════════════════════════════════════════

def buscar_noticias_semana(quantidade=7) -> list[dict]:
    """Busca notícias dos feeds RSS — igual ao generate_video.py."""
    feeds = config.get('rss_feeds', [])
    if not feeds:
        print("  ⚠️ Nenhum feed RSS configurado")
        return []

    todas = []
    vistos = set()
    print(f"🔍 Buscando notícias de {len(feeds)} feeds...")

    for feed_url in feeds[:3]:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:10]:
                titulo = entry.title.strip()
                chave = titulo.lower().strip('.,!?;: ')
                if chave not in vistos:
                    todas.append({
                        'titulo': titulo,
                        'resumo': entry.get('summary', titulo),
                        'link': entry.link
                    })
                    vistos.add(chave)
        except Exception as e:
            print(f"  ❌ Erro feed: {e}")

    random.shuffle(todas)
    selecionadas = todas[:quantidade]
    print(f"  ✅ {len(selecionadas)} notícias selecionadas")
    for n in selecionadas:
        print(f"     • {n['titulo'][:65]}")
    return selecionadas


# ════════════════════════════════════════════════════════════════════════════
# 3. GEMINI — gerar roteiro longo + metadados
# ════════════════════════════════════════════════════════════════════════════

def gerar_roteiro_e_metadados(noticias: list[dict]) -> dict:
    print("\n✍️ Gerando roteiro semanal com Gemini...")

    lista = '\n'.join(
        f"- {n['titulo']}: {n['resumo'][:150]}" for n in noticias
    )
    semana_str = datetime.now().strftime('%d/%m/%Y')

    prompt = f"""Você é um jornalista político brasileiro do canal "Canal 55 Notícias".

As principais notícias desta semana são:
{lista}

Crie um ROTEIRO COMPLETO para um vídeo de análise semanal (5 a 7 minutos).

Regras do roteiro:
- Introdução apresentando os principais temas da semana
- Um parágrafo aprofundado para cada notícia
- Linguagem jornalística clara, direta e imparcial
- Conclusão sobre o cenário político da semana
- SEM markdown, bullets ou formatação — apenas texto corrido para narração
- Aproximadamente 900 a 1200 palavras

Retorne APENAS JSON válido (sem markdown):
{{
  "titulo": "título atraente até 80 chars com emojis",
  "roteiro": "texto completo do roteiro",
  "descricao": "descrição YouTube de 300-500 chars com hashtags",
  "tags": ["politica", "brasil", "noticias", "resumo", "semanal", "canal55"]
}}"""

    try:
        response = model.generate_content(prompt)
        texto = response.text.strip().replace('```json','').replace('```','').strip()
        inicio = texto.find('{')
        fim = texto.rfind('}') + 1
        dados = json.loads(texto[inicio:fim])
        print(f"  ✅ Roteiro: {len(dados['roteiro'].split())} palavras")
        print(f"  📺 Título: {dados['titulo']}")
        return dados
    except Exception as e:
        print(f"  ⚠️ Gemini falhou: {e} — usando fallback")
        titulos = '. '.join(n['titulo'] for n in noticias[:3])
        semana = datetime.now().strftime('%d/%m')
        return {
            'titulo': f'📰 Análise Política Semanal — {semana}',
            'roteiro': f"Esta semana a política brasileira foi marcada por importantes acontecimentos. {titulos}. Acompanhe o Canal 55 Notícias para não perder nenhuma atualização.",
            'descricao': f'Análise dos principais acontecimentos políticos da semana. #política #brasil #noticias #canal55',
            'tags': ['política', 'brasil', 'noticias', 'resumo', 'semanal', 'canal55']
        }


# ════════════════════════════════════════════════════════════════════════════
# 4. ÁUDIO — Edge TTS (mesma voz dos shorts)
# ════════════════════════════════════════════════════════════════════════════

def criar_audio(roteiro: str, output_path: str) -> bool:
    print("\n🎙️ Gerando áudio...")
    import edge_tts

    voz = config.get('voz', 'pt-BR-AntonioNeural')

    async def _gerar():
        communicate = edge_tts.Communicate(roteiro, voz, rate="+0%")
        await communicate.save(output_path)

    try:
        asyncio.run(_gerar())
        tamanho = os.path.getsize(output_path) / 1024
        print(f"  ✅ Áudio: {tamanho:.0f} KB")
        return True
    except Exception as e:
        print(f"  ❌ Erro TTS: {e}")
        return False


# ════════════════════════════════════════════════════════════════════════════
# 5. VÍDEO — pillarbox com blur para imagens 9:16
# ════════════════════════════════════════════════════════════════════════════

# Substitua a função montar_video() inteira no compilar_shorts.py

def montar_video(audio_path: str, output_path: str) -> bool:
    print("\n🎬 Montando vídeo longo...")
    try:
        from moviepy import AudioFileClip, ImageClip, CompositeVideoClip
        from PIL import Image, ImageFilter
        import numpy as np
        import itertools

        W, H = 1920, 1080

        audio = AudioFileClip(audio_path)
        duracao = audio.duration
        print(f"  ⏱️ Duração: {duracao:.1f}s ({duracao/60:.1f}min)")

        # Buscar imagens
        imagens = (
            glob.glob(f'{ASSETS_DIR}/politicos/**/*.jpg', recursive=True) +
            glob.glob(f'{ASSETS_DIR}/politicos/**/*.png', recursive=True) +
            glob.glob(f'{ASSETS_DIR}/instituicoes/**/*.jpg', recursive=True) +
            glob.glob(f'{ASSETS_DIR}/instituicoes/**/*.png', recursive=True) +
            glob.glob(f'{ASSETS_DIR}/genericas/*.jpg') +
            glob.glob(f'{ASSETS_DIR}/genericas/*.png')
        )

        if not imagens:
            print("  ⚠️ Sem imagens — usando fundo sólido")
            frame = np.full((H, W, 3), (15, 15, 30), dtype=np.uint8)
            clip  = ImageClip(frame, duration=duracao)
            video = clip.with_audio(audio)
        else:
            random.shuffle(imagens)
            duracao_por_img = 6.0
            clips  = []
            tempo  = 0.0

            def pillarbox_array(img_path: str) -> np.ndarray:
                """Retorna array numpy 1920x1080 com pillarbox+blur."""
                img = Image.open(img_path).convert('RGB')
                iw, ih = img.size

                # Fundo desfocado 1920x1080
                ratio = W / H
                if iw / ih > ratio:
                    bg = img.resize((W, int(W * ih / iw)), Image.LANCZOS)
                else:
                    bg = img.resize((int(H * iw / ih), H), Image.LANCZOS)
                bw, bh = bg.size
                left = max(0, (bw - W) // 2)
                top  = max(0, (bh - H) // 2)
                bg   = bg.crop((left, top, left + W, top + H))
                if bg.size != (W, H):
                    bg = bg.resize((W, H), Image.LANCZOS)
                bg = bg.filter(ImageFilter.GaussianBlur(radius=25))

                # Frente centralizada
                scale = min(W / iw, H / ih)
                fw = int(iw * scale)
                fh = int(ih * scale)
                front = img.resize((fw, fh), Image.LANCZOS)
                x = (W - fw) // 2
                y = (H - fh) // 2
                bg.paste(front, (x, y))
                return np.array(bg)

            for img_path in itertools.cycle(imagens):
                if tempo >= duracao:
                    break
                dur = min(duracao_por_img, duracao - tempo)
                try:
                    frame = pillarbox_array(img_path)
                    clip  = ImageClip(frame, duration=dur).with_start(tempo)
                    clips.append(clip)
                    tempo += dur
                except Exception as e:
                    print(f"  ⚠️ Erro imagem: {e}")
                    continue

            if not clips:
                print("  ❌ Nenhum clip criado")
                return False

            video_base = CompositeVideoClip(clips, size=(W, H))
            video_base = video_base.with_duration(duracao)
            video      = video_base.with_audio(audio)

        os.makedirs(VIDEOS_DIR, exist_ok=True)
        print("  💾 Renderizando...")
        video.write_videofile(
            output_path,
            fps=24,
            codec='libx264',
            audio_codec='aac',
            preset='fast',
            bitrate='4000k',
            threads=4,
            logger=None
        )
        tamanho_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"  ✅ Vídeo: {output_path} ({tamanho_mb:.1f} MB)")
        return True

    except Exception as e:
        print(f"  ❌ Erro ao montar vídeo: {e}")
        import traceback; traceback.print_exc()
        return False


# ════════════════════════════════════════════════════════════════════════════
# 6. YOUTUBE — publicar
# ════════════════════════════════════════════════════════════════════════════

def publicar_youtube(video_path: str, metadados: dict) -> str | None:
    print("\n📤 Publicando no YouTube...")
    try:
        creds = Credentials.from_authorized_user_info(json.loads(YOUTUBE_CREDENTIALS))
        yt = build('youtube', 'v3', credentials=creds)
        body = {
            'snippet': {
                'title':       metadados['titulo'][:100],
                'description': metadados['descricao'],
                'tags':        metadados['tags'],
                'categoryId':  '27'
            },
            'status': {
                'privacyStatus':           'public',
                'selfDeclaredMadeForKids':  False
            }
        }
        media = MediaFileUpload(video_path, resumable=True)
        resp  = yt.videos().insert(
            part='snippet,status', body=body, media_body=media
        ).execute()
        url = f"https://www.youtube.com/watch?v={resp['id']}"
        print(f"  ✅ Publicado: {url}")
        return url
    except Exception as e:
        print(f"  ❌ Erro YouTube: {e}")
        return None


# ════════════════════════════════════════════════════════════════════════════
# 7. DISTRIBUIÇÃO
# ════════════════════════════════════════════════════════════════════════════

def _tg(chat_id, texto):
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={'chat_id': chat_id, 'text': texto,
                  'parse_mode': 'HTML', 'disable_web_page_preview': False},
            timeout=15
        )
    except Exception:
        pass

def distribuir(titulo, roteiro, url_yt, tags):
    print("\n📣 Distribuindo...")
    _tg(TELEGRAM_CHAT_ID,
        f"🎬 <b>ANÁLISE SEMANAL PUBLICADA</b>\n\n{titulo}\n\n🔗 {url_yt}")
    time.sleep(2)
    if TELEGRAM_CANAL_ID:
        _tg(TELEGRAM_CANAL_ID,
            f"📰 <b>{titulo}</b>\n\n"
            f"{roteiro[:600]}...\n\n"
            f"▶️ Assista completo:\n{url_yt}\n\n"
            f"🔔 Inscreva-se!\n"
            f"{'📺 ' + CANAL_YOUTUBE_URL if CANAL_YOUTUBE_URL else ''}")
    time.sleep(2)
    if BLOGGER_BLOG_ID and BLOGGER_CREDENTIALS:
        try:
            from distribuidor import publicar_blogger
            publicar_blogger(titulo=titulo, roteiro=roteiro,
                             url_youtube=url_yt, tags=tags)
        except Exception as e:
            print(f"  ⚠️ Blogger: {e}")


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════

def main():
    print("🎬 ANÁLISE SEMANAL — Canal 55 Notícias")
    print("=" * 60)
    os.makedirs(VIDEOS_DIR, exist_ok=True)

    # 1. Notícias
    noticias = buscar_noticias_semana(quantidade=7)
    if len(noticias) < 3:
        print(f"\n⚠️ Apenas {len(noticias)} notícias encontradas. Abortando.")
        _tg(TELEGRAM_CHAT_ID, "⚠️ Análise semanal cancelada: sem notícias suficientes.")
        return

    # 2. Roteiro
    metadados = gerar_roteiro_e_metadados(noticias)

    # 3. Áudio
    audio_path = f'{ASSETS_DIR}/audio_semanal.mp3'
    if not criar_audio(metadados['roteiro'], audio_path):
        print("❌ Falha no áudio. Abortando.")
        return

    # 4. Vídeo
    timestamp  = datetime.now().strftime('%Y%m%d_%H%M%S')
    video_path = f'{VIDEOS_DIR}/semanal_{timestamp}.mp4'
    if not montar_video(audio_path, video_path):
        print("❌ Falha no vídeo. Abortando.")
        return

    # 5. YouTube
    url_yt = publicar_youtube(video_path, metadados)
    if not url_yt:
        print("❌ Falha no upload. Abortando.")
        return

    # 6. Distribuir
    distribuir(metadados['titulo'], metadados['roteiro'], url_yt, metadados['tags'])

    # 7. Log
    logs = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, encoding='utf-8') as f:
                logs = json.load(f)
        except Exception:
            logs = []
    logs.append({
        'data':    datetime.now().isoformat(),
        'tipo':    'semanal',
        'titulo':  metadados['titulo'],
        'url':     url_yt,
        'noticias': [n['titulo'] for n in noticias]
    })
    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print("✅ ANÁLISE SEMANAL CONCLUÍDA!")
    print(f"🔗 {url_yt}")
    print("=" * 60)


if __name__ == '__main__':
    main()
