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
        # Remove http://, https:// e barras
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
    def is_blocked(self):
        return self.action == 'BLOCKED' or 'DENIED' in self.http_status or '403' in self.http_status

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


