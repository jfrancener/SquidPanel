from django.db import models
from django.utils import timezone
from django.utils.text import slugify

class ProxyList(models.Model):
    """
    Lista temática e reutilizável de domínios (Whitelist ou Blacklist).
    Pode ser aplicada simultaneamente a um ou múltiplos grupos de navegação.
    """
    LIST_TYPE_CHOICES = [
        ('WHITELIST', 'Whitelist (Permitidos)'),
        ('BLACKLIST', 'Blacklist (Bloqueados)'),
    ]
    
    COLOR_CHOICES = [
        ('indigo', 'Índigo'),
        ('emerald', 'Esmeralda / Verde'),
        ('cyan', 'Ciano / Azul Claro'),
        ('purple', 'Roxo / Púrpura'),
        ('amber', 'Âmbar / Laranja'),
        ('rose', 'Rosa / Vermelho'),
        ('blue', 'Azul Real'),
    ]

    name = models.CharField(max_length=100, unique=True, verbose_name="Nome da Lista")
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    list_type = models.CharField(max_length=20, choices=LIST_TYPE_CHOICES, default='WHITELIST')
    color = models.CharField(max_length=20, choices=COLOR_CHOICES, default='emerald')
    description = models.CharField(max_length=255, blank=True, verbose_name="Descrição")
    is_mandatory = models.BooleanField(default=False, verbose_name="Obrigatória do Sistema")
    is_active = models.BooleanField(default=True, verbose_name="Ativa")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Lista de Proxy"
        verbose_name_plural = "Listas de Proxy"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.get_list_type_display()})"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def domain_count(self):
        return self.domains.filter(is_active=True).count()

    @property
    def applied_groups(self):
        if self.list_type == 'WHITELIST':
            return self.applied_groups_whitelist.filter(is_active=True)
        return self.applied_groups_blacklist.filter(is_active=True)


class DomainItem(models.Model):
    """
    Domínio cadastrado dentro de uma lista específica.
    """
    proxy_list = models.ForeignKey(ProxyList, on_delete=models.CASCADE, related_name='domains')
    domain = models.CharField(max_length=255, verbose_name="Domínio")
    description = models.CharField(max_length=255, blank=True, verbose_name="Observação")
    is_active = models.BooleanField(default=True, verbose_name="Ativo")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Domínio"
        verbose_name_plural = "Domínios"
        unique_together = ('proxy_list', 'domain')
        ordering = ['domain']

    def __str__(self):
        return f"{self.domain} [{self.proxy_list.name}]"

    def clean_domain(self):
        d = self.domain.strip().lower()
        if d.startswith('http://'):
            d = d[7:]
        elif d.startswith('https://'):
            d = d[8:]
        d = d.split('/')[0].split(':')[0]
        if d.startswith('*.'):
            d = f".{d[2:]}"
        return d

    def save(self, *args, **kwargs):
        self.domain = self.clean_domain()
        super().save(*args, **kwargs)


