import os
import json
import requests
import time
from datetime import datetime

class TikTokUploader:
    def __init__(self):
        self.client_key = os.environ.get('TIKTOK_CLIENT_KEY')
        self.client_secret = os.environ.get('TIKTOK_CLIENT_SECRET')
        self.access_token = os.environ.get('TIKTOK_ACCESS_TOKEN')
        
        self.base_url = "https://open.tiktokapis.com/v2"
        
    def verificar_credenciais(self):
        """Verifica se as credenciais estão configuradas"""
        if not all([self.client_key, self.client_secret, self.access_token]):
            print("⚠️ Credenciais do TikTok não configuradas")
            return False
        return True
    
    def fazer_upload(self, video_path, titulo, descricao, hashtags=None):
        """
        Faz upload de vídeo para o TikTok
        
        Args:
            video_path: Caminho do arquivo de vídeo
            titulo: Título do vídeo (max 150 caracteres)
            descricao: Descrição do vídeo
            hashtags: Lista de hashtags (opcional)
        
        Returns:
            dict: Informações do vídeo publicado ou None se falhar
        """
        if not self.verificar_credenciais():
            return None
        
        if not os.path.exists(video_path):
            print(f"❌ Arquivo não encontrado: {video_path}")
            return None
        
        print("📤 Iniciando upload para TikTok...")
        
        try:
            # Passo 1: Inicializar upload
            print("  1️⃣ Inicializando upload...")
            init_response = self._inicializar_upload(video_path)
            
            if not init_response:
                return None
            
            upload_url = init_response['data']['upload_url']
            publish_id = init_response['data']['publish_id']
            
            # Passo 2: Upload do arquivo
            print("  2️⃣ Enviando arquivo...")
            upload_success = self._upload_arquivo(upload_url, video_path)
            
            if not upload_success:
                return None
            
            # Passo 3: Publicar vídeo
            print("  3️⃣ Publicando...")
            
            # Preparar descrição com hashtags
            descricao_completa = self._preparar_descricao(titulo, descricao, hashtags)
            
            publish_response = self._publicar_video(
                publish_id, 
                descricao_completa
            )
            
            if publish_response:
                video_id = publish_response['data']['publish_id']
                print(f"✅ Vídeo publicado no TikTok!")
                print(f"   ID: {video_id}")
                
                return {
                    'video_id': video_id,
                    'platform': 'tiktok',
                    'titulo': titulo,
                    'descricao': descricao_completa,
                    'timestamp': datetime.now().isoformat()
                }
            
        except Exception as e:
            print(f"❌ Erro ao publicar no TikTok: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _inicializar_upload(self, video_path):
        """Inicializa o processo de upload"""
        url = f"{self.base_url}/post/publish/video/init/"
        
        # Obter tamanho do arquivo
        file_size = os.path.getsize(video_path)
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'post_info': {
                'title': '',
                'privacy_level': 'SELF_ONLY',  # ou PUBLIC_TO_EVERYONE
                'disable_duet': False,
                'disable_comment': False,
                'disable_stitch': False,
                'video_cover_timestamp_ms': 1000
            },
            'source_info': {
                'source': 'FILE_UPLOAD',
                'video_size': file_size,
                'chunk_size': file_size,
                'total_chunk_count': 1
            }
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"❌ Erro ao inicializar upload: {e}")
            return None
    
    def _upload_arquivo(self, upload_url, video_path):
        """Faz upload do arquivo de vídeo"""
        try:
            with open(video_path, 'rb') as video_file:
                headers = {
                    'Content-Type': 'video/mp4'
                }
                
                response = requests.put(
                    upload_url, 
                    data=video_file, 
                    headers=headers,
                    timeout=300  # 5 minutos
                )
                
                response.raise_for_status()
                return True
                
        except Exception as e:
            print(f"❌ Erro ao enviar arquivo: {e}")
            return False
    
    def _publicar_video(self, publish_id, descricao):
        """Publica o vídeo após upload"""
        url = f"{self.base_url}/post/publish/status/fetch/"
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'publish_id': publish_id
        }
        
        # Aguardar processamento (pode levar alguns segundos)
        max_tentativas = 10
        for tentativa in range(max_tentativas):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=30)
                response.raise_for_status()
                result = response.json()
                
                status = result['data']['status']
                
                if status == 'PUBLISH_COMPLETE':
                    return result
                elif status == 'PROCESSING_UPLOAD':
                    print(f"  ⏳ Processando... ({tentativa + 1}/{max_tentativas})")
                    time.sleep(3)
                elif status == 'FAILED':
                    print(f"❌ Falha na publicação: {result['data'].get('fail_reason', 'Desconhecido')}")
                    return None
                    
            except Exception as e:
                print(f"⚠️ Tentativa {tentativa + 1} falhou: {e}")
                if tentativa < max_tentativas - 1:
                    time.sleep(3)
        
        print("❌ Timeout ao aguardar publicação")
        return None
    
    def _preparar_descricao(self, titulo, descricao, hashtags):
        """Prepara descrição formatada com hashtags"""
        # TikTok tem limite de 2200 caracteres na descrição
        partes = []
        
        if titulo:
            partes.append(titulo)
        
        if descricao:
            # Limitar descrição se necessário
            desc_curta = descricao[:500] if len(descricao) > 500 else descricao
            partes.append(desc_curta)
        
        # Adicionar hashtags
        if hashtags:
            if isinstance(hashtags, list):
                hashtags_str = ' '.join([f'#{tag}' for tag in hashtags])
            else:
                hashtags_str = hashtags
            partes.append(hashtags_str)
        
        descricao_final = '\n\n'.join(partes)
        
        # Garantir limite de caracteres
        if len(descricao_final) > 2200:
            descricao_final = descricao_final[:2197] + '...'
        
        return descricao_final
    
    def obter_url_autorizacao(self):
        """
        Gera URL para autorização OAuth
        Usado apenas na configuração inicial
        """
        redirect_uri = "https://localhost/"  # Configure conforme seu app
        scope = "user.info.basic,video.publish"
        
        url = (
            f"https://www.tiktok.com/v2/auth/authorize/"
            f"?client_key={self.client_key}"
            f"&scope={scope}"
            f"&response_type=code"
            f"&redirect_uri={redirect_uri}"
        )
        
        return url
    
    def trocar_code_por_token(self, auth_code):
        """
        Troca o código de autorização por access token
        Usado apenas na configuração inicial
        """
        url = "https://open.tiktokapis.com/v2/oauth/token/"
        
        payload = {
            'client_key': self.client_key,
            'client_secret': self.client_secret,
            'code': auth_code,
            'grant_type': 'authorization_code',
            'redirect_uri': 'https://localhost/'
        }
        
        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
            result = response.json()
            
            access_token = result['data']['access_token']
            refresh_token = result['data']['refresh_token']
            expires_in = result['data']['expires_in']
            
            print("✅ Token obtido com sucesso!")
            print(f"Access Token: {access_token}")
            print(f"Refresh Token: {refresh_token}")
            print(f"Expira em: {expires_in} segundos")
            
            return result['data']
            
        except Exception as e:
            print(f"❌ Erro ao obter token: {e}")
            return None


# Função auxiliar para usar no generate_video.py
def fazer_upload_tiktok(video_path, titulo, descricao, hashtags=None):
    """
    Função simplificada para upload no TikTok
    
    Args:
        video_path: Caminho do vídeo
        titulo: Título do vídeo
        descricao: Descrição
        hashtags: Lista de hashtags (opcional)
    
    Returns:
        dict ou None
    """
    uploader = TikTokUploader()
    return uploader.fazer_upload(video_path, titulo, descricao, hashtags)


if __name__ == '__main__':
    # Teste
    uploader = TikTokUploader()
    
    # Para obter URL de autorização inicial
    # print(uploader.obter_url_autorizacao())
    
    # Teste de upload
    resultado = uploader.fazer_upload(
        'videos/teste.mp4',
        'Teste de Upload',
        'Vídeo de teste via API',
        ['teste', 'api', 'tiktok']
    )
    
    if resultado:
        print(f"✅ Upload bem-sucedido: {json.dumps(resultado, indent=2)}")
