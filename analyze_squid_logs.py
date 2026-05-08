import re
from collections import Counter
from urllib.parse import urlparse

def analyze_logs():
    log_file = "access.log"
    if not os.path.exists(log_file):
        print("Arquivo access.log não encontrado.")
        return

    domains = []
    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            parts = line.split()
            if len(parts) > 6:
                url = parts[6]
                # Squid URL can be domain:port or full URL
                if url.startswith("http"):
                    domain = urlparse(url).netloc
                else:
                    domain = url.split(':')[0]
                
                # Clean domain
                domain = domain.lower()
                # Remove subdomains for broad classification? Maybe keep for now
                domains.append(domain)

    # Filter domains
    strange_domains = []
    
    # Categories to filter OUT (Normal/EAD)
    system_patterns = [
        r'microsoft\.com', r'windows\.com', r'windowsupdate\.com', r'live\.com', r'office\.com',
        r'google\.com', r'googleapis\.com', r'gstatic\.com', r'googleusercontent\.com',
        r'apple\.com', r'icloud\.com', r'adobe\.com', r'akamai\.net', r'aws\.amazon\.com',
        r'github\.com', r'githubusercontent\.com', r'mozilla\.net', r'digicert\.com',
        r'sectigo\.com', r'globalsign\.com'
    ]
    
    ead_patterns = [
        r'\.edu', r'\.gov', r'moodle', r'canvas', r'blackboard', r'classroom', r'teams', r'zoom',
        r'ead', r'ensino', r'estudo', r'escola', r'universidade', r'faculdade', r'senai', r'sesc',
        r'senac', r'sebrae'
    ]
    
    # Categories to filter IN (Strange/Entertainment/Search)
    search_patterns = [
        r'google\.com', r'bing\.com', r'yahoo\.com', r'duckduckgo\.com', r'baidu\.com'
    ]
    
    entertainment_patterns = [
        r'youtube\.com', r'googlevideo\.com', r'netflix\.com', r'spotify\.com', r'twitch\.tv',
        r'tiktok\.com', r'instagram\.com', r'facebook\.com', r'twitter\.com', r'x\.com',
        r'roblox\.com', r'steamcommunity\.com', r'discord\.com', r'whatsapp\.com', r'disney',
        r'hbo', r'primevideo'
    ]
    
    # Note: Google is in both, I'll handle it carefully
    
    domain_counts = Counter(domains)
    results = []

    for domain, count in domain_counts.most_common(200):
        is_normal = False
        
        # Check if it's EAD or System
        if any(re.search(p, domain) for p in ead_patterns):
            continue # Skip EAD
            
        if any(re.search(p, domain) for p in system_patterns):
            # Only skip if NOT a search engine (like google.com)
            if not any(re.search(p, domain) for p in search_patterns):
                continue
        
        # If it's search or entertainment, it's "strange" for this request
        category = "Outro"
        if any(re.search(p, domain) for p in search_patterns):
            category = "Pesquisa"
        elif any(re.search(p, domain) for p in entertainment_patterns):
            category = "Entretenimento"
        
        results.append((domain, count, category))

    # Print results
    print(f"{'Domínio':<50} | {'Acessos':<8} | {'Categoria'}")
    print("-" * 75)
    for domain, count, cat in results:
        print(f"{domain:<50} | {count:<8} | {cat}")

import os
if __name__ == "__main__":
    analyze_logs()
