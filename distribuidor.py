"""
distribuidor.py
---------------
Distribui o vídeo publicado no YouTube para:
  1. Canal Telegram público (com thumbnail Canal 55)
  2. Blogger (com thumbnail Canal 55 embutida)
  3. Twitter/X (texto + link, plano free)
  4. Instagram (Reels via instagrapi)

Secrets necessários no GitHub:
  TELEGRAM_BOT_TOKEN          → token do bot
  TELEGRAM_CANAL_ID           → @username ou ID do canal público
  BLOGGER_BLOG_ID             → ID numérico do blog
  BLOGGER_CREDENTIALS         → JSON OAuth2 do Blogger
  TWITTER_API_KEY             → API Key do app no developer.x.com
  TWITTER_API_SECRET          → API Secret
  TWITTER_ACCESS_TOKEN        → Access Token (permissão Read+Write)
  TWITTER_ACCESS_TOKEN_SECRET → Access Token Secret
  INSTAGRAM_USERNAME          → usuário do Instagram
  INSTAGRAM_PASSWORD          → senha do Instagram
  CANAL_YOUTUBE_URL           → https://youtube.com/@canal55noticias
  KOFI_URL                    → https://ko-fi.com/canal55
  KIRVANO_URL                 → link da página de apoio na Kirvano
"""

import os
import re
import json
import time
import base64
import textwrap
import traceback
import requests
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

# ── Secrets ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN          = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CANAL_ID           = os.environ.get('TELEGRAM_CANAL_ID', '')
BLOGGER_BLOG_ID             = os.environ.get('BLOGGER_BLOG_ID', '')
BLOGGER_CREDENTIALS         = os.environ.get('BLOGGER_CREDENTIALS', '')
TWITTER_API_KEY             = os.environ.get('TWITTER_API_KEY', '')
TWITTER_API_SECRET          = os.environ.get('TWITTER_API_SECRET', '')
TWITTER_ACCESS_TOKEN        = os.environ.get('TWITTER_ACCESS_TOKEN', '')
TWITTER_ACCESS_TOKEN_SECRET = os.environ.get('TWITTER_ACCESS_TOKEN_SECRET', '')
INSTAGRAM_USERNAME          = os.environ.get('INSTAGRAM_USERNAME', '')
INSTAGRAM_PASSWORD          = os.environ.get('INSTAGRAM_PASSWORD', '')
INSTAGRAM_SESSION           = os.environ.get('INSTAGRAM_SESSION', '')
CANAL_YOUTUBE_URL           = os.environ.get('CANAL_YOUTUBE_URL', '')
KOFI_URL                    = os.environ.get('KOFI_URL', '')
KIRVANO_URL                 = os.environ.get('KIRVANO_URL', '')

LOGO_PATH = 'logo_canal55.png'


# ════════════════════════════════════════════════════════════════════════════
# UTILITÁRIOS
# ════════════════════════════════════════════════════════════════════════════

def _limpar_titulo(titulo: str) -> str:
    """Remove #shorts e variações do título para exibição externa."""
    titulo = re.sub(r'\s*#shorts?\s*$', '', titulo, flags=re.IGNORECASE)
    titulo = re.sub(r'\s*#short\s*$',  '', titulo, flags=re.IGNORECASE)
    return titulo.strip()


def _apoio_texto() -> str:
    """Retorna linha de apoio para texto simples (Telegram, Twitter)."""
    linha = ''
    if KIRVANO_URL:
        linha += f'\n☕ Apoie: {KIRVANO_URL}'
    if KOFI_URL:
        linha += f'\n💙 Ko-fi: {KOFI_URL}'
    return linha


def obter_primeira_midia_match(midias_sincronizadas: list) -> str | None:
    """
    Retorna a primeira foto com match real (não genérica).
    Fallback: última foto genérica disponível.
    """
    if not midias_sincronizadas:
        return None
    generica = None
    for item in midias_sincronizadas:
        midia = item.get('midia')
        if not midia:
            continue
        caminho, tipo = midia
        if not caminho or not os.path.exists(caminho):
            continue
        if tipo == 'video_local':
            continue
        if 'genericas' in caminho:
            generica = caminho
        else:
            return caminho
    return generica


# ════════════════════════════════════════════════════════════════════════════
# Substitua a função gerar_thumbnail() inteira no distribuidor.py
# Correções:
#   - Título sempre completo (fonte reduz até caber)
#   - Logo e "LEIA NA LEGENDA" calculados de baixo para cima (sem sobreposição)
# ════════════════════════════════════════════════════════════════════════════

