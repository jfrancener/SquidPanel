from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
import json

class SystemSetting(models.Model):
    """
    Armazena configurações dinâmicas do sistema que podem ser alteradas pelo painel sem reiniciar o servidor.
    """
    key = models.CharField(max_length=60, unique=True)
    value = models.TextField()
    description = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.key}: {self.value}"

    @classmethod
    def get_value(cls, key, default=None):
        try:
            setting = cls.objects.filter(key=key).first()
            if setting:
                return setting.value
        except Exception:
            pass
        return default

    @classmethod
    def set_value(cls, key, value, description=""):
        obj, created = cls.objects.get_or_create(key=key)
        obj.value = str(value)
        if description:
            obj.description = description
        obj.save()
        return obj


class ProxyGroup(models.Model):
    """
    Grupo de controle (ex: Administrativo, Salas de Aula, Laboratório).
    """
    POLICY_CHOICES = [
        ('WHITELIST_STRICT', 'Bloqueio Total (Apenas Whitelist)'),
        ('SCHEDULED', 'Temporizado / Horários Programados'),
        ('BLACKLIST_ONLY', 'Liberado Geral com Blacklist'),
    ]
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True)
    default_policy = models.CharField(max_length=30, choices=POLICY_CHOICES, default='WHITELIST_STRICT')
    whitelists = models.ManyToManyField('squid.ProxyList', blank=True, related_name='applied_groups_whitelist')
    blacklists = models.ManyToManyField('squid.ProxyList', blank=True, related_name='applied_groups_blacklist')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.name


class ProxyPort(models.Model):
    """
    Porta de escuta do Squid mapeada para uma sala ou setor.
    """
    STATUS_CHOICES = [
        ('BLOCKED', 'Bloqueada (Sem Acesso)'),
        ('WHITELIST', 'Whitelist Básica'),
        ('ALLOWED', 'Liberada Total (Acesso Completo)'),
        ('SCHEDULED', 'Agendamento / Horário Automático'),
    ]
    group = models.ForeignKey(ProxyGroup, on_delete=models.CASCADE, related_name='ports')
    port_number = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=100) # Ex: Sala 1, Sala 5, TI Admin
    slug = models.SlugField(max_length=100, unique=True)
    current_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='WHITELIST')
    temp_allowed_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} (Porta {self.port_number})"

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            self.slug = slugify(f"{self.name}-{self.port_number}")
        super().save(*args, **kwargs)


class RoomSchedule(models.Model):
    """
    Agendamentos recorrentes de horários para liberação automática das salas.
    """
    port = models.ForeignKey(ProxyPort, on_delete=models.CASCADE, related_name='schedules')
    name = models.CharField(max_length=100, blank=True)
    days_of_week = models.CharField(max_length=10, default='MTWHF') # M=Seg, T=Ter, W=Qua, H=Qui, F=Sex, A=Sab, S=Dom
    start_time = models.TimeField()
    end_time = models.TimeField()
    action = models.CharField(max_length=20, default='ALLOW_ALL')
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.port.name} - {self.days_of_week} ({self.start_time} - {self.end_time})"


class DomainRule(models.Model):
    """
    Regras de domínios (Whitelist e Blacklist) vinculadas a grupos.
    """
    RULE_TYPE_CHOICES = [
        ('allow', 'Permitido (Whitelist)'),
        ('block', 'Bloqueado (Blacklist)'),
        ('hide', 'Oculto / Ignorado'),
    ]
    group = models.ForeignKey(ProxyGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name='domain_rules')
    domain = models.CharField(max_length=255, unique=True)
    rule_type = models.CharField(max_length=10, choices=RULE_TYPE_CHOICES, default='allow')
    is_verified = models.BooleanField(default=False)
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.domain} ({self.rule_type})"


class UserProfile(models.Model):
    """
    Perfil estendido de usuário com Nível de Acesso (RBAC) e grupos/portas autorizados.
    """
    ROLE_CHOICES = [
        ('ADMIN', 'Administrador Geral (TI)'),
        ('MANAGER', 'Coordenador / Gestor de Setor'),
        ('OPERATOR', 'Operador / Professor'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='OPERATOR')
    allowed_groups = models.ManyToManyField(ProxyGroup, blank=True, related_name='authorized_users')
    allowed_ports = models.ManyToManyField(ProxyPort, blank=True, related_name='authorized_users')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"

    @property
    def is_admin(self):
        return self.role == 'ADMIN' or self.user.is_superuser or self.user.is_staff

    @property
    def is_manager(self):
        return self.role in ['ADMIN', 'MANAGER'] or self.user.is_superuser or self.user.is_staff

    @property
    def role_display_name(self):
        if self.user.is_superuser or self.user.is_staff or self.role == 'ADMIN':
            return 'Administrador Geral (TI)'
        elif self.role == 'MANAGER':
            return 'Coordenador / Gestor'
        return 'Operador / Professor'


# Garante que todo usuário Django criado tenha um UserProfile automático
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    profile, _ = UserProfile.objects.get_or_create(user=instance)
    if instance.is_superuser and profile.role != 'ADMIN':
        profile.role = 'ADMIN'
        profile.save()
