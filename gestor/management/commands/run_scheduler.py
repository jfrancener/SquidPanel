import time
from django.core.management.base import BaseCommand
from gestor.scheduler_service import process_room_schedules


class Command(BaseCommand):
    help = "Executa a verificação e aplicação dos agendamentos de horários das salas."

    def add_arguments(self, parser):
        parser.add_argument(
            '--loop',
            action='store_true',
            help='Executa em loop contínuo verificando a cada 60 segundos.',
        )

    def handle(self, *args, **options):
        is_loop = options.get('loop', False)

        if is_loop:
            self.stdout.write(self.style.SUCCESS("[*] SquidPanel Scheduler iniciado em modo contínuo (loop de 60s)..."))
            while True:
                res = process_room_schedules()
                if res['changed_count'] > 0:
                    self.stdout.write(self.style.SUCCESS(f"[{res['timestamp']}] {res['changed_count']} sala(s) alterada(s):"))
                    for line in res['log']:
                        self.stdout.write(f"  -> {line}")
                time.sleep(60)
        else:
            res = process_room_schedules()
            if res['changed_count'] > 0:
                self.stdout.write(self.style.SUCCESS(f"[{res['timestamp']}] {res['changed_count']} sala(s) alterada(s):"))
                for line in res['log']:
                    self.stdout.write(f"  -> {line}")
            else:
                self.stdout.write(f"[{res['timestamp']}] Verificação concluída. Nenhuma sala precisou de alteração.")
