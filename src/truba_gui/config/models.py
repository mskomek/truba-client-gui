from dataclasses import dataclass

@dataclass
class SSHConfig:
    host: str = ""
    port: int = 22
    username: str = ""
    password: str = ""
    key_path: str = ""
    host_key_policy: str = "accept-new"  # accept-new | strict
    x11_forwarding: bool = False
    dry_run: bool = False  # mock backend

@dataclass
class AppConfig:
    language: str = "tr"
