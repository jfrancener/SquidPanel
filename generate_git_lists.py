import re

def create_blacklist():
    input_file = "target categories.md"
    blacklist_file = "blacklist.txt"
    whitelist_file = "whitelist.txt"
    
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Separar seções Bloqueados e Liberados
    parts = content.split("Liberados")
    blocked_part = parts[0]
    allowed_part = parts[1] if len(parts) > 1 else ""
    
    # Extrair domínios de Bloqueados
    # Ignorar nomes de categorias (linhas curtas ou que começam com maiúscula/sem ponto)
    def extract_domains(text):
        # Encontrar tudo que parece um domínio (contém ponto)
        found = re.findall(r'[a-z0-9\-\.]+\.[a-z]{2,}', text.lower())
        return set(found)

    blocked_domains = extract_domains(blocked_part)
    allowed_domains = extract_domains(allowed_part)
    
    # Remover domínios permitidos da lista de bloqueados
    final_blacklist = blocked_domains - allowed_domains
    
    # Salvar blacklist.txt
    with open(blacklist_file, 'w', encoding='utf-8') as f:
        for domain in sorted(list(final_blacklist)):
            # Adiciona o ponto no início para bloquear subdomínios também (.dominio.com)
            if not domain.startswith("."):
                f.write(f".{domain}\n")
            else:
                f.write(f"{domain}\n")
            
    # Salvar whitelist.txt (opcional, para organização)
    with open(whitelist_file, 'w', encoding='utf-8') as f:
        for domain in sorted(list(allowed_domains)):
            f.write(f"{domain}\n")
            
    print(f"Blacklist criada com {len(final_blacklist)} domínios.")
    print(f"Whitelist criada com {len(allowed_domains)} domínios.")

if __name__ == "__main__":
    create_blacklist()
