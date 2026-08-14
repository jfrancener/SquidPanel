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
