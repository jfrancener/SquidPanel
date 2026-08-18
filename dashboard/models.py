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
    Suporta listas exclusivas (override) que têm prioridade sobre as listas do grupo.
    """
    STATUS_CHOICES = [
        ('ALLOWED', 'Liberado Total (100% Livre)'),
        ('BLACKLIST', 'Liberado com Blacklist'),
        ('WHITELIST', 'Apenas Whitelist (Padrão Seguro)'),
        ('BLOCKED', 'Bloqueio Total (Sem Acesso)'),
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

    # Listas exclusivas da porta (override do grupo)
    port_whitelists = models.ManyToManyField(
        'squid.ProxyList', blank=True,
        related_name='applied_ports_whitelist',
        help_text='Whitelists exclusivas desta porta (têm prioridade sobre as listas do grupo)'
    )
    port_blacklists = models.ManyToManyField(
        'squid.ProxyList', blank=True,
        related_name='applied_ports_blacklist',
        help_text='Blacklists exclusivas desta porta (têm prioridade sobre as listas do grupo)'
    )

    use_custom_portal = models.BooleanField(
        default=False,
        verbose_name="Usar Portal de Bloqueio Personalizado",
        help_text="Redireciona acessos negados para o portal educacional com lista de links permitidos"
    )

    # Rastreamento de quem/o que alterou o status da sala (Usuário ou Agendamento)
    last_status_source = models.CharField(max_length=50, default='MANUAL', verbose_name="Origem da Última Alteração") # 'MANUAL' ou 'SCHEDULE'
    last_modified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='ports_modified', verbose_name="Último Usuário a Modificar")
    active_schedule = models.ForeignKey('RoomSchedule', on_delete=models.SET_NULL, null=True, blank=True, related_name='active_on_ports', verbose_name="Agendamento em Vigor")

    def __str__(self):
        return f"{self.name} (Porta {self.port_number})"

    @property
    def status_source_info(self):
        """
        Retorna informações formatadas sobre quem/o que definiu o status atual da sala.
        """
        now = timezone.localtime(timezone.now())

        # 1. Se estiver sob efeito de um agendamento ativo
        if self.last_status_source == 'SCHEDULE' and self.active_schedule and self.active_schedule.is_in_effect_now(now):
            end_t = self.active_schedule.end_time.strftime('%H:%M')
            if self.current_status == 'ALLOWED':
                return {
                    'type': 'SCHEDULE',
                    'title': 'Livre por agendamento',
                    'detail': f"Agendamento '{self.active_schedule.name}' (bloqueia às {end_t})",
                    'short': f"Agendamento (até {end_t})",
                    'badge_class': 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30',
                    'icon': 'fa-solid fa-globe text-emerald-400',
                    'end_time': end_t
                }
            elif self.current_status == 'BLACKLIST':
                return {
                    'type': 'SCHEDULE',
                    'title': 'Navegação Segura por agendamento',
                    'detail': f"Agendamento '{self.active_schedule.name}' (bloqueia às {end_t})",
                    'short': f"Agendamento (até {end_t})",
                    'badge_class': 'bg-amber-500/15 text-amber-300 border border-amber-500/30',
                    'icon': 'fa-solid fa-shield-halved text-amber-400',
                    'end_time': end_t
                }
            elif self.current_status == 'WHITELIST':
                return {
                    'type': 'SCHEDULE',
                    'title': 'Navegação Restrita por agendamento',
                    'detail': f"Agendamento '{self.active_schedule.name}' (até às {end_t})",
                    'short': f"Agendamento (até {end_t})",
                    'badge_class': 'bg-indigo-500/15 text-indigo-300 border border-indigo-500/30',
                    'icon': 'fa-solid fa-filter text-indigo-400',
                    'end_time': end_t
                }
            else:
                return {
                    'type': 'SCHEDULE',
                    'title': 'Bloqueado por agendamento',
                    'detail': f"Agendamento '{self.active_schedule.name}' (até às {end_t})",
                    'short': f"Agendamento (até {end_t})",
                    'badge_class': 'bg-rose-500/15 text-rose-300 border border-rose-500/30',
                    'icon': 'fa-solid fa-calendar-xmark text-rose-400',
                    'end_time': end_t
                }

        # 2. Se foi alterado por usuário manualmente
        if self.last_modified_by:
            user_name = self.last_modified_by.first_name or self.last_modified_by.username
            if self.current_status == 'ALLOWED':
                action_word = "Livre"
            elif self.current_status == 'BLACKLIST':
                action_word = "Navegação Segura"
            elif self.current_status == 'WHITELIST':
                action_word = "Navegação Restrita"
            else:
                action_word = "Bloqueado"

            return {
                'type': 'MANUAL',
                'title': f"{action_word} por {user_name}",
                'detail': f"{action_word} manualmente pelo usuário {user_name}",
                'short': f"Usuário: {user_name}",
                'badge_class': 'bg-slate-800 text-slate-300 border border-slate-700',
                'icon': 'fa-solid fa-user-gear text-slate-400',
                'end_time': ''
            }

        # 3. Padrão do sistema
        return {
            'type': 'DEFAULT',
            'title': 'Padrão do Sistema',
            'detail': 'Configuração padrão do sistema',
            'short': 'Padrão',
            'badge_class': 'bg-slate-800/60 text-slate-400 border border-slate-700/60',
            'icon': 'fa-solid fa-server text-slate-500',
            'end_time': ''
        }

    @property
    def active_schedules_list(self):
        """
        Retorna a lista de agendamentos habilitados para esta sala.
        """
        now = timezone.localtime(timezone.now())
        schedules = list(self.schedules.filter(is_enabled=True).order_by('start_time'))
        for s in schedules:
            s.is_active_now = s.is_in_effect_now(now)
        return schedules

    @property
    def schedule_summary(self):
        """
        Retorna um resumo conciso do agendamento configurado para a sala:
        Dias/Data, Horário de Liberação e Horário de Bloqueio.
        """
        schedules = self.active_schedules_list
        if not schedules:
            return None

        # Prioriza o agendamento que está em vigor agora
        active = next((s for s in schedules if getattr(s, 'is_active_now', False)), None)
        target = active or schedules[0]

        start_h = target.start_time.strftime('%H:%M')
        end_h = target.end_time.strftime('%H:%M')
        days = target.days_display

        action_map = {
            'ALLOWED': 'Livre',
            'BLACKLIST': 'Navegação Segura',
            'WHITELIST': 'Navegação Restrita',
            'BLOCKED': 'Bloqueado'
        }
        act_label = action_map.get(target.action, target.action)
        rev_label = action_map.get(target.revert_action, 'Bloqueado')

        return {
            'has_schedule': True,
            'is_active_now': getattr(target, 'is_active_now', False),
            'name': target.name,
            'days': days,
            'start_time': start_h,
            'end_time': end_h,
            'action_label': act_label,
            'revert_label': rev_label,
            'count': len(schedules),
            'text': f"{days}: Libera {start_h} • Bloqueia {end_h}",
        }

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            self.slug = slugify(f"{self.name}-{self.port_number}")
        super().save(*args, **kwargs)


class RoomSchedule(models.Model):
    """
    Agendamentos de horários para liberação/bloqueio automático das salas.
    Suporta regras recorrentes por dias da semana e agendamentos pontuais (data específica).
    """
    SCHEDULE_TYPE_CHOICES = [
        ('RECURRENT', 'Recorrente (Dias da Semana)'),
        ('ONETIME', 'Pontual (Data Específica)'),
    ]
    ACTION_CHOICES = [
        ('BLACKLIST', 'Navegação Segura (Blacklist)'),
        ('WHITELIST', 'Navegação Restrita (Whitelist)'),
        ('ALLOWED', 'Livre (Acesso Total)'),
        ('BLOCKED', 'Bloqueado'),
    ]

    port = models.ForeignKey(ProxyPort, on_delete=models.CASCADE, related_name='schedules', verbose_name="Sala / Porta")
    name = models.CharField(max_length=150, verbose_name="Nome do Agendamento")
    schedule_type = models.CharField(max_length=20, choices=SCHEDULE_TYPE_CHOICES, default='RECURRENT', verbose_name="Tipo de Agendamento")
    
    # Campo para data específica (quando schedule_type == 'ONETIME')
    specific_date = models.DateField(null=True, blank=True, verbose_name="Data Específica")
    
    # Dias da semana: '0,1,2,3,4' onde 0=Segunda, 1=Terça, 2=Quarta, 3=Quinta, 4=Sexta, 5=Sábado, 6=Domingo
    days_of_week = models.CharField(max_length=50, default='0,1,2,3,4', verbose_name="Dias da Semana")
    
    start_time = models.TimeField(verbose_name="Horário de Início")
    end_time = models.TimeField(verbose_name="Horário de Término")
    
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, default='ALLOWED', verbose_name="Ação no Período")
    revert_action = models.CharField(max_length=20, choices=ACTION_CHOICES, default='BLOCKED', verbose_name="Ação Após Término")
    
    is_enabled = models.BooleanField(default=True, verbose_name="Ativo / Habilitado")
    current_state = models.CharField(max_length=20, default='INACTIVE', verbose_name="Estado Atual") # 'ACTIVE' ou 'INACTIVE'
    last_run_at = models.DateTimeField(null=True, blank=True, verbose_name="Última Execução")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='schedules_created')
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Criado em")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "Agendamento de Sala"
        verbose_name_plural = "Agendamentos de Salas"
        ordering = ['start_time', 'name']

    def __str__(self):
        return f"{self.name} - {self.port.name} ({self.start_time.strftime('%H:%M')} às {self.end_time.strftime('%H:%M')})"

    @property
    def days_display(self):
        if self.schedule_type == 'ONETIME':
            return self.specific_date.strftime('%d/%m/%Y') if self.specific_date else 'Data Não Definida'
        
        day_map = {
            '0': 'Seg', '1': 'Ter', '2': 'Qua', '3': 'Qui',
            '4': 'Sex', '5': 'Sáb', '6': 'Dom'
        }
        days = [d.strip() for d in (self.days_of_week or '').split(',') if d.strip() in day_map]
        
        if set(days) == {'0', '1', '2', '3', '4'}:
            return "Seg a Sex (Dias Úteis)"
        elif len(days) == 7:
            return "Todos os Dias"
        elif not days:
            return "Nenhum dia"
        return ", ".join([day_map[d] for d in sorted(days)])

    def is_in_effect_now(self, check_dt=None):
        """
        Verifica se o agendamento deve estar em vigor no instante fornecido (ou agora).
        """
        if not self.is_enabled:
            return False
        
        if check_dt is None:
            check_dt = timezone.localtime(timezone.now())
        
        current_date = check_dt.date()
        current_time = check_dt.time()
        current_weekday = str(check_dt.weekday()) # 0=Segunda, 6=Domingo

        # Validação do dia
        if self.schedule_type == 'ONETIME':
            if self.specific_date != current_date:
                return False
        else:
            active_days = [d.strip() for d in (self.days_of_week or '').split(',')]
            if current_weekday not in active_days:
                return False

        # Validação do horário
        if self.start_time <= self.end_time:
            return self.start_time <= current_time < self.end_time
        else:
            # Caso atravesse a meia-noite (ex: 22:00 às 06:00)
            return current_time >= self.start_time or current_time < self.end_time


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
