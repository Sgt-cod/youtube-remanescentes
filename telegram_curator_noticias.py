import os
import json
import requests
import time
import sys
from datetime import datetime

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
CURACAO_FILE = 'curacao_pendente.json'
CURACAO_TEMAS_FILE = 'curacao_temas_pendente.json'
ASSETS_DIR = 'assets'

class TelegramCuratorNoticias:
    def __init__(self):
        self.bot_token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.update_id_offset = self._obter_ultimo_update_id()
    
    def _obter_ultimo_update_id(self):
        """Obtém o último update_id"""
        try:
            url = f"{self.base_url}/getUpdates"
            response = requests.get(url, params={'offset': -1}, timeout=5)
            result = response.json()
            
            if result.get('ok') and result.get('result'):
                return result['result'][0]['update_id'] + 1
            return 0
        except:
            return 0
    
    def enviar_mensagem(self, texto, reply_markup=None):
        """Envia mensagem de texto"""
        url = f"{self.base_url}/sendMessage"
        data = {
            'chat_id': self.chat_id,
            'text': texto,
            'parse_mode': 'HTML'
        }
        
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        
        try:
            response = requests.post(url, json=data, timeout=10)
            result = response.json()
            
            if result.get('ok'):
                return result
            else:
                print(f"⚠️ Erro: {result}")
                return None
        except Exception as e:
            print(f"❌ Erro: {e}")
            return None
    
    def enviar_foto(self, foto_path, caption, reply_markup=None):
        """Envia foto LOCAL com legenda"""
        url = f"{self.base_url}/sendPhoto"
        
        try:
            with open(foto_path, 'rb') as photo:
                files = {'photo': photo}
                data = {
                    'chat_id': self.chat_id,
                    'caption': caption,
                    'parse_mode': 'HTML'
                }
                
                if reply_markup:
                    data['reply_markup'] = json.dumps(reply_markup)
                
                response = requests.post(url, files=files, data=data, timeout=15)
                result = response.json()
                
                if result.get('ok'):
                    return result
                else:
                    print(f"⚠️ Erro: {result}")
                    return None
        except Exception as e:
            print(f"❌ Erro: {e}")
            return None
    
    # ========================================
    # CURADORIA DE TEMAS (VÍDEOS LONGOS)
    # ========================================
    
    def solicitar_curacao_temas(self, noticias, timeout=3600):
        """Solicita curadoria dos temas (notícias) antes de gerar roteiros"""
        print("📋 Iniciando curadoria de TEMAS...")
        
        import re
        noticias_limpas = []
        
        for noticia in noticias:
            noticia_limpa = {
                'titulo': re.sub(r'<[^>]*>', '', noticia.get('titulo', '')).strip(),
                'resumo': re.sub(r'<[^>]*>', '', noticia.get('resumo', '')).strip(),
                'link': noticia.get('link', '')
            }
            noticias_limpas.append(noticia_limpa)
        
        print(f"   ✅ {len(noticias_limpas)} notícias com HTML limpo")
        
        curacao_data = {
            'timestamp': datetime.now().isoformat(),
            'noticias': noticias_limpas,
            'status': 'aguardando',
            'aprovacoes': {},
            'rejeicoes': [],
            'substituicoes': {}
        }
        
        with open(CURACAO_TEMAS_FILE, 'w', encoding='utf-8') as f:
            json.dump(curacao_data, f, indent=2, ensure_ascii=False)
        
        mensagem_inicial = (
            f"🎬 CURADORIA DE TEMAS - VÍDEO LONGO\n\n"
            f"📰 {len(noticias_limpas)} notícias encontradas\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}\n\n"
            f"Vou enviar cada tema para você aprovar ou substituir.\n\n"
            f"Comandos:\n"
            f"• /aprovar_tudo - Aprovar todos os temas restantes\n"
            f"• /cancelar - Cancelar curadoria\n"
            f"• /status - Ver progresso\n\n"
            f"⏳ Aguardo {timeout//60}min"
        )
        
        url = f"{self.base_url}/sendMessage"
        data = {
            'chat_id': self.chat_id,
            'text': mensagem_inicial
        }
        
        try:
            response = requests.post(url, json=data, timeout=10)
            result = response.json()
            
            if result.get('ok'):
                print("   ✅ Mensagem inicial enviada")
            else:
                print(f"   ⚠️ Erro ao enviar mensagem inicial: {result}")
        except Exception as e:
            print(f"   ⚠️ Erro ao enviar mensagem inicial: {e}")
        
        time.sleep(2)
        
        self._enviar_proximo_tema()
        
        print("✅ Primeiro tema enviado para curadoria")
        
        return self._aguardar_aprovacao_temas(timeout)
    
    def enviar_link_download(self, download_url, titulo, descricao, tags, url_youtube, duracao, tamanho_mb, tag_name):
        """Envia link de download do vídeo via Telegram COM BOTÃO DE CONFIRMAÇÃO"""
        print("\n📤 Enviando link de download para Telegram...")
        
        try:
            tags_str = ", ".join(tags) if isinstance(tags, list) else tags
            
            mensagem = (
                f"🎬 <b>VÍDEO PUBLICADO</b>\n\n"
                f"📺 <b>Título:</b>\n{titulo}\n\n"
                f"📝 <b>Descrição:</b>\n{descricao[:200]}...\n\n"
                f"🏷️ <b>Tags:</b>\n{tags_str}\n\n"
                f"⏱️ <b>Duração:</b> {int(duracao)}s ({duracao/60:.1f}min)\n"
                f"📦 <b>Tamanho:</b> {tamanho_mb:.2f} MB\n\n"
                f"🔗 <b>YouTube:</b>\n{url_youtube}\n\n"
                f"⬇️ <b>DOWNLOAD DO VÍDEO:</b>\n{download_url}\n\n"
                f"💡 Clique no link, baixe o vídeo e depois confirme abaixo"
            )
            
            keyboard = {
                'inline_keyboard': [
                    [
                        {'text': '✅ Já baixei o vídeo', 'callback_data': f'download_ok_{tag_name}'}
                    ]
                ]
            }
            
            resultado = self.enviar_mensagem(mensagem, reply_markup=keyboard)
            
            if resultado:
                print("✅ Link de download enviado com botão!")
                
                release_info = {
                    'tag_name': tag_name,
                    'download_url': download_url,
                    'timestamp': datetime.now().isoformat(),
                    'aguardando_confirmacao': True
                }
                
                with open('release_pendente.json', 'w', encoding='utf-8') as f:
                    json.dump(release_info, f, indent=2)
                
                if len(descricao) > 200:
                    self.enviar_mensagem(
                        f"📄 <b>Descrição Completa:</b>\n\n{descricao}"
                    )
                
                return True
            else:
                print("❌ Falha ao enviar link")
                return False
                
        except Exception as e:
            print(f"❌ Erro ao enviar link: {e}")
            import traceback
            traceback.print_exc()
            return False

    def aguardar_confirmacao_download(self, timeout=7200):
        """Aguarda confirmação de download via Telegram"""
        print(f"\n⏳ Aguardando confirmação de download...")
        print(f"   Timeout: {timeout}s ({timeout//3600}h)")
        
        if not os.path.exists('release_pendente.json'):
            print("   ⚠️ Nenhuma release pendente")
            return False
        
        inicio = time.time()
        
        while time.time() - inicio < timeout:
            try:
                with open('release_pendente.json', 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if not data.get('aguardando_confirmacao'):
                    print("   ✅ Download confirmado!")
                    return True
                    
            except:
                pass
            
            self._processar_atualizacoes()
            
            time.sleep(3)
        
        print("   ⏰ Timeout - download não confirmado")
        self.enviar_mensagem(
            "⏰ <b>TIMEOUT - Download não confirmado</b>\n\n"
            "A release permanecerá no GitHub.\n"
            "💡 Delete manualmente em: Settings > Releases\n\n"
            "⚠️ Workflow finalizado por timeout."
        )
        time.sleep(2)
        sys.exit(0)
    
    def _enviar_proximo_tema(self):
        """Envia próximo tema para aprovação"""
        if not os.path.exists(CURACAO_TEMAS_FILE):
            return False
        
        with open(CURACAO_TEMAS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        noticias = data['noticias']
        aprovacoes = data['aprovacoes']
        
        proximo_indice = None
        for i, noticia in enumerate(noticias):
            if str(i) not in aprovacoes:
                proximo_indice = i
                break
        
        if proximo_indice is None:
            self._finalizar_curacao_temas()
            return False
        
        noticia = noticias[proximo_indice]
        num = proximo_indice + 1
        total = len(noticias)
        
        resumo = noticia['resumo'][:300] if len(noticia['resumo']) > 300 else noticia['resumo']
        
        mensagem = (
            f"📌 <b>Tema {num}/{total}</b>\n\n"
            f"📰 <b>{noticia['titulo']}</b>\n\n"
            f"📝 <i>{resumo}...</i>\n\n"
            f"<b>Este tema será usado no vídeo?</b>"
        )
        
        keyboard = {
            'inline_keyboard': [
                [
                    {'text': '✅ Aprovar', 'callback_data': f'tema_aprovar_{num}'},
                    {'text': '🔄 Substituir', 'callback_data': f'tema_substituir_{num}'}
                ]
            ]
        }
        
        print(f"📤 Enviando tema {num}/{total} para aprovação...")
        self.enviar_mensagem(mensagem, keyboard)
        
        return True
    
    def _finalizar_curacao_temas(self):
        """Finaliza curadoria de temas"""
        if not os.path.exists(CURACAO_TEMAS_FILE):
            return
        
        with open(CURACAO_TEMAS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        data['status'] = 'aprovado'
        
        with open(CURACAO_TEMAS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        aprovados = len(data['aprovacoes'])
        substituidos = len(data['substituicoes'])
        
        self.enviar_mensagem(
            f"🎉 <b>CURADORIA DE TEMAS CONCLUÍDA!</b>\n\n"
            f"✅ {aprovados} temas aprovados\n"
            f"🔄 {substituidos} temas substituídos\n\n"
            f"📝 Agora vou gerar os roteiros segmentados...\n"
            f"⏳ Em seguida, vem a curadoria de mídias"
        )
        
        print("✅ Curadoria de temas finalizada")
    
    def _aguardar_aprovacao_temas(self, timeout):
        """Aguarda aprovação dos temas"""
        print(f"⏳ Aguardando aprovação de temas...")
        print(f"⏰ Timeout: {timeout}s ({timeout//60}min)")
        
        inicio = time.time()
        ultima_verificacao = 0
        
        while True:
            tempo_decorrido = time.time() - inicio
            
            if tempo_decorrido >= timeout:
                print(f"⏰ Timeout após {tempo_decorrido/60:.1f}min")
                
                if os.path.exists(CURACAO_TEMAS_FILE):
                    with open(CURACAO_TEMAS_FILE, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    data['status'] = 'timeout'
                    
                    with open(CURACAO_TEMAS_FILE, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    
                    self.enviar_mensagem(
                        f"⏰ <b>TIMEOUT NA CURADORIA DE TEMAS</b>\n\n"
                        f"Aguardei {timeout//60}min sem resposta.\n"
                        f"Curadoria cancelada."
                    )
                
                return None
            
            if int(tempo_decorrido) % 60 == 0 and tempo_decorrido != ultima_verificacao:
                minutos = int(tempo_decorrido / 60)
                restantes = int((timeout - tempo_decorrido) / 60)
                print(f"⏱️ {minutos}min | {restantes}min restantes")
                ultima_verificacao = tempo_decorrido
            
            if os.path.exists(CURACAO_TEMAS_FILE):
                with open(CURACAO_TEMAS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if data['status'] == 'aprovado':
                    print("✅ Temas aprovados!")
                    
                    noticias_aprovadas = []
                    
                    for i, noticia in enumerate(data['noticias']):
                        if str(i) in data['aprovacoes']:
                            if str(i) in data['substituicoes']:
                                noticias_aprovadas.append(data['substituicoes'][str(i)])
                            else:
                                noticias_aprovadas.append(noticia)
                    
                    print(f"✅ {len(noticias_aprovadas)} temas finais")
                    
                    try:
                        os.remove(CURACAO_TEMAS_FILE)
                    except:
                        pass
                    
                    return noticias_aprovadas
                
                elif data['status'] == 'cancelado':
                    print("❌ Curadoria cancelada")
                    self.enviar_mensagem("🛑 <b>CURADORIA CANCELADA</b>")
                    sys.exit(1)
            
            self._processar_atualizacoes_temas()
            time.sleep(3)
    
    def _processar_atualizacoes_temas(self):
        """Processa updates do Telegram para curadoria de temas"""
        url = f"{self.base_url}/getUpdates"
        params = {
            'offset': self.update_id_offset,
            'timeout': 1
        }
        
        try:
            response = requests.get(url, params=params, timeout=5)
            result = response.json()
            
            if not result.get('ok'):
                return
            
            updates = result.get('result', [])
            
            if updates:
                print(f"📨 {len(updates)} updates recebidos para temas")
            
            for update in updates:
                self.update_id_offset = update['update_id'] + 1
                
                if 'callback_query' in update:
                    print(f"   🔔 Callback detectado: {update['callback_query']['data']}")
                
                if 'message' in update:
                    self._processar_mensagem_temas(update['message'])
                elif 'callback_query' in update:
                    self._processar_callback_temas(update['callback_query'])
        except Exception as e:
            print(f"⚠️ Erro ao processar updates de temas: {e}")
    
    def _processar_mensagem_temas(self, message):
        """Processa mensagens na curadoria de temas"""
        text = message.get('text', '')
        
        if not os.path.exists(CURACAO_TEMAS_FILE):
            return
        
        with open(CURACAO_TEMAS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"📩 Comando: {text}")
        
        if text == '/cancelar':
            print("🛑 CANCELAR CURADORIA")
            data['status'] = 'cancelado'
            
            with open(CURACAO_TEMAS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            self.enviar_mensagem(
                "🛑 <b>CANCELAMENTO TOTAL</b>\n\n"
                "❌ Curadoria cancelada\n"
                "❌ Vídeo cancelado"
            )
        
        elif text == '/status':
            total = len(data['noticias'])
            aprovados = len(data['aprovacoes'])
            substituidos = len(data['substituicoes'])
            
            self.enviar_mensagem(
                f"📊 <b>STATUS DA CURADORIA DE TEMAS</b>\n\n"
                f"📰 Total de temas: {total}\n"
                f"✅ Aprovados: {aprovados}\n"
                f"🔄 Substituídos: {substituidos}\n"
                f"⏳ Pendentes: {total - aprovados}\n\n"
                f"Status: {data['status']}"
            )
        
        elif text == '/aprovar_tudo':
            print("⏭️ Aprovar todos os temas restantes")
            
            for i in range(len(data['noticias'])):
                if str(i) not in data['aprovacoes']:
                    data['aprovacoes'][str(i)] = 'aprovado'
            
            data['status'] = 'aprovado'
            
            with open(CURACAO_TEMAS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            self.enviar_mensagem("✅ <b>Todos os temas restantes aprovados!</b>")
        
        elif text.startswith('/substituir_'):
            try:
                partes = text.split(' ', 1)
                if len(partes) >= 2:
                    numero_parte = partes[0].replace('/substituir_', '')
                    indice = int(numero_parte) - 1
                    novo_titulo = partes[1].strip()
                    
                    if 0 <= indice < len(data['noticias']):
                        nova_noticia = {
                            'titulo': novo_titulo,
                            'resumo': f"Tema customizado pelo usuário: {novo_titulo}",
                            'link': ''
                        }
                        
                        data['substituicoes'][str(indice)] = nova_noticia
                        data['aprovacoes'][str(indice)] = 'substituido'
                        
                        with open(CURACAO_TEMAS_FILE, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=2, ensure_ascii=False)
                        
                        self.enviar_mensagem(
                            f"✅ <b>Tema {indice+1} substituído!</b>\n\n"
                            f"🆕 {novo_titulo}"
                        )
                        
                        time.sleep(1)
                        self._enviar_proximo_tema()
                    else:
                        self.enviar_mensagem(f"❌ Índice {indice+1} inválido")
                else:
                    self.enviar_mensagem(
                        "❌ Formato incorreto.\n\n"
                        "<b>Use:</b> <code>/substituir_N Novo título</code>\n\n"
                        "<b>Exemplo:</b> <code>/substituir_1 Reforma tributária avança</code>"
                    )
            except Exception as e:
                print(f"Erro ao processar substituição: {e}")
                self.enviar_mensagem(
                    "❌ Erro ao processar.\n\n"
                    "<b>Formato correto:</b>\n"
                    "<code>/substituir_1 Novo título aqui</code>"
                )
    
    def _processar_callback_temas(self, callback):
        """Processa botões na curadoria de temas"""
        callback_data = callback['data']
        callback_id = callback['id']
        
        if not os.path.exists(CURACAO_TEMAS_FILE):
            self._responder_callback(callback_id, "⚠️ Expirado")
            return
        
        with open(CURACAO_TEMAS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"🖱️ Botão TEMAS: {callback_data}")
        
        self._responder_callback(callback_id, "✅ Processando...")
        
        try:
            if callback_data.startswith('tema_aprovar_'):
                num = int(callback_data.split('_')[2])
                self._aprovar_tema(data, num)
            
            elif callback_data.startswith('tema_substituir_'):
                num = int(callback_data.split('_')[2])
                self._solicitar_substituicao_tema(data, num)
            
            else:
                print(f"⚠️ Callback desconhecido: {callback_data}")
                
        except Exception as e:
            print(f"❌ Erro ao processar callback de tema: {e}")
            import traceback
            traceback.print_exc()
    
    def _aprovar_tema(self, data, num):
        """Aprova um tema"""
        idx = num - 1
        total = len(data['noticias'])
        
        print(f"✅ Aprovar tema {num}/{total}")
        
        data['aprovacoes'][str(idx)] = 'aprovado'
        
        with open(CURACAO_TEMAS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        self.enviar_mensagem(f"✅ <b>Tema {num} aprovado!</b>")
        
        time.sleep(1)
        self._enviar_proximo_tema()
    
    def _solicitar_substituicao_tema(self, data, num):
        """Solicita substituição de tema"""
        idx = num - 1
        
        print(f"🔄 Solicitar substituição tema {num}")
        
        self.enviar_mensagem(
            f"🔄 <b>Substituir Tema {num}</b>\n\n"
            f"Digite o NOVO tema que deseja:\n\n"
            f"<b>Formato:</b>\n"
            f"<code>/substituir_{num} Seu novo título aqui</code>\n\n"
            f"<b>Exemplo:</b>\n"
            f"<code>/substituir_{num} Reforma tributária avança no Senado</code>"
        )
    
    # ========================================
    # CURADORIA DE MÍDIAS (COM SUPORTE A VÍDEO)
    # ========================================
    
    def solicitar_curacao(self, segmentos_com_midias):
        """Inicia curadoria interativa DE MÍDIAS"""
        print("📱 Iniciando curadoria de MÍDIAS...")
        
        curacao_data = {
            'timestamp': datetime.now().isoformat(),
            'segmentos': segmentos_com_midias,
            'status': 'aguardando',
            'segmento_atual': 0,
            'aprovacoes': {},
            'aguardando_midia': False,   # Aguardando foto OU vídeo do usuário
            'ultimo_envio': None
        }
        
        with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
            json.dump(curacao_data, f, indent=2, ensure_ascii=False)
        
        self.enviar_mensagem(
            f"🎬 <b>CURADORIA DE MÍDIAS</b>\n\n"
            f"📝 {len(segmentos_com_midias)} segmentos encontrados\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}\n\n"
            f"🖼️ <b>Imagens do banco local</b>\n\n"
            f"<b>Comandos:</b>\n"
            f"• <b>/cancelar</b> - Cancela TUDO\n"
            f"• <b>/status</b> - Ver progresso\n"
            f"• <b>/pular</b> - Aprovar restantes\n"
            f"• <b>/retomar</b> - Se travar\n\n"
            f"💡 <b>Pode enviar foto ou vídeo do celular!</b>\n"
            f"🎬 <b>Vídeos muito longos serão cortados automaticamente</b>"
        )
        
        time.sleep(2)
        self._enviar_proximo_segmento()
        print("✅ Primeira mídia enviada para curadoria")
    
    def _enviar_proximo_segmento(self):
        """Envia próximo segmento com TEXTO COMPLETO"""
        if not os.path.exists(CURACAO_FILE):
            return False
        
        with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        segmento_atual = data['segmento_atual']
        segmentos = data['segmentos']
        total = len(segmentos)
        
        if segmento_atual >= total:
            self._finalizar_curacao()
            return False
        
        seg = segmentos[segmento_atual]
        num = segmento_atual + 1
        
        midia_info, midia_tipo = seg['midia']
        # ALTERAÇÃO: usar 'texto_completo' se disponível, senão fallback para 'texto'
        texto_seg = seg.get('texto_completo', seg.get('texto', ''))
        keywords = seg.get('keywords', [])
        duracao_seg = seg.get('duracao', 0)
        
        # Truncar texto se muito longo para o Telegram (limite ~4096 chars na legenda)
        # Enviar o texto integral como mensagem separada se necessário
        texto_exibir = texto_seg
        texto_extra = None
        
        # Legenda tem limite de 1024 chars no Telegram
        caption_base = (
            f"📌 <b>Segmento {num}/{total}</b>\n\n"
            f"⏱️ Duração: {duracao_seg:.1f}s\n"
            f"🔍 Keywords: {', '.join(keywords)}\n"
            f"📁 Pasta: {self._extrair_pasta(midia_info)}\n\n"
            f"📝 <b>Roteiro deste segmento:</b>\n"
        )
        
        # Calcular espaço restante para o texto do roteiro na legenda
        espaco_restante = 1024 - len(caption_base) - 100  # 100 chars de margem
        
        if len(texto_exibir) > espaco_restante:
            texto_na_legenda = texto_exibir[:espaco_restante] + "..."
            texto_extra = texto_exibir  # enviar completo depois
        else:
            texto_na_legenda = texto_exibir
        
        caption = caption_base + f"<i>{texto_na_legenda}</i>"
        
        keyboard = {
            'inline_keyboard': [
                [
                    {'text': '✅ Aprovar', 'callback_data': f'aprovar_{num}'},
                    {'text': '🔄 Buscar outra', 'callback_data': f'buscar_{num}'}
                ],
                [
                    {'text': '📤 Enviar foto/vídeo', 'callback_data': f'midia_{num}'}
                ]
            ]
        }
        
        print(f"📤 Enviando segmento {num}/{total}...")
        resultado = self.enviar_foto(midia_info, caption, keyboard)
        
        if resultado:
            data['ultimo_envio'] = datetime.now().isoformat()
            with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            # Enviar texto completo como mensagem adicional se foi truncado
            if texto_extra:
                time.sleep(1)
                self.enviar_mensagem(
                    f"📄 <b>Roteiro completo do segmento {num}:</b>\n\n"
                    f"<i>{texto_extra}</i>"
                )
            
            print(f"✅ Segmento {num} enviado")
            return True
        else:
            print(f"❌ Falha ao enviar {num}")
            return False
    
    def _extrair_pasta(self, caminho):
        """Extrai nome da pasta do caminho"""
        try:
            partes = caminho.split('/')
            if len(partes) >= 2:
                return partes[-2]
            return "local"
        except:
            return "local"
    
    def _finalizar_curacao(self):
        """Finaliza curadoria"""
        if not os.path.exists(CURACAO_FILE):
            return
        
        with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        data['status'] = 'aprovado'
        
        with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        self.enviar_mensagem(
            f"🎉 <b>CURADORIA DE MÍDIAS CONCLUÍDA!</b>\n\n"
            f"✅ Todos os {len(data['segmentos'])} segmentos aprovados!\n"
            f"🎥 Criando e publicando vídeo...\n\n"
            f"Aguarde o link!"
        )
        
        print("✅ Curadoria de mídias finalizada")
    
    def aguardar_aprovacao(self, timeout=3600):
        """Aguarda aprovação"""
        print(f"⏳ Aguardando aprovação de mídias...")
        print(f"⏰ Timeout: {timeout}s")
        
        inicio = time.time()
        ultima_verificacao = 0
        ultimo_aviso = 0
        
        while True:
            tempo_decorrido = time.time() - inicio
            
            if tempo_decorrido >= timeout:
                print(f"⏰ Timeout após {tempo_decorrido/60:.1f}min")
                
                if os.path.exists(CURACAO_FILE):
                    with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    data['status'] = 'timeout'
                    
                    with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    
                    self.enviar_mensagem(
                        f"⏰ <b>TIMEOUT</b>\n\n"
                        f"Aguardei {timeout/60:.0f}min sem resposta.\n"
                        f"Curadoria cancelada."
                    )
                
                return None
            
            if int(tempo_decorrido) % 60 == 0 and tempo_decorrido != ultima_verificacao:
                minutos = int(tempo_decorrido / 60)
                restantes = int((timeout - tempo_decorrido) / 60)
                print(f"⏱️ {minutos}min | {restantes}min restantes")
                ultima_verificacao = tempo_decorrido
            
            if os.path.exists(CURACAO_FILE):
                with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if data.get('ultimo_envio'):
                    ultimo_envio = datetime.fromisoformat(data['ultimo_envio'])
                    tempo_sem_resposta = (datetime.now() - ultimo_envio).total_seconds()
                    
                    if tempo_sem_resposta > 120 and tempo_sem_resposta - ultimo_aviso > 120:
                        minutos_travado = int(tempo_sem_resposta / 60)
                        seg_atual = data['segmento_atual'] + 1
                        total = len(data['segmentos'])
                        
                        self.enviar_mensagem(
                            f"⚠️ <b>PODE ESTAR TRAVADO</b>\n\n"
                            f"Sem resposta há {minutos_travado}min\n"
                            f"Segmento: {seg_atual}/{total}\n\n"
                            f"Use <b>/retomar</b> se necessário"
                        )
                        ultimo_aviso = tempo_sem_resposta
                        print(f"⚠️ Travamento? {minutos_travado}min")
                
                if data['status'] == 'aprovado':
                    print("✅ Mídias aprovadas!")
                    return data['segmentos']
                
                elif data['status'] == 'cancelado':
                    print("❌ Cancelado")
                    self.enviar_mensagem("🛑 <b>WORKFLOW CANCELADO</b>")
                    sys.exit(1)
            
            self._processar_atualizacoes()
            time.sleep(3)
    
    def _processar_atualizacoes(self):
        """Processa updates do Telegram"""
        url = f"{self.base_url}/getUpdates"
        params = {
            'offset': self.update_id_offset,
            'timeout': 1
        }
        
        try:
            response = requests.get(url, params=params, timeout=5)
            result = response.json()
            
            if not result.get('ok'):
                return
            
            updates = result.get('result', [])
            
            for update in updates:
                self.update_id_offset = update['update_id'] + 1
                
                if 'message' in update:
                    self._processar_mensagem(update['message'])
                elif 'callback_query' in update:
                    self._processar_callback(update['callback_query'])
        except:
            pass
    
    def _processar_callback(self, callback):
        """Processa botões"""
        callback_data = callback['data']
        callback_id = callback['id']
        
        # Confirmação de download
        if callback_data.startswith('download_ok_'):
            tag_name = callback_data.replace('download_ok_', '')
            print(f"\n✅ CONFIRMAÇÃO DE DOWNLOAD RECEBIDA")
            print(f"   Tag: {tag_name}")
            
            self._responder_callback(callback_id, "✅ Download confirmado!")
            
            try:
                with open('release_pendente.json', 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                data['aguardando_confirmacao'] = False
                data['confirmado_em'] = datetime.now().isoformat()
                
                with open('release_pendente.json', 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
                
                self.enviar_mensagem("✅ <b>Download confirmado!</b>\n\n🗑️ Deletando release do GitHub...")
                
                from create_release import deletar_release
                
                if deletar_release(tag_name):
                    self.enviar_mensagem("✅ Release deletada com sucesso!\n\n💾 Espaço liberado no repositório.\n\n🎉 Workflow finalizado!")
                    
                    try:
                        os.remove('release_pendente.json')
                    except:
                        pass
                    
                    print("\n" + "="*60)
                    print("✅ WORKFLOW CONCLUÍDO COM SUCESSO!")
                    print("="*60)
                    time.sleep(2)
                    sys.exit(0)
                else:
                    self.enviar_mensagem("⚠️ Erro ao deletar release. Delete manualmente se necessário.\n\n⚠️ Workflow finalizado com aviso.")
                    time.sleep(2)
                    sys.exit(0)
                    
            except Exception as e:
                print(f"❌ Erro ao processar confirmação: {e}")
                self.enviar_mensagem(f"❌ Erro: {e}\n\n⚠️ Workflow finalizado com erro.")
                time.sleep(2)
                sys.exit(1)
            return
        
        if callback_data.startswith('tema_'):
            if os.path.exists(CURACAO_TEMAS_FILE):
                self._processar_callback_temas(callback)
            else:
                self._responder_callback(callback_id, "⚠️ Curadoria de temas expirada")
            return
        
        if not os.path.exists(CURACAO_FILE):
            self._responder_callback(callback_id, "⚠️ Expirado")
            return
        
        with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"🖱️ Botão MÍDIAS: {callback_data}")
        self._responder_callback(callback_id, "✅ Processando...")
        
        if callback_data.startswith('aprovar_'):
            num = int(callback_data.split('_')[1])
            self._aprovar_segmento(data, num)
        
        elif callback_data.startswith('buscar_'):
            num = int(callback_data.split('_')[1])
            self._buscar_nova_midia(data, num)
        
        elif callback_data.startswith('midia_'):
            # ALTERAÇÃO: botão unificado para foto ou vídeo
            num = int(callback_data.split('_')[1])
            self._solicitar_midia(data, num)
    
    def _processar_mensagem(self, message):
        """Processa mensagens"""
        text = message.get('text', '')
        
        if os.path.exists(CURACAO_TEMAS_FILE):
            self._processar_mensagem_temas(message)
            return
        
        if not os.path.exists(CURACAO_FILE):
            if text == '/start':
                self.enviar_mensagem(
                    "👋 <b>Curador de Notícias</b>\n\n"
                    "Enviarei temas e mídias para você aprovar.\n"
                    "Você pode enviar fotos ou vídeos do celular!\n\n"
                    "Aguarde próxima execução."
                )
            return
        
        with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"📩 Comando/mensagem recebido: {text[:50] if text else '(mídia)'}")
        
        if text == '/cancelar':
            print("🛑 CANCELAR TUDO")
            data['status'] = 'cancelado'
            
            with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            self.enviar_mensagem(
                "🛑 <b>CANCELAMENTO TOTAL</b>\n\n"
                "❌ Curadoria cancelada\n"
                "❌ Vídeo cancelado\n"
                "❌ Workflow encerrado"
            )
        
        elif text == '/status':
            atual = data['segmento_atual']
            total = len(data['segmentos'])
            aprovados = len(data.get('aprovacoes', {}))
            ultimo_envio_str = "Nunca"
            
            if data.get('ultimo_envio'):
                ultimo_envio = datetime.fromisoformat(data['ultimo_envio'])
                tempo = (datetime.now() - ultimo_envio).total_seconds()
                ultimo_envio_str = f"{int(tempo / 60)}min atrás"
            
            self.enviar_mensagem(
                f"📊 <b>STATUS</b>\n\n"
                f"✅ Aprovados: {aprovados}\n"
                f"📍 Atual: {atual + 1}/{total}\n"
                f"⏳ Status: {data['status']}\n"
                f"🕐 Último: {ultimo_envio_str}\n\n"
                f"<i>Se travou: /retomar</i>"
            )
        
        elif text == '/pular':
            thumbnail_file = 'thumbnail_pendente.json'
            
            if os.path.exists(thumbnail_file):
                print("⏭️ Pular thumbnail")
                with open(thumbnail_file, 'r', encoding='utf-8') as f:
                    thumb_data = json.load(f)
                
                thumb_data['status'] = 'pulada'
                
                with open(thumbnail_file, 'w', encoding='utf-8') as f:
                    json.dump(thumb_data, f, indent=2, ensure_ascii=False)
                
                self.enviar_mensagem("⏭️ <b>Usando thumbnail automática</b>")
            
            elif os.path.exists(CURACAO_FILE):
                print("⏭️ Pular curadoria de mídias")
                data['status'] = 'aprovado'
                
                with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                self.enviar_mensagem("⏭️ <b>Restantes aprovados!</b>")
        
        elif text == '/retomar':
            print("🔄 Retomar")
            atual = data['segmento_atual']
            total = len(data['segmentos'])
            
            self.enviar_mensagem(
                f"🔄 <b>RETOMANDO</b>\n\n"
                f"Forçando segmento {atual + 1}/{total}..."
            )
            
            time.sleep(1)
            
            if self._enviar_proximo_segmento():
                self.enviar_mensagem("✅ Reenviado!")
            else:
                self.enviar_mensagem("❌ Todos enviados")
        
        # ALTERAÇÃO: processar tanto foto quanto vídeo
        elif 'photo' in message:
            thumbnail_file = 'thumbnail_pendente.json'
            
            if os.path.exists(thumbnail_file):
                self._processar_thumbnail(message)
            elif os.path.exists(CURACAO_FILE) and data.get('aguardando_midia'):
                self._processar_midia_enviada(message, tipo='foto')
        
        elif 'video' in message or 'document' in message:
            # Vídeo enviado como arquivo ou como document (para não comprimir)
            if os.path.exists(CURACAO_FILE) and data.get('aguardando_midia'):
                self._processar_midia_enviada(message, tipo='video')
    
    def _processar_midia_enviada(self, message, tipo='foto'):
        """Processa foto ou vídeo enviado pelo usuário"""
        if not os.path.exists(CURACAO_FILE):
            return
        
        with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if not data.get('aguardando_midia'):
            self.enviar_mensagem("⚠️ Não estou aguardando mídia. Use o botão 📤")
            return
        
        idx = data['midia_segmento']
        total = len(data['segmentos'])
        num = idx + 1
        
        print(f"📸 {'Foto' if tipo == 'foto' else 'Vídeo'} recebido para segmento {num}")
        
        self.enviar_mensagem(f"📥 Baixando sua {'foto' if tipo == 'foto' else 'vídeo'}...")
        
        try:
            if tipo == 'foto':
                # Processar foto
                photo = message['photo'][-1]
                file_id = photo['file_id']
                extensao = '.jpg'
                midia_tipo_final = 'foto_local'
            else:
                # Processar vídeo - verificar se veio como 'video' ou 'document'
                if 'video' in message:
                    video_info = message['video']
                    file_id = video_info['file_id']
                elif 'document' in message:
                    doc_info = message['document']
                    file_id = doc_info['file_id']
                else:
                    self.enviar_mensagem("❌ Tipo de arquivo não reconhecido.")
                    return
                extensao = '.mp4'
                midia_tipo_final = 'video_local'
            
            # Obter info do arquivo
            file_info_url = f"{self.base_url}/getFile?file_id={file_id}"
            file_response = requests.get(file_info_url, timeout=10)
            file_data = file_response.json()
            
            if not file_data.get('ok'):
                raise Exception("Erro ao obter info do arquivo")
            
            file_path = file_data['result']['file_path']
            download_url = f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}"
            
            # Download do arquivo (timeout maior para vídeos)
            timeout_download = 60 if tipo == 'foto' else 300
            midia_response = requests.get(download_url, timeout=timeout_download)
            
            midia_filename = f'{ASSETS_DIR}/custom_{num}{extensao}'
            
            with open(midia_filename, 'wb') as f:
                f.write(midia_response.content)
            
            tamanho_mb = os.path.getsize(midia_filename) / (1024 * 1024)
            print(f"✅ {'Foto' if tipo == 'foto' else 'Vídeo'} salvo: {midia_filename} ({tamanho_mb:.1f} MB)")
            
            # Atualizar segmento
            seg = data['segmentos'][idx]
            seg['midia'] = (midia_filename, midia_tipo_final)
            seg['customizado'] = True
            
            data['segmentos'][idx] = seg
            data['aprovacoes'][str(idx)] = 'aprovado'
            
            if idx + 1 < total:
                data['segmento_atual'] = idx + 1
            else:
                data['segmento_atual'] = total
            
            data['aguardando_midia'] = False
            
            with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            if tipo == 'video':
                duracao_seg = seg.get('duracao', 0)
                self.enviar_mensagem(
                    f"✅ <b>Vídeo recebido!</b>\n\n"
                    f"📏 Duração do segmento: {duracao_seg:.1f}s\n"
                    f"✂️ Se o vídeo for mais longo, será cortado automaticamente"
                )
            else:
                self.enviar_mensagem(f"✅ <b>Foto aplicada ao segmento {num}!</b>")
            
            time.sleep(2)
            self._enviar_proximo_segmento()
            
        except Exception as e:
            print(f"❌ Erro ao processar mídia: {e}")
            self.enviar_mensagem(f"❌ Erro ao processar: {e}\n\nTente novamente ou use /retomar")
    
    # Mantido para compatibilidade retroativa
    def _processar_foto_enviada(self, message):
        """Compatibilidade - chama o novo método unificado"""
        self._processar_midia_enviada(message, tipo='foto')
    
    def _aprovar_segmento(self, data, num):
        """Aprova segmento"""
        idx = num - 1
        total = len(data['segmentos'])
        
        print(f"✅ Aprovar {num}/{total}")
        
        data['aprovacoes'][str(idx)] = 'aprovado'
        
        if idx + 1 < total:
            data['segmento_atual'] = idx + 1
        else:
            data['segmento_atual'] = total
        
        with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        self.enviar_mensagem(f"✅ <b>Segmento {num} aprovado!</b>")
        
        time.sleep(2)
        self._enviar_proximo_segmento()
    
    def _buscar_nova_midia(self, data, num):
        """Busca outra imagem da mesma pasta"""
        idx = num - 1
        seg = data['segmentos'][idx]
        
        print(f"🔄 Buscar nova para {num}")
        
        self.enviar_mensagem(f"🔄 Buscando outra imagem...")
        
        try:
            caminho_atual = seg['midia'][0]
            pasta = os.path.dirname(caminho_atual)
            
            arquivos = [f for f in os.listdir(pasta)
                       if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            
            nome_atual = os.path.basename(caminho_atual)
            if nome_atual in arquivos:
                arquivos.remove(nome_atual)
            
            if arquivos:
                import random
                nova_foto = random.choice(arquivos)
                novo_caminho = os.path.join(pasta, nova_foto)
                
                seg['midia'] = (novo_caminho, 'foto_local')
                data['segmentos'][idx] = seg
                data['segmento_atual'] = idx
                
                with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                print(f"✅ Nova imagem encontrada")
                
                time.sleep(2)
                self._enviar_proximo_segmento()
            else:
                self.enviar_mensagem("⚠️ Sem mais imagens nesta pasta. Use 📤 para enviar foto ou vídeo!")
        
        except Exception as e:
            print(f"❌ Erro: {e}")
            self.enviar_mensagem(f"❌ Erro. Use 📤 Enviar foto/vídeo!")
    
    def _solicitar_midia(self, data, num):
        """Solicita foto ou vídeo do usuário"""
        idx = num - 1
        
        print(f"📤 Solicitar mídia para segmento {num}")
        
        duracao_seg = data['segmentos'][idx].get('duracao', 0)
        
        # ALTERAÇÃO: flag renomeada de aguardando_foto para aguardando_midia
        data['aguardando_midia'] = True
        data['midia_segmento'] = idx
        # Manter compatibilidade com código antigo que verifica aguardando_foto
        data['aguardando_foto'] = True
        data['foto_segmento'] = idx
        
        with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        self.enviar_mensagem(
            f"📤 <b>Envie sua mídia agora</b>\n\n"
            f"🖼️ <b>Foto:</b> envie normalmente pela galeria\n"
            f"🎬 <b>Vídeo:</b> envie como arquivo para melhor qualidade\n\n"
            f"⏱️ <b>Duração deste segmento: {duracao_seg:.1f}s</b>\n"
            f"✂️ Vídeos mais longos serão cortados automaticamente\n\n"
            f"💡 Será usada no segmento {num}"
        )
    
    # Mantido para compatibilidade retroativa
    def _solicitar_foto(self, data, num):
        """Compatibilidade - chama o novo método unificado"""
        self._solicitar_midia(data, num)
    
    def _responder_callback(self, callback_id, texto):
        """Responde callback"""
        url = f"{self.base_url}/answerCallbackQuery"
        
        try:
            requests.post(url, json={
                'callback_query_id': callback_id,
                'text': texto,
                'show_alert': False
            }, timeout=5)
        except:
            pass
    
    # ========================================
    # CURADORIA DE THUMBNAIL
    # ========================================
    
    def solicitar_thumbnail(self, titulo, timeout=1200):
        """Solicita thumbnail customizada"""
        print("🖼️ Solicitando thumbnail...")
        
        thumbnail_file = 'thumbnail_pendente.json'
        
        data = {
            'titulo': titulo,
            'status': 'aguardando',
            'thumbnail_path': None,
            'timestamp': datetime.now().isoformat()
        }
        
        with open(thumbnail_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        self.enviar_mensagem(
            f"🖼️ <b>THUMBNAIL CUSTOMIZADA</b>\n\n"
            f"📺 <b>Vídeo:</b>\n"
            f"<i>{titulo}</i>\n\n"
            f"📤 <b>Envie a imagem AGORA</b>\n\n"
            f"💡 <b>Recomendações:</b>\n"
            f"• Resolução: 1280x720 ou superior\n"
            f"• Formato: JPG ou PNG\n"
            f"• Texto grande e legível\n"
            f"• Cores vibrantes\n\n"
            f"⏱️ Tempo: {timeout//60} minutos\n"
            f"⏭️ Use /pular para thumbnail automática"
        )
        
        inicio = time.time()
        ultimo_aviso = 0
        
        while time.time() - inicio < timeout:
            tempo_decorrido = time.time() - inicio
            
            if int(tempo_decorrido) // 300 > ultimo_aviso:
                minutos_restantes = int((timeout - tempo_decorrido) / 60)
                self.enviar_mensagem(
                    f"⏳ Ainda aguardando thumbnail...\n"
                    f"⏰ {minutos_restantes} minutos restantes\n"
                    f"Use /pular se não quiser enviar"
                )
                ultimo_aviso = int(tempo_decorrido) // 300
            
            if os.path.exists(thumbnail_file):
                with open(thumbnail_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if data['status'] == 'recebida':
                    print("✅ Thumbnail recebida!")
                    thumbnail_path = data['thumbnail_path']
                    
                    try:
                        os.remove(thumbnail_file)
                    except:
                        pass
                    
                    return thumbnail_path
                
                elif data['status'] == 'pulada':
                    print("⏭️ Thumbnail pulada pelo usuário")
                    
                    try:
                        os.remove(thumbnail_file)
                    except:
                        pass
                    
                    return None
            
            self._processar_atualizacoes()
            time.sleep(3)
        
        print("⏰ Timeout ao aguardar thumbnail")
        self.enviar_mensagem("⏰ <b>Tempo esgotado</b>\n\nUsando thumbnail automática do YouTube")
        
        try:
            os.remove(thumbnail_file)
        except:
            pass
        
        return None
    
    def _processar_thumbnail(self, message):
        """Processa thumbnail enviada"""
        thumbnail_file = 'thumbnail_pendente.json'
        
        if not os.path.exists(thumbnail_file):
            return
        
        print("📸 Thumbnail recebida")
        
        self.enviar_mensagem("📥 Baixando thumbnail...")
        
        try:
            photo = message['photo'][-1]
            file_id = photo['file_id']
            
            file_info_url = f"{self.base_url}/getFile?file_id={file_id}"
            file_response = requests.get(file_info_url, timeout=10)
            file_data = file_response.json()
            
            if not file_data.get('ok'):
                raise Exception("Erro ao obter arquivo")
            
            file_path = file_data['result']['file_path']
            download_url = f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}"
            
            foto_response = requests.get(download_url, timeout=15)
            thumbnail_path = f'{ASSETS_DIR}/thumbnail_custom.jpg'
            
            with open(thumbnail_path, 'wb') as f:
                f.write(foto_response.content)
            
            print(f"✅ Thumbnail salva: {thumbnail_path}")
            
            with open(thumbnail_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            data['status'] = 'recebida'
            data['thumbnail_path'] = thumbnail_path
            
            with open(thumbnail_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            self.enviar_mensagem("✅ <b>Thumbnail recebida!</b>\n\nContinuando...")
            
        except Exception as e:
            print(f"❌ Erro: {e}")
            self.enviar_mensagem(f"❌ Erro ao processar thumbnail: {e}")
    
    def enviar_video_publicado(self, video_path, titulo, descricao, tags, url_youtube):
        """Envia vídeo completo + metadados para o Telegram após publicação"""
        print("\n📤 Enviando vídeo para Telegram...")
        
        if not os.path.exists(video_path):
            print(f"❌ Vídeo não encontrado: {video_path}")
            return False
        
        try:
            tags_str = ", ".join(tags) if isinstance(tags, list) else tags
            
            caption = (
                f"🎬 <b>VÍDEO PUBLICADO</b>\n\n"
                f"📺 <b>Título:</b>\n{titulo}\n\n"
                f"📝 <b>Descrição:</b>\n{descricao[:200]}...\n\n"
                f"🏷️ <b>Tags:</b>\n{tags_str}\n\n"
                f"🔗 <b>YouTube:</b>\n{url_youtube}\n\n"
                f"💾 Arquivo MP4 em anexo para publicação no TikTok"
            )
            
            url = f"{self.base_url}/sendVideo"
            
            with open(video_path, 'rb') as video_file:
                files = {'video': video_file}
                data = {
                    'chat_id': self.chat_id,
                    'caption': caption,
                    'parse_mode': 'HTML',
                    'supports_streaming': True
                }
                
                print(f"  📹 Enviando vídeo: {os.path.basename(video_path)}")
                print(f"  📦 Tamanho: {os.path.getsize(video_path) / (1024*1024):.1f} MB")
                
                response = requests.post(url, files=files, data=data, timeout=300)
                result = response.json()
                
                if result.get('ok'):
                    print("✅ Vídeo enviado com sucesso!")
                    
                    if len(descricao) > 200:
                        self.enviar_mensagem(
                            f"📄 <b>Descrição Completa:</b>\n\n{descricao}"
                        )
                    
                    return True
                else:
                    print(f"⚠️ Erro ao enviar vídeo: {result}")
                    
                    if 'file is too big' in str(result).lower():
                        print("  ⚠️ Vídeo muito grande, tentando como documento...")
                        return self._enviar_video_como_documento(video_path, caption)
                    
                    return False
                    
        except Exception as e:
            print(f"❌ Erro ao enviar vídeo: {e}")
            import traceback
            traceback.print_exc()
            
            self.enviar_mensagem(
                f"⚠️ <b>Erro ao enviar vídeo (muito grande)</b>\n\n"
                f"{caption}\n\n"
                f"📁 Vídeo disponível no GitHub Actions artifacts"
            )
            return False
    
    def _enviar_video_como_documento(self, video_path, caption):
        """Envia vídeo como documento (para arquivos grandes)"""
        url = f"{self.base_url}/sendDocument"
        
        try:
            with open(video_path, 'rb') as video_file:
                files = {'document': video_file}
                data = {
                    'chat_id': self.chat_id,
                    'caption': caption[:1024],
                    'parse_mode': 'HTML'
                }
                
                print("  📎 Enviando como documento...")
                response = requests.post(url, files=files, data=data, timeout=300)
                result = response.json()
                
                if result.get('ok'):
                    print("✅ Vídeo enviado como documento!")
                    return True
                else:
                    print(f"❌ Falha: {result}")
                    return False
                    
        except Exception as e:
            print(f"❌ Erro: {e}")
            return False
    
    def notificar_publicacao(self, video_info):
        """Notifica publicação"""
        mensagem = (
            f"🎉 <b>VÍDEO PUBLICADO!</b>\n\n"
            f"📺 {video_info['titulo']}\n"
            f"⏱️ {video_info['duracao']:.1f}s\n"
            f"🔗 {video_info['url']}\n\n"
            f"✅ No ar!"
        )
        self.enviar_mensagem(mensagem)
        print("📤 Notificação enviada")
