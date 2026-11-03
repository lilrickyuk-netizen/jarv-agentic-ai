"""Whether PyTorch in this image can use the NVIDIA GPU here (prints gpu and its name, or cpu and why)."""
import torch

if torch.cuda.is_available():
    props = torch.cuda.get_device_properties(0)
    print(f"gpu {props.name} {props.total_memory // (1024 * 1024)}MB torch {torch.__version__} cuda {torch.version.cuda}")
else:
    try:
        torch.zeros(1).cuda()
        print("cpu (no CUDA device)")
    except Exception as exc:  # noqa: BLE001
        print(f"cpu ({str(exc).splitlines()[0][:200]})")
