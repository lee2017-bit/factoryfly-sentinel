# Security and Privacy

Do not commit:

- SSH private keys
- real Radeon Cloud hosts and ports
- cloud tokens or credentials
- personal absolute paths
- private raw videos without consent
- generated virtual environments, caches, checkpoints, or archives

The public source package uses portable project paths and sanitized example
configuration files. Runtime settings are written locally under `shared/config/`
and are excluded by `.gitignore`.
