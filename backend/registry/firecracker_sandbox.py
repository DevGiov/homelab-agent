import base64
import json
import logging
import subprocess
import time
from typing import Any, Dict

import requests

import config

logger = logging.getLogger("firecracker_sandbox")

class FirecrackerSandbox:
    def __init__(self):
        self.api_url = config.FIRECRACKER_API_URL
        self.log_url = config.FIRECRACKER_LOG_URL
        self.kernel_path = config.FIRECRACKER_KERNEL_PATH
        self.rootfs_path = config.FIRECRACKER_ROOTFS_PATH

    def is_available(self) -> bool:
        """Verifica se l'API HTTP di Firecracker è raggiungibile."""
        try:
            res = requests.get(f"{self.api_url}/machine-config", timeout=2)
            return res.status_code in [200, 400]  # 200 = ready, 400 = microVM is running
        except requests.RequestException:
            return False

    def execute_code(self, code: str, timeout: int = 10) -> Dict[str, Any]:
        """
        Esegue codice Python in una microVM Firecracker reale col Guest Runner.
        Non ripiega mai da sola sull'esecuzione locale: se la sandbox non è utilizzabile
        ritorna `sandbox_unavailable=True` e la decisione (approvazione) spetta al chiamante.
        """
        if not self.is_available():
            return self._unavailable(f"API Firecracker non raggiungibile su {self.api_url}")

        try:
            # 1. Base64 del codice Python per i boot_args del kernel
            b64_code = base64.b64encode(code.encode("utf-8")).decode("utf-8")
            boot_args = f"console=ttyS0 quiet panic=1 pci=off init=/usr/local/bin/guest_runner.sh b64payload={b64_code}"

            # Invia SendCtrlAltDel per riavviare se un'istanza precedente era attiva
            try:
                requests.put(f"{self.api_url}/actions", json={"action_type": "SendCtrlAltDel"}, timeout=1.5)
                time.sleep(0.3)
            except Exception:
                pass

            # 2. Configurazione ed Avvio MicroVM via REST API (con retry brevi)
            res_boot = None
            for _ in range(5):
                try:
                    r = requests.put(f"{self.api_url}/boot-source", json={
                        "kernel_image_path": self.kernel_path,
                        "boot_args": boot_args
                    }, timeout=3)
                    if r.status_code == 204:
                        res_boot = r
                        break
                except Exception:
                    pass
                time.sleep(0.2)

            if not res_boot:
                return self._unavailable("impossibile configurare il boot-source della microVM")

            res_root = requests.put(f"{self.api_url}/drives/rootfs", json={
                "drive_id": "rootfs",
                "path_on_host": self.rootfs_path,
                "is_root_device": True,
                "is_read_only": True
            }, timeout=3)
            res_root.raise_for_status()

            res_start = requests.put(f"{self.api_url}/actions", json={
                "action_type": "InstanceStart"
            }, timeout=3)
            res_start.raise_for_status()

            # 3. Attesa del risultato scansionando l'output console HTTP
            start_time = time.time()
            res_data = None

            while time.time() - start_time < timeout:
                time.sleep(0.3)
                try:
                    c_res = requests.get(self.log_url, timeout=2)
                    if c_res.status_code == 200:
                        txt = c_res.text
                        if "<<<RESULT_START>>>" in txt and "<<<RESULT_END>>>" in txt:
                            s_idx = txt.find("<<<RESULT_START>>>") + len("<<<RESULT_START>>>")
                            e_idx = txt.find("<<<RESULT_END>>>")
                            b64_json = txt[s_idx:e_idx].strip()
                            res_json_str = base64.b64decode(b64_json).decode("utf-8")
                            res_data = json.loads(res_json_str)
                            break
                except requests.RequestException:
                    pass

            if not res_data:
                return self._unavailable(f"nessun risultato dalla microVM entro {timeout}s")

            return {
                "output": res_data.get("output", ""),
                "success": res_data.get("success", False),
                "sandboxed": True,
                "error": res_data.get("error")
            }

        except Exception as e:
            return self._unavailable(f"errore della microVM: {e}")

    @staticmethod
    def _unavailable(reason: str) -> Dict[str, Any]:
        logger.warning(f"Sandbox Firecracker non utilizzabile: {reason}")
        return {"output": "", "success": False, "sandboxed": False, "sandbox_unavailable": True, "error": reason}

    def execute_local(self, code: str, timeout: int = 5) -> Dict[str, Any]:
        """Esecuzione NON isolata via subprocess nel container backend: solo dopo approvazione esplicita."""
        try:
            res = subprocess.run(
                ["python3", "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            stdout = res.stdout.strip()
            stderr = res.stderr.strip()
            if res.returncode == 0:
                return {"output": stdout, "success": True, "sandboxed": False, "error": None}
            else:
                return {"output": stdout, "success": False, "sandboxed": False, "error": stderr or f"Exit code {res.returncode}"}
        except subprocess.TimeoutExpired:
            return {"output": "", "success": False, "sandboxed": False, "error": f"Timeout esecuzione ({timeout}s) superato."}
        except Exception as e:
            return {"output": "", "success": False, "sandboxed": False, "error": str(e)}
