import subprocess
import time
import sys

def run_ssh():
    print("Iniciando SSH...")
    cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "root@10.40.89.15", "apt-get update && apt-get install -y goaccess nginx sshpass"]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    
    print("Aguardando 3 segundos para enviar senha...")
    time.sleep(3)
    proc.stdin.write("@Jufran0803\n")
    proc.stdin.flush()
    print("Senha enviada.")
    
    while True:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        print(f"OUT: {line.strip()}")
        sys.stdout.flush()
    
    print(f"Processo finalizado com código: {proc.returncode}")

if __name__ == "__main__":
    run_ssh()
