# JAI's image generator: ComfyUI (open source, GPL-3.0) with ComfyUI-GGUF, running FLUX.1-schnell (Apache-2.0)
# compressed to fit a 6 GB laptop GPU. PyTorch is the CUDA 12.8 build, which runs on any NVIDIA driver from the
# CUDA 12 family (CUDA's minor-version compatibility), so no driver update is needed; below CUDA 13 ComfyUI only turns
# off comfy-kitchen's optional fp8/fp4 kernels, which the GGUF models here do not use. The models are not in the
# image: fetch_models.py downloads them once into a volume, each checked against Hugging Face's SHA-256.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends git curl libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* && useradd --create-home --uid 1000 comfy

ARG COMFYUI_REF=v0.44.0
ARG GGUF_REF=6ea2651e7df66d7585f6ffee804b20e92fb38b8a
ARG TORCH_INDEX=https://download.pytorch.org/whl/cu128
WORKDIR /opt
RUN git clone --depth 1 --branch "$COMFYUI_REF" https://github.com/comfyanonymous/ComfyUI.git comfyui \
    && git clone https://github.com/city96/ComfyUI-GGUF.git comfyui/custom_nodes/ComfyUI-GGUF \
    && git -C comfyui/custom_nodes/ComfyUI-GGUF checkout "$GGUF_REF" \
    && rm -rf comfyui/.git comfyui/custom_nodes/ComfyUI-GGUF/.git
RUN pip install torch torchvision torchaudio --index-url "$TORCH_INDEX" \
    && pip install -r comfyui/requirements.txt -r comfyui/custom_nodes/ComfyUI-GGUF/requirements.txt
COPY fetch_models.py check_gpu.py /opt/jai/
RUN mkdir -p comfyui/models/unet comfyui/models/text_encoders comfyui/models/vae comfyui/output comfyui/input \
    comfyui/user && chown -R comfy:comfy /opt/comfyui

USER comfy
WORKDIR /opt/comfyui
EXPOSE 8188
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8188/system_stats || exit 1
# --offline: the interface never calls out; --reserve-vram 3.5: leaves room on the 6 GB card for JAI's voice
# (Chatterbox and Kokoro stay loaded), so images offload part of the model to memory and take longer instead.
CMD ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188", "--disable-auto-launch", "--offline", \
     "--reserve-vram", "3.5", "--disable-metadata"]