def gerar_thumbnail(titulo: str, fundo_path: str | None = None,
                    output_path: str = '/tmp/thumbnail_canal55.jpg',
                    tamanho: tuple = (1080, 1080)) -> str | None:
    try:
        import textwrap
        from PIL import Image, ImageDraw, ImageFont

        W, H = tamanho
        titulo_limpo = titulo.replace(' #shorts', '').replace('#shorts', '').strip()

        # ── Fundo ─────────────────────────────────────────────────────────
        if fundo_path and os.path.exists(fundo_path):
            try:
                img = Image.open(fundo_path).convert('RGB')
                ratio = W / H
                iw, ih = img.size
                if iw / ih > ratio:
                    new_w = int(ih * ratio)
                    img = img.crop(((iw - new_w) // 2, 0, (iw + new_w) // 2, ih))
                else:
                    new_h = int(iw / ratio)
                    img = img.crop((0, (ih - new_h) // 2, iw, (ih + new_h) // 2))
                img = img.resize((W, H), Image.LANCZOS)
                overlay = Image.new('RGBA', (W, H), (0, 0, 0, 130))
                img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
            except Exception:
                img = Image.new('RGB', (W, H), (15, 15, 30))
        else:
            img = Image.new('RGB', (W, H), (15, 15, 30))

        draw = ImageDraw.Draw(img)

        def font(size, bold=True):
            nome = 'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'
            for base in ['/usr/share/fonts/truetype/dejavu/',
                         '/usr/share/fonts/dejavu/']:
                try:
                    return ImageFont.truetype(base + nome, size)
                except Exception:
                    continue
            return ImageFont.load_default()

        # ── Faixa vermelha no topo ─────────────────────────────────────────
        FAIXA_H = 95
        draw.rectangle([(0, 0), (W, FAIXA_H)], fill='#cc0000')
        f_faixa = font(50)
        canal_txt = 'CANAL 55 NOTÍCIAS'
        bb = draw.textbbox((0, 0), canal_txt, font=f_faixa)
        draw.text(((W - (bb[2]-bb[0])) // 2, (FAIXA_H - (bb[3]-bb[1])) // 2),
                  canal_txt, font=f_faixa, fill='white')

        # ── Zona inferior — calculada de baixo para cima ───────────────────
        MARGEM_BASE = 15
        MARGEM_LAT  = 60

        # "LEIA NA LEGENDA"
        f_leia  = font(36)
        txt_leia = '👇 LEIA NA LEGENDA'
        bb_leia  = draw.textbbox((0, 0), txt_leia, font=f_leia)
        LEIA_H   = bb_leia[3] - bb_leia[1]

        leia_y = H - MARGEM_BASE - LEIA_H          # y do texto
        logo_y = leia_y - 10 - 180                  # logo 180px acima do texto
        linha_y = logo_y - 12                        # linha vermelha acima da logo

        # ── Área disponível para o título ──────────────────────────────────
        area_w   = W - MARGEM_LAT * 2
        area_y_ini = FAIXA_H + 30
        area_y_fim = linha_y - 20
        area_h   = area_y_fim - area_y_ini

        # Ajusta fonte até título caber COMPLETO
        font_size = 84
        f_titulo  = None
        linhas    = []
        while font_size >= 28:
            f_titulo = font(font_size)
            chars    = max(8, int(area_w / (font_size * 0.56)))
            linhas   = textwrap.wrap(titulo_limpo, width=chars)
            line_h   = font_size + 16
            if len(linhas) * line_h <= area_h:
                break
            font_size -= 3

        # Centraliza verticalmente
        line_h  = font_size + 16
        total_h = len(linhas) * line_h
        y = area_y_ini + (area_h - total_h) // 2

        for linha in linhas:
            bb = draw.textbbox((0, 0), linha, font=f_titulo)
            lw = bb[2] - bb[0]
            x  = (W - lw) // 2
            draw.text((x + 3, y + 3), linha, font=f_titulo, fill=(0, 0, 0, 200))
            draw.text((x, y),         linha, font=f_titulo, fill='white')
            y += line_h

        # ── Linha vermelha decorativa ──────────────────────────────────────
        draw.rectangle([(MARGEM_LAT, linha_y), (W - MARGEM_LAT, linha_y + 5)],
                       fill='#cc0000')

        # ── Logo Canal 55 ──────────────────────────────────────────────────
        for lp in ['logo_canal55.png', 'assets/logo_canal55.png']:
            if os.path.exists(lp):
                try:
                    LOGO_H = 180
                    logo   = Image.open(lp).convert('RGBA')
                    logo_w = int(logo.width * LOGO_H / logo.height)
                    logo   = logo.resize((logo_w, LOGO_H), Image.LANCZOS)
                    img.paste(logo, ((W - logo_w) // 2, logo_y), logo)
                    break
                except Exception:
                    pass

        # ── "LEIA NA LEGENDA" abaixo da logo ──────────────────────────────
        bb   = draw.textbbox((0, 0), txt_leia, font=f_leia)
        lw   = bb[2] - bb[0]
        draw.text(((W - lw) // 2 + 2, leia_y + 2), txt_leia,
                  font=f_leia, fill=(0, 0, 0, 180))
        draw.text(((W - lw) // 2,     leia_y),     txt_leia,
                  font=f_leia, fill='white')

        img.save(output_path, 'JPEG', quality=95)
        print(f"  ✅ Thumbnail: {output_path} | fonte {font_size}px | {len(linhas)} linhas")
        return output_path

    except Exception as e:
        print(f"  ❌ Erro ao gerar thumbnail: {e}")
        import traceback
        traceback.print_exc()
        return None


# ════════════════════════════════════════════════════════════════════════════
# TELEGRAM — Canal público
# ════════════════════════════════════════════════════════════════════════════

def publicar_telegram_canal(titulo: str, roteiro: str, url_youtube: str,
                             thumbnail_path: str | None = None) -> bool:
    if not TELEGRAM_CANAL_ID:
        print("  ⚠️ TELEGRAM_CANAL_ID não configurado — pulando canal")
        return False
 
    print("\n📣 Publicando no canal Telegram...")
 
    try:
        base_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
 
        # Legenda completa — igual ao Blogger
        apoio = _apoio_texto()
        legenda = (
            f"📰 <b>{titulo}</b>\n\n"
            f"{roteiro}\n\n"
            f"▶️ <b>Assista agora:</b>\n"
            f"{url_youtube}\n"
            f"{'📺 ' + CANAL_YOUTUBE_URL if CANAL_YOUTUBE_URL else ''}\n\n"
            f"🔔 Inscreva-se e ative o sininho!\n"
            f"{apoio}"
        )
 
        # Telegram limita legenda de foto a 1024 chars — se passar, envia foto + texto separado
        if thumbnail_path and os.path.exists(thumbnail_path):
            if len(legenda) <= 1024:
                # Tudo junto
                with open(thumbnail_path, 'rb') as f:
                    r = requests.post(
                        f"{base_url}/sendPhoto",
                        data={'chat_id': TELEGRAM_CANAL_ID,
                              'caption': legenda,
                              'parse_mode': 'HTML'},
                        files={'photo': f},
                        timeout=30
                    )
                ok = r.json().get('ok', False)
            else:
                # Foto primeiro, depois texto completo
                with open(thumbnail_path, 'rb') as f:
                    r = requests.post(
                        f"{base_url}/sendPhoto",
                        data={'chat_id': TELEGRAM_CANAL_ID,
                              'caption': f"📰 <b>{titulo}</b>",
                              'parse_mode': 'HTML'},
                        files={'photo': f},
                        timeout=30
                    )
 
                # Texto completo em mensagem separada
                requests.post(
                    f"{base_url}/sendMessage",
                    json={'chat_id': TELEGRAM_CANAL_ID,
                          'text': legenda,
                          'parse_mode': 'HTML',
                          'disable_web_page_preview': True},
                    timeout=15
                )
                ok = r.json().get('ok', False)
        else:
            # Sem imagem — só texto
            r = requests.post(
                f"{base_url}/sendMessage",
                json={'chat_id': TELEGRAM_CANAL_ID,
                      'text': legenda,
                      'parse_mode': 'HTML',
                      'disable_web_page_preview': True},
                timeout=15
            )
            ok = r.json().get('ok', False)
 
        if ok:
            print("  ✅ Publicado com roteiro completo!")
        else:
            print(f"  ❌ Falhou: {r.json()}")
        return ok
 
    except Exception as e:
        print(f"  ❌ Erro Telegram canal: {e}")
        return False


# ════════════════════════════════════════════════════════════════════════════
# BLOGGER
# ════════════════════════════════════════════════════════════════════════════

def _blogger_service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_info(json.loads(BLOGGER_CREDENTIALS))
    return build('blogger', 'v3', credentials=creds)


def _upload_thumb_github(thumbnail_path: str) -> str | None:
    """
    Faz upload da thumbnail para o repositório GitHub (pasta thumbs/).
    Retorna URL pública raw.githubusercontent.com ou None se falhar.

    Secrets necessários:
      GITHUB_TOKEN → token com permissão de repo (já existe no workflow como GITHUB_TOKEN)
      GITHUB_REPO  → ex: Sgt-cod/youtube-automation-news
    """
    GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
    GITHUB_REPO  = os.environ.get('GITHUB_REPO', '')

    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("  ⚠️ GITHUB_TOKEN ou GITHUB_REPO não configurado")
        return None

    try:
        import base64
        from datetime import datetime

        nome_arquivo = f"thumb_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        caminho_repo = f"thumbs/{nome_arquivo}"

        with open(thumbnail_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode()

        r = requests.put(
            f"https://api.github.com/repos/{GITHUB_REPO}/contents/{caminho_repo}",
            headers={
                'Authorization': f'token {GITHUB_TOKEN}',
                'Accept': 'application/vnd.github.v3+json'
            },
            json={
                'message': f'thumb: {nome_arquivo}',
                'content': b64
            },
            timeout=30
        )

        if r.status_code in (200, 201):
            url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{caminho_repo}"
            print(f"  🖼️ Thumbnail no GitHub: {url}")
            return url
        else:
            print(f"  ⚠️ GitHub upload falhou: {r.status_code} {r.text[:200]}")
            return None

    except Exception as e:
        print(f"  ⚠️ Erro upload GitHub: {e}")
        return None


def publicar_blogger(titulo: str, roteiro: str, url_youtube: str,
                     tags: list, thumbnail_path: str | None = None) -> str | None:
    if not BLOGGER_BLOG_ID or not BLOGGER_CREDENTIALS:
        print("  ⚠️ Blogger não configurado — pulando")
        return None

    print("\n📝 Publicando no Blogger...")

    try:
        import base64, traceback
        from datetime import datetime

        # ── Thumbnail: URL pública via GitHub ────────────────────────────────
        thumb_html = ''
        if thumbnail_path and os.path.exists(thumbnail_path):
            thumb_url = _upload_thumb_github(thumbnail_path)

            if thumb_url:
                # URL pública — Blogger extrai como miniatura do post ✅
                thumb_html = (
                    f'<div style="text-align:center;margin-bottom:24px">'
                    f'<img src="{thumb_url}" alt="{titulo}" '
                    f'style="max-width:100%;border-radius:10px;'
                    f'box-shadow:0 4px 16px rgba(0,0,0,.25)"></div>'
                )
            else:
                # Fallback base64 (imagem aparece no artigo mas não na listagem)
                with open(thumbnail_path, 'rb') as f:
                    b64 = base64.b64encode(f.read()).decode()
                thumb_html = (
                    f'<div style="text-align:center;margin-bottom:24px">'
                    f'<img src="data:image/jpeg;base64,{b64}" alt="{titulo}" '
                    f'style="max-width:100%;border-radius:10px;'
                    f'box-shadow:0 4px 16px rgba(0,0,0,.25)"></div>'
                )

        # Botão assistir no YouTube
        assistir_btn = (
            f'<div style="text-align:center;margin:24px 0">'
            f'<a href="{url_youtube}" target="_blank" style="'
            f'background:#ff0000;color:#fff;padding:14px 32px;'
            f'border-radius:8px;text-decoration:none;font-weight:bold;'
            f'font-size:16px;display:inline-block">'
            f'▶ Assistir no YouTube</a></div>'
        )

        tags_html = ' '.join([
            f'<span style="background:#cc0000;color:#fff;padding:3px 9px;'
            f'border-radius:12px;font-size:13px;margin:2px;'
            f'display:inline-block">#{t}</span>' for t in tags
        ])

        paragrafos = '\n'.join(
            f'<p style="line-height:1.75;margin:0 0 16px;font-size:16px">'
            f'{p.strip()}</p>'
            for p in roteiro.split('\n\n') if p.strip()
        )

        links_apoio = []
        if KIRVANO_URL:
            links_apoio.append(
                f'<a href="{KIRVANO_URL}" target="_blank" style="background:#cc0000;'
                f'color:#fff;padding:10px 22px;border-radius:6px;'
                f'text-decoration:none;font-weight:bold;margin:4px;'
                f'display:inline-block">☕ Apoie no Kirvano</a>')
        if KOFI_URL:
            links_apoio.append(
                f'<a href="{KOFI_URL}" target="_blank" style="background:#29abe0;'
                f'color:#fff;padding:10px 22px;border-radius:6px;'
                f'text-decoration:none;font-weight:bold;margin:4px;'
                f'display:inline-block">💙 Ko-fi</a>')

        apoio_bloco = ''
        if links_apoio:
            apoio_bloco = (
                f'<div style="background:#fff8f8;border:1px solid #cc0000;'
                f'border-radius:8px;padding:20px;margin:28px 0;text-align:center">'
                f'<p style="margin:0 0 12px;font-size:15px;font-weight:bold">'
                f'💰 Apoie o Canal 55 Notícias</p>'
                + ''.join(links_apoio) + '</div>'
            )

        inscricao = ''
        if CANAL_YOUTUBE_URL:
            inscricao = (
                f'<div style="background:#fff3e0;border:1px solid #ff9800;'
                f'border-radius:8px;padding:16px;margin:24px 0;text-align:center">'
                f'<p style="margin:0 0 10px;font-size:15px">🔔 '
                f'<strong>Não perca nenhuma notícia!</strong></p>'
                f'<a href="{CANAL_YOUTUBE_URL}?sub_confirmation=1" target="_blank" '
                f'style="background:#ff0000;color:#fff;padding:10px 22px;'
                f'border-radius:6px;text-decoration:none;font-weight:bold">'
                f'▶ Inscreva-se no YouTube</a></div>'
            )

        html = f"""<div style="font-family:Georgia,serif;max-width:800px;margin:0 auto;color:#1e293b">
  {thumb_html}
  {assistir_btn}
  {inscricao}
  <div style="margin:24px 0">{paragrafos}</div>
  <div style="margin:20px 0">{tags_html}</div>
  {apoio_bloco}
  <hr style="border:none;border-top:1px solid #e2e8f0;margin:28px 0">
  <p style="font-size:12px;color:#94a3b8;text-align:center">
    Canal 55 Notícias — Política brasileira com atualização contínua.<br>
    Publicado em {datetime.now().strftime('%d/%m/%Y às %H:%M')}
  </p>
</div>"""

        service = _blogger_service()
        post = service.posts().insert(
            blogId=BLOGGER_BLOG_ID,
            body={'title': titulo, 'content': html, 'labels': tags},
            isDraft=False
        ).execute()

        url_post = post.get('url', '')
        print(f"  ✅ Post publicado: {url_post}")
        return url_post

    except Exception as e:
        print(f"  ❌ Erro Blogger: {e}")
        traceback.print_exc()
        return None


# ════════════════════════════════════════════════════════════════════════════
# TWITTER / X
# ════════════════════════════════════════════════════════════════════════════

def publicar_twitter(titulo: str, url_youtube: str) -> bool:
    # A API do X exige plano pago (Basic $100/mês) para postar via API.
    # Desativado até o canal crescer e justificar o custo.
    print("\n🐦 Twitter/X — desativado (plano pago necessário)")
    return False


# ════════════════════════════════════════════════════════════════════════════
# INSTAGRAM — Reels via instagrapi
# ════════════════════════════════════════════════════════════════════════════

def publicar_instagram_reels(video_path: str, titulo: str, roteiro: str,
                              url_youtube: str,
                              thumbnail_path: str | None = None) -> bool:
    if not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD:
        print("  ⚠️ Instagram não configurado — pulando")
        return False
    if not video_path or not os.path.exists(video_path):
        print("  ⚠️ Vídeo não encontrado — pulando Instagram")
        return False
 
    print("\n📸 Publicando no Instagram (Reels)...")
 
    try:
        from instagrapi import Client as InstaClient
 
        cl = InstaClient()
        cl.delay_range = [2, 5]
 
        # Carrega sessão salva como secret (não expira entre execuções)
        if INSTAGRAM_SESSION:
            try:
                session_data = json.loads(INSTAGRAM_SESSION)
                cl.set_settings(session_data)
                cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
                cl.get_timeline_feed()
                print("  🔑 Sessão carregada do secret")
            except Exception as e:
                print(f"  ⚠️ Sessão inválida ({e}), fazendo login...")
                cl = InstaClient()
                cl.delay_range = [2, 5]
                cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
                print("  🔑 Login realizado — atualize o secret INSTAGRAM_SESSION")
        else:
            cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
            print("  🔑 Login sem sessão — adicione secret INSTAGRAM_SESSION")
 
        resumo = (roteiro[:300].rsplit(' ', 1)[0] + '...'
                  if len(roteiro) > 300 else roteiro)
        legenda = (
            f"🗞 {titulo}\n\n{resumo}\n\n"
            f"▶️ Assista no YouTube:\n{url_youtube}\n"
            f"{'📺 ' + CANAL_YOUTUBE_URL if CANAL_YOUTUBE_URL else ''}\n\n"
            f"🔔 Inscreva-se e ative o sininho!\n"
            f"{_apoio_texto()}\n\n"
            f"#Política #Brasil #Notícias #Canal55 #PoliticaBrasileira "
            f"#Congresso #STF #Governo"
        )
 
        cover = (Path(thumbnail_path)
                 if thumbnail_path and os.path.exists(thumbnail_path) else None)
        media = cl.clip_upload(Path(video_path), caption=legenda, thumbnail=cover)
        print(f"  ✅ Reel publicado! ID: {media.pk}")
        return True
 
    except ImportError:
        print("  ❌ instagrapi não instalado — adicione ao requirements.txt")
        return False
    except Exception as e:
        print(f"  ❌ Erro Instagram: {e}")
        traceback.print_exc()
        return False


# ════════════════════════════════════════════════════════════════════════════
# FUNÇÃO PRINCIPAL
# ════════════════════════════════════════════════════════════════════════════

def distribuir(titulo: str, roteiro: str, url_youtube: str, tags: list,
               thumbnail_path: str | None = None,
               video_path: str | None = None,
               midias_sincronizadas: list | None = None) -> dict:
    """
    Chamada no generate_video.py após upload YouTube.
    Retorna dict com resultados E caminho da thumbnail gerada.
    """
    titulo = _limpar_titulo(titulo)
 
    print("\n" + "="*60)
    print("🚀 DISTRIBUIÇÃO — Canal 55 Notícias")
    print("="*60)
 
    res = {
        'thumbnail':      None,
        'thumbnail_916':  None,   # ← versão 9:16 para YouTube
        'telegram_canal': False,
        'blogger_url':    None,
        'twitter':        False,
        'instagram':      False,
        'timestamp':      datetime.now().isoformat()
    }
 
    # Gerar thumbnail quadrada (Telegram + Blogger)
    print("\n🖼️ Gerando thumbnails...")
    fundo = obter_primeira_midia_match(midias_sincronizadas) if midias_sincronizadas else None
    if fundo:
        print(f"  📁 Fundo: {fundo}")
    else:
        print("  ⚠️ Sem match — fundo sólido")
 
    thumb_1x1 = gerar_thumbnail(titulo, fundo, '/tmp/thumbnail_canal55.jpg',
                                 tamanho=(1080, 1080))
    res['thumbnail'] = thumb_1x1
 
    # Gerar thumbnail 9:16 (YouTube Shorts)
    thumb_916 = gerar_thumbnail(titulo, fundo, '/tmp/thumbnail_canal55_916.jpg',
                                tamanho=(1080, 1920))
    res['thumbnail_916'] = thumb_916
 
    thumb = thumb_1x1  # Telegram e Blogger usam a quadrada
 
    # Distribuição
    res['telegram_canal'] = publicar_telegram_canal(titulo, roteiro, url_youtube, thumb)
    time.sleep(2)
    res['blogger_url']    = publicar_blogger(titulo, roteiro, url_youtube, tags, thumb)
    time.sleep(2)
    res['twitter']        = publicar_twitter(titulo, url_youtube)
    time.sleep(2)
    if video_path:
        res['instagram']  = publicar_instagram_reels(
            video_path, titulo, roteiro, url_youtube, thumb)
 
    # Resumo
    print("\n" + "="*60)
    print("📊 RESULTADO DA DISTRIBUIÇÃO")
    print(f"  🖼️  Thumbnail 1:1 : {'✅' if res['thumbnail'] else '❌'}")
    print(f"  🖼️  Thumbnail 9:16: {'✅' if res['thumbnail_916'] else '❌'}")
    print(f"  📣  Telegram      : {'✅' if res['telegram_canal'] else '❌'}")
    print(f"  📝  Blogger       : {'✅' if res['blogger_url'] else '❌'}")
    print(f"  🐦  Twitter/X     : {'✅' if res['twitter'] else '❌'}")
    print(f"  📸  Instagram     : {'✅' if res['instagram'] else '❌'}")
    print("="*60)
 
    return res
