---
name: gpu-cuda-doctor
description: Inspect NVIDIA/AMD GPU VRAM, thermals, CUDA availability, and local Ollama/vLLM servers.
triggers: gpu, cuda, vram, nvidia, nvidia-smi, ollama, vllm, oom
---
# GPU & Local AI Doctor Runbook

1. Run `<gpu />` to capture `nvidia-smi` VRAM usage, temperature, and `:11434` / `:8000` model status.
2. Check if another process is holding VRAM (`fuser -v /dev/nvidia*`).
3. For Ollama OOM or slow inference, inspect `journalctl -u ollama -n 50` via `<systemd unit="ollama" />`.
4. Verify Docker GPU passthrough if running in containers with `<containers />`.
