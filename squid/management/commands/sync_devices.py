from django.core.management.base import BaseCommand
from squid.tactical_sync import sync_devices_from_tactical
from squid.ad_sync import sync_devices_from_ad
from squid.log_service import sync_logs_from_squid_file, cleanup_old_logs


class Command(BaseCommand):
    help = 'Executa sincronização periódica automática de dispositivos (Tactical RMM + AD) e logs do Squid'

    def handle(self, *args, **options):
        self.stdout.write("Iniciando sincronização de dispositivos via Tactical RMM...")
        try:
            count_t, msg_t = sync_devices_from_tactical()
            self.stdout.write(self.style.SUCCESS(f"[Tactical RMM] {msg_t}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"[Tactical RMM Erro] {e}"))

        self.stdout.write("Iniciando sincronização de dispositivos via AD/DNS...")
        try:
            count_a, msg_a = sync_devices_from_ad()
            self.stdout.write(self.style.SUCCESS(f"[AD/DNS] {msg_a}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"[AD/DNS Erro] {e}"))

        self.stdout.write("Sincronizando logs pendentes do access.log...")
        try:
            logs_count = sync_logs_from_squid_file()
            self.stdout.write(self.style.SUCCESS(f"[Logs] {logs_count} novas linhas processadas."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"[Logs Erro] {e}"))

        self.stdout.write("Executando limpeza de logs antigos (política de retenção)...")
        try:
            deleted_count, retention_days = cleanup_old_logs()
            self.stdout.write(self.style.SUCCESS(f"[Retenção] {deleted_count} logs antigos com mais de {retention_days} dias foram removidos."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"[Retenção Erro] {e}"))

        self.stdout.write(self.style.SUCCESS("Rotina de sincronização concluída com sucesso!"))