class AccessLog(models.Model):
    """
    Registro histórico de requisições processadas pelo Proxy Squid.
    Permite consultas avançadas por data, hora, porta, grupo, status e monitoramento em tempo real.
    """
    ACTION_CHOICES = [
        ('ALLOWED', 'Permitido (Liberado)'),
        ('BLOCKED', 'Bloqueado (Negado)'),
        ('DIRECT', 'Acesso Direto'),
    ]

    timestamp = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="Data / Hora")
    client_ip = models.CharField(max_length=45, verbose_name="IP do Cliente")
    hostname = models.CharField(max_length=100, blank=True, db_index=True, verbose_name="Hostname do Equipamento")
    port_number = models.PositiveIntegerField(db_index=True, verbose_name="Porta Proxy")
    port = models.ForeignKey('dashboard.ProxyPort', on_delete=models.SET_NULL, null=True, blank=True, related_name='access_logs')
    group = models.ForeignKey('dashboard.ProxyGroup', on_delete=models.SET_NULL, null=True, blank=True, related_name='access_logs')
    
    method = models.CharField(max_length=15, default='CONNECT', verbose_name="Método")
    domain = models.CharField(max_length=255, db_index=True, verbose_name="Domínio Requisitado")
    full_url = models.CharField(max_length=1000, blank=True, verbose_name="URL Completa")
    
    http_status = models.CharField(max_length=50, default='TCP_TUNNEL/200', verbose_name="Código / Status Squid")
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, default='ALLOWED', verbose_name="Ação")
    bytes_sent = models.BigIntegerField(default=0, verbose_name="Bytes Trafegados")
    response_time_ms = models.IntegerField(default=0, verbose_name="Latência (ms)")
    mime_type = models.CharField(max_length=100, default='-', verbose_name="Tipo MIME")

    class Meta:
        verbose_name = "Log de Acesso"
        verbose_name_plural = "Logs de Acesso"
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp', 'port_number']),
            models.Index(fields=['domain']),
            models.Index(fields=['action']),
            models.Index(fields=['hostname']),
        ]

    def __str__(self):
        return f"[{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] {self.client_ip} -> {self.domain} ({self.action})"

    @property
    def status_code(self):
        if not self.http_status:
            return '200'
        if '/' in self.http_status:
            code = self.http_status.split('/')[1]
            return code if code.isdigit() else '200'
        parts = self.http_status.split()
        for p in parts:
            if p.isdigit() and len(p) == 3:
                return p
        return '200'

    @property
    def is_proxy_blocked(self):
        status_upper = (self.http_status or '').upper()
        return self.action == 'BLOCKED' or 'DENIED' in status_upper or 'ERR_ACCESS_DENIED' in status_upper or status_upper.startswith('TCP_DENIED') or status_upper.startswith('UDP_DENIED') or status_upper.startswith('NONE/403')

    @property
    def is_dest_blocked(self):
        if self.is_proxy_blocked:
            return False
        return self.status_code in ['401', '403', '407', '429']

    @property
    def status_category(self):
        if self.is_proxy_blocked:
            return 'proxy_blocked'
        if self.is_dest_blocked:
            return 'dest_blocked'
        return 'allowed'

    @property
    def is_blocked(self):
        return self.is_proxy_blocked or self.is_dest_blocked

    @property
    def formatted_bytes(self):
        if self.bytes_sent < 1024:
            return f"{self.bytes_sent} B"
        elif self.bytes_sent < 1024 * 1024:
            return f"{self.bytes_sent / 1024:.1f} KB"
        return f"{self.bytes_sent / (1024 * 1024):.1f} MB"


class DeviceHost(models.Model):
    """
    Mapeamento de endereço IP para Hostname / Nome amigável do Equipamento.
    Permite identificar exatamente qual computador/terminal da sala fez a requisição.
    """
    ip_address = models.GenericIPAddressField(unique=True, db_index=True, verbose_name="Endereço IP")
    hostname = models.CharField(max_length=100, verbose_name="Nome / Hostname do Equipamento")
    description = models.CharField(max_length=255, blank=True, verbose_name="Descrição / Localização")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Equipamento / Hostname"
        verbose_name_plural = "Equipamentos / Hostnames"
        ordering = ['hostname', 'ip_address']

    def __str__(self):
        return f"{self.hostname} ({self.ip_address})"


class HiddenDomain(models.Model):
    """
    Domínios que devem ser ocultados do Monitor em Tempo Real (Live Stream).
    Permite silenciar ruídos, telemetrias, CDNs e domínios frequentes cadastrados pelo usuário.
    """
    domain = models.CharField(max_length=255, unique=True, db_index=True, verbose_name="Domínio a Ocultar")
    description = models.CharField(max_length=255, blank=True, verbose_name="Motivo / Descrição")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Criado em")

    class Meta:
        verbose_name = "Domínio Oculto no Live"
        verbose_name_plural = "Domínios Ocultos no Live"
        ordering = ['domain']

    def __str__(self):
        return self.domain

    def clean_domain(self):
        d = self.domain.strip().lower()
        if '://' in d:
            from urllib.parse import urlparse
            d = urlparse(d).hostname or d
        else:
            d = d.split(':')[0].split('/')[0]
        return d.lstrip('.')


