#!/bin/bash
# Live Translator startup script
#
# Installation options:
#   pip install -e .          # Install as editable package
#   live-translator           # Run using console script
#   python -m live_translator # Run as module
#
cd "$(dirname "$0")"

# Add cuDNN libraries to path for CUDA support
CUDNN_PATH="./venv/lib/python3.12/site-packages/nvidia/cudnn/lib"
CUBLAS_PATH="./venv/lib/python3.12/site-packages/nvidia/cublas/lib"

if [ -d "$CUDNN_PATH" ]; then
    export LD_LIBRARY_PATH="$CUDNN_PATH:$CUBLAS_PATH:$LD_LIBRARY_PATH"
fi

# Add src to Python path and run
export PYTHONPATH="$PWD/src:$PYTHONPATH"
./venv/bin/python -m live_translator "$@"
