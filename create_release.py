#!/usr/bin/env python3
"""
Script para criar release no GitHub e fazer upload do vídeo
Retorna a URL de download direto
"""

import os
import sys
import json
import requests
from datetime import datetime

def criar_release_com_video(video_path, titulo, descricao):
    """
    Cria uma release no GitHub e faz upload do vídeo
    
    Args:
        video_path: caminho do arquivo de vídeo
        titulo: título da release
        descricao: descrição da release
    
    Returns:
        dict: {'download_url': str, 'tag_name': str, 'release_id': int} ou None
    """
    
    # Obter informações do GitHub
    github_token = os.environ.get('GITHUB_TOKEN')
    github_repository = os.environ.get('GITHUB_REPOSITORY')
    
    if not github_token:
        print("❌ GITHUB_TOKEN não encontrado")
        return None
    
    if not github_repository:
        print("❌ GITHUB_REPOSITORY não encontrado")
        return None
    
    if not os.path.exists(video_path):
        print(f"❌ Vídeo não encontrado: {video_path}")
        return None
    
    # Informações do arquivo
    video_filename = os.path.basename(video_path)
    video_size = os.path.getsize(video_path) / (1024 * 1024)  # MB
    
    print(f"\n📦 CRIANDO RELEASE NO GITHUB")
    print(f"   Repositório: {github_repository}")
    print(f"   Arquivo: {video_filename}")
    print(f"   Tamanho: {video_size:.2f} MB")
    
    # Criar tag única baseada no timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    tag_name = f"video-{timestamp}"
    
    # Headers para API do GitHub
    headers = {
        'Authorization': f'token {github_token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    
    try:
        # Passo 1: Criar a release
        print(f"\n1️⃣ Criando release com tag '{tag_name}'...")
        
        release_data = {
            'tag_name': tag_name,
            'name': f"📹 {titulo}",
            'body': f"""## 🎬 Vídeo Gerado Automaticamente

**Título:** {titulo}

**Descrição:**
{descricao[:500]}

**Informações:**
- 📅 Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}
- 📦 Tamanho: {video_size:.2f} MB
- 🤖 Gerado automaticamente pelo bot

---

⬇️ **Baixe o vídeo abaixo** (clique no arquivo)
            """,
            'draft': False,
            'prerelease': False
        }
        
        create_url = f"https://api.github.com/repos/{github_repository}/releases"
        response = requests.post(create_url, headers=headers, json=release_data, timeout=30)
        
        if response.status_code != 201:
            print(f"❌ Erro ao criar release: {response.status_code}")
            print(f"   Resposta: {response.text}")
            return None
        
        release = response.json()
        release_id = release['id']
        upload_url = release['upload_url'].replace('{?name,label}', '')
        
        print(f"   ✅ Release criada! ID: {release_id}")
        
        # Passo 2: Fazer upload do vídeo como asset
        print(f"\n2️⃣ Fazendo upload do vídeo...")
        
        upload_headers = {
            'Authorization': f'token {github_token}',
            'Content-Type': 'video/mp4'
        }
        
        with open(video_path, 'rb') as video_file:
            upload_params = {'name': video_filename}
            
            print(f"   ⬆️ Enviando {video_size:.2f} MB...")
            
            upload_response = requests.post(
                upload_url,
                headers=upload_headers,
                params=upload_params,
                data=video_file,
                timeout=600  # 10 minutos de timeout
            )
            
            if upload_response.status_code != 201:
                print(f"❌ Erro ao fazer upload: {upload_response.status_code}")
                print(f"   Resposta: {upload_response.text}")
                return None
            
            asset = upload_response.json()
            download_url = asset['browser_download_url']
            
            print(f"   ✅ Upload concluído!")
            print(f"\n🔗 URL DE DOWNLOAD:")
            print(f"   {download_url}")
            
            # Retornar informações da release
            return {
                'download_url': download_url,
                'tag_name': tag_name,
                'release_id': release_id
            }
            
    except requests.exceptions.Timeout:
        print("❌ Timeout ao comunicar com GitHub")
        return None
    except Exception as e:
        print(f"❌ Erro inesperado: {e}")
        import traceback
        traceback.print_exc()
        return None

def deletar_release(tag_name):
    """
    Deleta uma release do GitHub
    
    Args:
        tag_name: nome da tag da release
    
    Returns:
        bool: True se deletado com sucesso
    """
    github_token = os.environ.get('GITHUB_TOKEN')
    github_repository = os.environ.get('GITHUB_REPOSITORY')
    
    if not github_token or not github_repository:
        print("❌ Credenciais GitHub não encontradas")
        return False
    
    headers = {
        'Authorization': f'token {github_token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    
    try:
        print(f"\n🗑️ Deletando release '{tag_name}'...")
        
        # Buscar release pela tag
        get_url = f"https://api.github.com/repos/{github_repository}/releases/tags/{tag_name}"
        response = requests.get(get_url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            print(f"   ⚠️ Release não encontrada")
            return False
        
        release = response.json()
        release_id = release['id']
        
        # Deletar release
        delete_url = f"https://api.github.com/repos/{github_repository}/releases/{release_id}"
        delete_response = requests.delete(delete_url, headers=headers, timeout=10)
        
        if delete_response.status_code == 204:
            print(f"   ✅ Release deletada!")
            
            # Deletar tag também
            tag_url = f"https://api.github.com/repos/{github_repository}/git/refs/tags/{tag_name}"
            requests.delete(tag_url, headers=headers, timeout=10)
            print(f"   ✅ Tag deletada!")
            
            return True
        else:
            print(f"   ❌ Erro ao deletar: {delete_response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Erro: {e}")
        return False

if __name__ == '__main__':
    # Uso via linha de comando
    if len(sys.argv) < 4:
        print("Uso: python create_release.py <video_path> <titulo> <descricao>")
        sys.exit(1)
    
    video_path = sys.argv[1]
    titulo = sys.argv[2]
    descricao = sys.argv[3]
    
    url = criar_release_com_video(video_path, titulo, descricao)
    
    if url:
        print(f"\n✅ Sucesso! URL: {url}")
        sys.exit(0)
    else:
        print("\n❌ Falha ao criar release")
        sys.exit(1)