class PortalLink(models.Model):
    """
    Links e atalhos permitidos exibidos na página de bloqueio/portal educacional (ex: Portal EAD, Google Scholar, Dicionários).
    """
    CATEGORY_CHOICES = [
        ('FACULDADES', 'Faculdades & Portais Acadêmicos'),
        ('PESQUISA', 'Pesquisa & Bibliotecas Virtuais'),
        ('DICIONARIOS', 'Dicionários & Enciclopédias'),
        ('FERRAMENTAS', 'Ferramentas & Recursos Educacionais'),
        ('OUTROS', 'Outros Links Autorizados'),
    ]

    title = models.CharField(max_length=150, verbose_name="Título / Nome do Site")
    url = models.URLField(max_length=500, verbose_name="Endereço URL (ex: https://...)")
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='FACULDADES', verbose_name="Categoria")
    description = models.CharField(max_length=255, blank=True, verbose_name="Descrição Curta")
    icon = models.CharField(max_length=50, default='fa-graduation-cap', verbose_name="Ícone FontAwesome")
    port = models.ForeignKey(
        'dashboard.ProxyPort',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='portal_links',
        verbose_name="Porta / Sala Específica",
        help_text="Selecione uma porta específica ou deixe em branco para todas as salas com portal ativo"
    )
    is_active = models.BooleanField(default=True, verbose_name="Ativo")
    display_order = models.IntegerField(default=0, verbose_name="Ordem de Exibição")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Criado em")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "Link do Portal"
        verbose_name_plural = "Links do Portal"
        ordering = ['display_order', 'title']

    def __str__(self):
        return f"{self.title} ({self.get_category_display()})"


class AllowedRefererHub(models.Model):
    """
    Portais e Buscadores com Sublinks Liberados (Referer Whitelist).
    Permite abrir links externos e resultados derivados desde que o clique tenha se originado
    de um dos domínios autorizados cadastrados nesta tabela (ex: scholar.google.com, scielo.br).
    """
    name = models.CharField(max_length=150, verbose_name="Nome do Portal / Buscador")
    domain_pattern = models.CharField(
        max_length=255, 
        verbose_name="Domínio / Padrão de Origem (ex: scholar.google.com)",
        help_text="Domínio ou regex do site de busca/portal que permite navegar nos resultados"
    )
    description = models.CharField(max_length=255, blank=True, verbose_name="Descrição / Finalidade")
    is_active = models.BooleanField(default=True, verbose_name="Ativo")
    ports = models.ManyToManyField(
        'dashboard.ProxyPort',
        blank=True,
        related_name='allowed_referer_hubs',
        verbose_name="Salas / Portas Aplicadas",
        help_text="Deixe em branco para aplicar a todas as salas com Whitelist ativa"
    )
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Criado em")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "Sublinks Liberados (Referer Hub)"
        verbose_name_plural = "Sublinks Liberados (Referer Hubs)"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.domain_pattern})"

    def clean_pattern(self):
        d = self.domain_pattern.strip().lower()
        if '://' in d:
            from urllib.parse import urlparse
            d = urlparse(d).hostname or d
        return d.lstrip('.')


class DiscoveredSublink(models.Model):
    """
    Domínios externos que foram acessados dinamicamente através de cliques em Sublinks/Buscadores (Referer Hubs).
    Registra a frequência de acesso e permite ao administrador promover o domínio para uma Whitelist definitiva com 1 clique.
    """
    domain = models.CharField(max_length=255, unique=True, db_index=True, verbose_name="Domínio Acessado")
    origin_hub = models.ForeignKey(
        AllowedRefererHub, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='discovered_links',
        verbose_name="Buscador de Origem"
    )
    last_requested_url = models.URLField(max_length=500, blank=True, verbose_name="Última URL Acessada")
    hit_count = models.PositiveIntegerField(default=1, verbose_name="Vezes Acessado")
    first_seen = models.DateTimeField(default=timezone.now, verbose_name="Primeiro Acesso")
    last_seen = models.DateTimeField(auto_now=True, verbose_name="Último Acesso")
    ai_analysis = models.JSONField(null=True, blank=True, verbose_name="Análise de IA")
    # Estrutura: {"is_cdn": bool, "cdn_of": str|null, "importance": "high"|"medium"|"low",
    #              "recommendation": "whitelist"|"block"|"monitor", "reason": str, "model": str}
    ai_analyzed_at = models.DateTimeField(null=True, blank=True, verbose_name="Data da Análise de IA")

    class Meta:
        verbose_name = "Sublink Descoberto / Acessado"
        verbose_name_plural = "Sublinks Descobertos / Acessados"
        ordering = ['-last_seen']

    def __str__(self):
        return f"{self.domain} ({self.hit_count} acessos)"

    @property
    def is_in_whitelist(self):
        """Verifica se este domínio ou seu domínio pai já está cadastrado em alguma Whitelist ativa"""
        clean = self.domain.strip().lower().lstrip('.')
        active_wl_domains = DomainItem.objects.filter(
            proxy_list__list_type='WHITELIST',
            proxy_list__is_active=True,
            is_active=True
        ).values_list('domain', flat=True)

        for wl_d in active_wl_domains:
            base = wl_d.strip().lower().lstrip('.')
            if clean == base or clean.endswith('.' + base):
                return True
        return False
